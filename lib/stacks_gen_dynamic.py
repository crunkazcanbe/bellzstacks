#!/usr/bin/env python3
"""
stacks_gen_dynamic.py — Auto-generate Traefik dynamic config files
Scans compose stacks and generates routers, services, middlewares, TCP routes
Config-driven: reads from stacks.conf for domains, URLs, feature flags
"""
import re, os, sys, yaml

# ── Config defaults ───────────────────────────────────────────────────────────
DEFAULTS = {
    'PRIMARY_DOMAIN':    'example.com',
    'SECONDARY_DOMAIN':  'example.net',
    'AUTHENTIK_URL':     'http://authentik-server:9000',
    'CROWDSEC_URL':      'http://crowdsec-bouncer:8080',
    'SABLIER_URL':       'http://sablier:10000',
    'SABLIER_THEME':     'ghost',
    'SABLIER_DURATION':  '1h',
    'GEN_ROUTERS':       '1',
    'GEN_SERVICES':      '1',
    'GEN_MIDDLEWARES':   '1',
    'GEN_SABLIER':       '1',
    'GEN_TCP':           '1',
    'GEN_AUTH':          '1',   # include authentik middleware
    'GEN_CROWDSEC':      '1',   # include crowdsec middleware
    'GEN_DOMAIN':        'primary',  # primary|secondary|both
}

# TCP database port map
TCP_PORTS = {
    'postgres': 5432, 'postgresql': 5432,
    'mysql': 3306, 'mariadb': 3306,
    'mongo': 27017, 'mongodb': 27017,
    'redis': 6379,
    'mssql': 1433,
    'neo4j': 7687,
}

STANDARD_MIDDLEWARES = [
    'https-header', 'crowdsec-bouncer', 'authentik-auth',
    'global-retry', 'compress', 'inflight', 'buffering', 'rate-limit'
]

def load_conf(conf_path):
    cfg = dict(DEFAULTS)
    if os.path.exists(conf_path):
        for line in open(conf_path):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg

def get_service_port(svc_def):
    """Extract port from traefik label or common defaults."""
    labels = svc_def.get('labels', [])
    if isinstance(labels, dict):
        labels = [f"{k}={v}" for k, v in labels.items()]
    for l in labels:
        m = re.search(r'loadbalancer\.server\.port=(\d+)', str(l))
        if m: return int(m.group(1))
    # Common port defaults by image
    image = svc_def.get('image', '').lower()
    port_map = {
        'nginx': 80, 'apache': 80, 'caddy': 80,
        'grafana': 3000, 'prometheus': 9090,
        'gitea': 3000, 'nextcloud': 80,
        'vaultwarden': 80, 'portainer': 9000,
    }
    for k, p in port_map.items():
        if k in image: return p
    return 80

def is_tcp_service(name, svc_def):
    """Check if service is a TCP database."""
    name_lower = name.lower()
    for db in TCP_PORTS:
        if db in name_lower: return True
    image = svc_def.get('image', '').lower()
    for db in TCP_PORTS:
        if db in image: return True
    return False

def get_tcp_port(name, svc_def):
    name_lower = name.lower()
    for db, port in TCP_PORTS.items():
        if db in name_lower: return port
    image = svc_def.get('image', '').lower()
    for db, port in TCP_PORTS.items():
        if db in image: return port
    return None

def service_has_traefik(svc_def):
    labels = svc_def.get('labels', [])
    if isinstance(labels, dict):
        return labels.get('traefik.enable', 'false').lower() == 'true'
    for l in labels:
        if 'traefik.enable=true' in str(l).lower(): return True
    return False

def get_subdomain(name, svc_def):
    """Get subdomain from traefik label or derive from name."""
    labels = svc_def.get('labels', [])
    if isinstance(labels, dict):
        labels = [f"{k}={v}" for k, v in labels.items()]
    for l in labels:
        m = re.search(r'rule=Host\(`([^.]+)\.', str(l))
        if m: return m.group(1)
    # Derive from container name
    cname = svc_def.get('container_name', name)
    return cname.replace('_', '-').lower()

def gen_router(name, subdomain, domain, svc_name, sablier_mw, cfg):
    mws = []
    if sablier_mw: mws.append(sablier_mw)
    mws.append('https-header')
    if cfg.get('GEN_CROWDSEC') == '1': mws.append('crowdsec-bouncer')
    if cfg.get('GEN_AUTH') == '1': mws.append('authentik-auth')
    mws += ['global-retry', 'compress', 'inflight', 'buffering', 'rate-limit']
    mw_str = ', '.join(mws)
    return (
        f"    {name}-router:\n"
        f'      rule: "Host(`{subdomain}.{domain}`)"\n'
        f"      service: {svc_name}\n"
        f"      entryPoints: [web]\n"
        f"      middlewares: [{mw_str}]\n"
    )

def gen_service(name, container, port):
    return (
        f"    {name}-svc:\n"
        f"      loadBalancer:\n"
        f'        servers: [{{ url: "http://{container}:{port}" }}]\n'
    )

def gen_sablier_mw(name, container, cfg):
    return (
        f"    sablier-{name}:\n"
        f"      plugin:\n"
        f"        sablier:\n"
        f'          sablierUrl: "{cfg["SABLIER_URL"]}"\n'
        f'          sessionDuration: "{cfg["SABLIER_DURATION"]}"\n'
        f'          names: "{container}"\n'
        f"          dynamic:\n"
        f'            displayName: "{container}"\n'
        f'            provider: "docker"\n'
        f'            stopTimeout: "30s"\n'
        f'            refreshFrequency: "5s"\n'
        f'            theme: "{cfg["SABLIER_THEME"]}"\n'
        f'            timeout: "10m"\n'
        f'            warmupPeriod: "10s"\n'
        f'            healthCheckPath: "/"\n'
        f'            healthCheckInterval: "2s"\n'
        f"            scaling:\n"
        f"              replicas: 1\n"
        f"              minReplicas: 0\n"
        f"              maxReplicas: 1\n"
    )

def gen_tcp_router(name, subdomain, domain, port):
    return (
        f"    {name}-tcp:\n"
        f'      rule: "HostSNI(`{subdomain}.{domain}`)"\n'
        f"      entryPoints: [websecure]\n"
        f"      service: {name}-tcp-svc\n"
        f"      tls:\n"
        f"        passthrough: true\n"
    )

def gen_tcp_service(name, container, port):
    return (
        f"    {name}-tcp-svc:\n"
        f"      loadBalancer:\n"
        f"        servers:\n"
        f'          - address: "{container}:{port}"\n'
    )

def gen_standard_middlewares(cfg):
    auth_url = cfg['AUTHENTIK_URL']
    crowdsec_url = cfg['CROWDSEC_URL']
    return f"""
    https-header:
      headers:
        customRequestHeaders:
          X-Forwarded-Proto: "https"
        customResponseHeaders:
          X-Frame-Options: "SAMEORIGIN"
          X-Content-Type-Options: "nosniff"
          X-XSS-Protection: "1; mode=block"
          Referrer-Policy: "strict-origin-when-cross-origin"
          Strict-Transport-Security: "max-age=31536000; includeSubDomains; preload"
          Server: ""
          X-Robots-Tag: "noindex, nofollow"

    global-retry:
      retry:
        attempts: 3
        initialInterval: 100ms

    compress:
      compress:
        minResponseBodyBytes: 1024
        encodings: [zstd, br, gzip]

    inflight:
      inFlightReq:
        amount: 100
        sourceCriterion:
          ipStrategy: {{ depth: 1 }}

    buffering:
      buffering:
        maxRequestBodyBytes: 10485760
        memRequestBodyBytes: 2097152
        maxResponseBodyBytes: 10485760
        memResponseBodyBytes: 2097152
        retryExpression: "IsNetworkError() && Attempts() < 3"

    rate-limit:
      rateLimit:
        average: 100
        burst: 50
        period: 1s
        sourceCriterion:
          ipStrategy: {{ depth: 1 }}

    authentik-auth:
      forwardAuth:
        address: "{auth_url}/outpost.goauthentik.io/auth/traefik"
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-email
          - X-authentik-name
          - X-authentik-uid
          - X-authentik-jwt

    crowdsec-bouncer:
      forwardAuth:
        address: "{crowdsec_url}/api/v1/forwardAuth"
        trustForwardHeader: true
"""

def generate_dynamic(stack_path, out_path, cfg):
    """Generate a dynamic config from a compose file."""
    try:
        content = open(stack_path).read()
        # Strip YAML anchors for parsing
        clean = re.sub(r'<<:\s*\*\w+\n?', '', content)
        clean = re.sub(r'&\w+\s*\n', '\n', clean)
        data = yaml.safe_load(clean)
    except Exception as e:
        print(f"  Parse error {os.path.basename(stack_path)}: {e}")
        return False

    services = data.get('services', {})
    if not services:
        return False

    domain = cfg['PRIMARY_DOMAIN']

    routers_out = ''
    services_out = ''
    middlewares_out = ''
    tcp_routers_out = ''
    tcp_services_out = ''

    for svc_name, svc_def in services.items():
        if not isinstance(svc_def, dict): continue
        container = svc_def.get('container_name', svc_name)

        if is_tcp_service(svc_name, svc_def) and cfg.get('GEN_TCP') == '1':
            port = get_tcp_port(svc_name, svc_def)
            subdomain = container.replace('_', '-').lower()
            if port:
                tcp_routers_out += gen_tcp_router(svc_name, subdomain, domain, port)
                tcp_services_out += gen_tcp_service(svc_name, container, port)
            continue

        if not service_has_traefik(svc_def): continue

        port = get_service_port(svc_def)
        subdomain = get_subdomain(svc_name, svc_def)
        sablier_mw = f'sablier-{svc_name}' if cfg.get('GEN_SABLIER') == '1' else ''

        if cfg.get('GEN_ROUTERS') == '1':
            routers_out += gen_router(svc_name, subdomain, domain,
                                      f'{svc_name}-svc', sablier_mw, cfg)
        if cfg.get('GEN_SERVICES') == '1':
            services_out += gen_service(svc_name, container, port)
        if cfg.get('GEN_SABLIER') == '1':
            middlewares_out += gen_sablier_mw(svc_name, container, cfg)

    if not routers_out and not services_out:
        return False

    out = "http:\n"
    out += "  serversTransports:\n"
    out += "    insecureTransport:\n"
    out += "      insecureSkipVerify: true\n\n"

    if routers_out:
        out += "  routers:\n\n" + routers_out + "\n"
    if services_out:
        out += "  services:\n\n" + services_out + "\n"
    if middlewares_out or cfg.get('GEN_MIDDLEWARES') == '1':
        out += "  middlewares:\n"
        if cfg.get('GEN_MIDDLEWARES') == '1':
            out += gen_standard_middlewares(cfg)
        if middlewares_out:
            out += middlewares_out

    if tcp_routers_out:
        out += "\ntcp:\n  routers:\n\n" + tcp_routers_out
        out += "\n  services:\n\n" + tcp_services_out

    open(out_path, 'w').write(out)
    return True


def main():
    conf_path = os.path.expanduser('~/.config/stacks/stacks.conf')
    cfg = load_conf(conf_path)
    stacks_dir = cfg.get('STACKS_DIR_OVERRIDE') or '/srv/stacks/Stacks'
    dyn_dir = cfg.get('DYNAMICS_DIR_OVERRIDE') or '/srv/stacks/Configs/Dynamics'

    target = sys.argv[1] if len(sys.argv) > 1 else 'all'

    if target == 'all':
        files = sorted(f for f in os.listdir(stacks_dir) if f.endswith('.yml'))
    else:
        files = [target if target.endswith('.yml') else target + '.yml']

    generated = 0
    for fname in files:
        stack_path = os.path.join(stacks_dir, fname)
        if not os.path.exists(stack_path): continue
        out_name = fname  # same name in dynamics dir
        out_path = os.path.join(dyn_dir, out_name)
        # Don't overwrite existing unless --force
        if os.path.exists(out_path) and '--force' not in sys.argv:
            print(f"  skip (exists): {fname}")
            continue
        if generate_dynamic(stack_path, out_path, cfg):
            print(f"  generated: {fname}")
            generated += 1
        else:
            print(f"  skip (no traefik services): {fname}")

    print(f"\nGenerated {generated} dynamic config(s)")

if __name__ == '__main__':
    main()
