#!/usr/bin/env python3
"""
stacks_gen_dynamic2.py — rich, config-driven Traefik dynamics generator.

Single source of truth for the dynamic files: scans the compose stacks and
emits the FULL rich set (serversTransports + all middlewares + HTTP routers +
per-service Sablier + TCP DB routers on DEDICATED entrypoints). Everything is
driven by ~/.config/stacks/dynamics.yaml — nothing is hardcoded, so it works
for anyone's stacks.

Usage:
  stacks_gen_dynamic2.py [all|<stack>] [--force] [--sandbox <dir>] [--emit-entrypoints]
"""
import os, sys, re, yaml, copy

# ── Paths: generic for any user. Resolution order for each ────────────────────
#   env var (exported by `stacks`) → master config (stacks.yaml) → sane default.
def _master_cfg():
    try:
        sys.path.insert(0, '/usr/local/lib'); import stacks_config as sc
        return sc.load(), sc.CONF_DIR
    except Exception:
        return {}, os.path.expanduser('~/.config/stacks')
_MC, _CONF_DIR = _master_cfg()
def _path(env, mckey, default):
    return os.environ.get(env) or _MC.get(mckey) or default

CONF       = os.path.join(_CONF_DIR, 'dynamics.yaml')
# Neutral fallbacks only — real paths come from env (set by `stacks`) or the
# master config (stacks.yaml: stacks_folder / dynamics_folder). No user identity.
_DEF_BASE  = os.path.expanduser('~/MyDocker')
STACKS_DIR = _path('STACKS_DIR',   'STACKS_DIR',   f'{_DEF_BASE}/Stacks')
DYN_DIR    = _path('DYNAMICS_DIR', 'DYNAMICS_DIR', f'{_DEF_BASE}/Configs/Dynamics')

def _find_traefik_stack(stacks_dir):
    """Auto-detect which compose file defines the traefik service (where the
    entrypoints live). Generic — not assumed to be net_2.yml. Falls back to the
    first file that even mentions an entrypoint, then net_2.yml."""
    cand_with_ep = None
    try:
        for fn in sorted(os.listdir(stacks_dir)):
            if not fn.endswith('.yml'): continue
            fp = os.path.join(stacks_dir, fn)
            try: data = yaml.safe_load(open(fp)) or {}
            except Exception:
                # not valid YAML to load fully — cheap text check for entrypoints
                if 'entrypoints.' in open(fp, errors='ignore').read() and not cand_with_ep:
                    cand_with_ep = fp
                continue
            for sn, sv in (data.get('services') or {}).items():
                if not isinstance(sv, dict): continue
                if 'traefik' in sn.lower() or 'traefik' in str(sv.get('image','')).lower():
                    if any('entrypoints.' in str(a) for a in (sv.get('command') or [])):
                        return fp                      # the real traefik stack
                    if cand_with_ep is None: cand_with_ep = fp
    except FileNotFoundError:
        pass
    return cand_with_ep or os.path.join(stacks_dir, 'net_2.yml')

TRAEFIK_STACK = os.environ.get('TRAEFIK_STACK') or _find_traefik_stack(STACKS_DIR)

# ── defaults (used if dynamics.yaml is missing keys) ──────────────────────────
DEF = {
    'domain': {'primary': 'example.com', 'secondary': '', 'use': 'primary'},
    'host_overrides': {},   # service|container -> subdomain (explicit; wins over harvest)
    'generate': {'routers': True, 'services': True, 'middlewares': True, 'transports': True, 'tcp': True},
    'chain': ['sablier','cloudflare-ipallow','https-header','crowdsec_bouncer','authentik-auth',
              'global-retry','compress','inflight','buffering','rate-limit'],
    'features': {'authentik': True,'crowdsec': True,'sablier': True,'https_header': True,
                 'https_redirect': True,'global_retry': True,'compress': True,'inflight': True,
                 'buffering': True,'rate_limit': True,'error_pages': True,'cloudflare_ipallow': False},
    'urls': {'authentik':'http://authentik_server:9000','crowdsec':'http://crowdsec_bouncer:8080',
             'sablier':'http://sablier:10000','error_pages':'http://error-pages:8080'},
    'headers': {'x_frame_options':'SAMEORIGIN','content_type_nosniff':True,'xss_protection':'1; mode=block',
                'referrer_policy':'strict-origin-when-cross-origin','hsts':'max-age=31536000; includeSubDomains; preload',
                'hide_server':True,'robots':'noindex, nofollow','permissions_policy_enabled':True,
                'permissions_policy':'camera=(), microphone=(), geolocation=(), payment=()',
                'csp_enabled':True,'csp':"default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: wss:; frame-ancestors 'self'"},
    'authentik_response_headers': ['X-authentik-username','X-authentik-groups','X-authentik-email',
        'X-authentik-name','X-authentik-uid','X-authentik-jwt','X-authentik-meta-jwks',
        'X-authentik-meta-outpost','X-authentik-meta-provider','X-authentik-meta-app','X-authentik-meta-version'],
    'tunables': {'global_retry':{'attempts':3,'initial_interval':'100ms'},
                 'compress':{'min_bytes':1024,'encodings':['zstd','br','gzip'],'excluded_content_types':['text/event-stream']},
                 'inflight':{'amount':100,'ip_depth':1},
                 'buffering':{'max_request':10485760,'mem_request':2097152,'max_response':10485760,'mem_response':2097152,'retry_expression':'IsNetworkError() && Attempts() < 3'},
                 'rate_limit':{'average':100,'burst':200,'period':'1s','ip_depth':1}},
    'transports': {'insecure_skip_verify': True,'h2c': True,'custom_timeout': True},
    'sablier': {'default_theme':'ghost','default_duration':'1h','default_timeout':'10m','overrides':{}},
    'tcp': {'enabled':True,'generate_entrypoints':True,'merge_into_traefik':True,
            'port_types':{5432:'postgres',3306:'mysql',6379:'redis',27017:'mongodb',7687:'neo4j',
                          5672:'amqp',5984:'couchdb',8086:'influxdb',9000:'clickhouse',9200:'opensearch'},
            # image substring -> [port, type]. Catches alias images (mariadb=mysql,
            # mongo=mongodb, rabbitmq=amqp, valkey=redis, ...). Longest match wins.
            'image_types':{'pgvector':[5432,'postgres'],'timescale':[5432,'postgres'],
                           'supabase/postgres':[5432,'postgres'],'postgres':[5432,'postgres'],
                           'mariadb':[3306,'mysql'],'percona':[3306,'mysql'],'mysql':[3306,'mysql'],
                           'mongo':[27017,'mongodb'],'rabbitmq':[5672,'amqp'],
                           'valkey':[6379,'redis'],'keydb':[6379,'redis'],'dragonfly':[6379,'redis'],'redis':[6379,'redis'],
                           'neo4j':[7687,'neo4j'],'couchdb':[5984,'couchdb'],'influxdb':[8086,'influxdb'],
                           'clickhouse':[9000,'clickhouse'],'opensearch':[9200,'opensearch'],'elasticsearch':[9200,'opensearch']},
            # images that CONTAIN a db word but are NOT databases (APIs, GUIs,
            # exporters, app servers). Vetoes detection. Substring match.
            'image_exclude':['postgrest','postgres-meta','-exporter','_exporter',
                             'zabbix-server','zabbix-web','zabbix-proxy','zabbix-agent',
                             'adminer','pgadmin','phpmyadmin','mongo-express','redis-commander',
                             'redisinsight','cloudbeaver','pgbackweb','supabase/studio'],
            'base_ports':{'postgres':5432,'mysql':3306,'redis':6379,'mongodb':27017,'neo4j':7687,
                          'amqp':5672,'couchdb':5984,'influxdb':8086,'clickhouse':9000,'opensearch':9200},
            'fallback_suffix':'general'},
    'exclude_suffixes': ['-ext'],
}
CF_IPS = ['173.245.48.0/20','103.21.244.0/22','103.22.200.0/22','103.31.4.0/22','141.101.64.0/18',
    '108.162.192.0/18','190.93.240.0/20','188.114.96.0/20','197.234.240.0/22','198.41.128.0/17',
    '162.158.0.0/15','104.16.0.0/13','104.24.0.0/14','172.64.0.0/13','131.0.72.0/22',
    '2400:cb00::/32','2606:4700::/32','2803:f800::/32','2405:b500::/32','2405:8100::/32','2a06:98c0::/29','2c0f:f248::/32']
LAN_IPS = ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.1/32']
TYPE_TOKENS = {'db','redis','mongo','mongodb','postgres','postgresql','mysql','mariadb','cache',
               'rabbitmq','opensearch','bolt','grpc','tcp'}

def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict): out[k] = _merge(out[k], v)
        else: out[k] = v
    return out

def load_cfg():
    cfg = copy.deepcopy(DEF)
    if os.path.exists(CONF):
        try: cfg = _merge(cfg, yaml.safe_load(open(CONF)) or {})
        except Exception as e: print(f"  WARN: bad dynamics.yaml ({e}); using defaults")
    return cfg

# ── compose scanning helpers ──────────────────────────────────────────────────
def _labels(svc):
    l = svc.get('labels', [])
    return l if isinstance(l, list) else [f"{k}={v}" for k, v in l.items()]
def has_traefik(svc):
    return any('traefik.enable=true' in str(l).lower() for l in _labels(svc))

# infra fingerprints: service-name / image substrings that prove a piece is installed
INFRA_SIGNS = {
    'authentik':   ['authentik', 'goauthentik'],
    'crowdsec':    ['crowdsec'],
    'sablier':     ['sablier'],
    'error_pages': ['error-pages', 'error_pages', 'tarampampam/error-pages'],
}
def detect_infra(stack_dir, files):
    """Scan the compose stacks and return the set of infra actually installed
    (authentik, crowdsec, sablier, error_pages). Drives 'auto' feature toggles."""
    present = set()
    for fn in files:
        sp = os.path.join(stack_dir, fn)
        if not os.path.exists(sp): continue
        try: data = yaml.safe_load(open(sp)) or {}
        except Exception: continue
        for sn, sv in (data.get('services') or {}).items():
            if not isinstance(sv, dict): continue
            blob = (sn + ' ' + str(sv.get('image', '')) + ' ' + str(sv.get('container_name',''))).lower()
            for infra, signs in INFRA_SIGNS.items():
                if any(s in blob for s in signs): present.add(infra)
    return present
def resolve_auto(cfg, present):
    """Turn any feature set to 'auto' into True/False based on what's installed."""
    f = cfg['features']
    for k, infra in (('authentik','authentik'),('crowdsec','crowdsec'),
                     ('sablier','sablier'),('error_pages','error_pages')):
        if isinstance(f.get(k), str) and f[k].lower() == 'auto':
            f[k] = infra in present
    return cfg
def sablier_on(svc):
    return not any('sablier.enable=false' in str(l).lower() for l in _labels(svc))
def get_port(svc):
    for l in _labels(svc):
        m = re.search(r'loadbalancer\.server\.port=(\d+)', str(l))
        if m: return int(m.group(1))
    img = svc.get('image', '').lower()
    for k, p in {'nginx':80,'apache':80,'caddy':80,'grafana':3000,'gitea':3000,
                 'vaultwarden':80,'portainer':9000}.items():
        if k in img: return p
    return 80
def get_host(svc, name, cfg=None, hmap=None):
    """Resolve the subdomain. Priority: compose Host label > explicit
    host_overrides in config > subdomain harvested from current dynamics
    (by service, then by container — survives renames) > service name."""
    for l in _labels(svc):
        m = re.search(r'rule=Host\(`([^.]+)\.', str(l))
        if m: return m.group(1)
    container = svc.get('container_name', name)
    ov = (cfg or {}).get('host_overrides') or {}
    if name in ov: return ov[name]
    if container in ov: return ov[container]
    if hmap:
        if name in hmap.get('by_service', {}):     return hmap['by_service'][name]
        if container in hmap.get('by_container', {}): return hmap['by_container'][container]
    return str(container).replace('_', '-').lower()

def harvest_hosts(dyn_dir):
    """Read the CURRENT dynamic files and map each service's real subdomain.
    Compose files lack Host labels here, so the live dynamics are the source
    of truth for subdomains. Returns {'by_service':{}, 'by_container':{}}."""
    by_svc, by_cont = {}, {}
    if not os.path.isdir(dyn_dir): return {'by_service': by_svc, 'by_container': by_cont}
    for fn in os.listdir(dyn_dir):
        fp = os.path.join(dyn_dir, fn)
        if not (fn.endswith('.yml') and os.path.isfile(fp)): continue
        txt = open(fp, errors='ignore').read()
        # service name -> subdomain  (X-router: ... Host(`SUB.`))
        for m in re.finditer(r'^    ([a-z0-9_-]+)-router:\s*\n\s*rule:\s*"Host\(`([^.`]+)\.', txt, re.M):
            by_svc.setdefault(m.group(1), m.group(2))
        # service name -> backend container  (X-svc: ... url: http://CONT:port)
        for m in re.finditer(r'^    ([a-z0-9_-]+)-svc:\s*\n.*?url:\s*"https?://([a-z0-9_.-]+):', txt, re.M | re.S):
            svc, cont = m.group(1), m.group(2)
            if svc in by_svc: by_cont.setdefault(cont, by_svc[svc])
    return {'by_service': by_svc, 'by_container': by_cont}
def _exposed_ports(svc):
    """Internal container ports from ports:/expose: (right-hand side of mappings)."""
    out = set()
    for p in (svc.get('ports') or []):
        s = str(p).split('/')[0]
        # forms: "1.2.3.4:5433:5432", "5433:5432", "5432"
        parts = s.split(':')
        try: out.add(int(parts[-1]))
        except ValueError: pass
    for e in (svc.get('expose') or []):
        try: out.add(int(str(e).split('/')[0]))
        except ValueError: pass
    return out
def db_port(name, svc, cfg):
    """Return the DB's internal port if this service is a database, else None.
    Detection order: image-alias map (mariadb=mysql, mongo=mongodb, ...),
    then port-type word in image/name, then a known db port in ports/expose."""
    pm   = cfg['tcp']['port_types']
    imgt = cfg['tcp'].get('image_types', {})
    img  = str(svc.get('image', '')).lower(); nm = name.lower()
    # 0) veto known non-DB images that merely contain a db word (postgREST,
    #    postgres-meta, *-exporter, zabbix app images, GUIs, ...)
    if any(x in img for x in cfg['tcp'].get('image_exclude', [])): return None
    # 1) image alias — longest substring match wins (so "supabase/postgres" beats "postgres")
    best = None
    for sub, pt in imgt.items():
        if sub in img and (best is None or len(sub) > len(best[0])):
            best = (sub, pt)
    if best: return int(best[1][0])
    # 2) port-type word literally in image or service name
    for p, t in pm.items():
        if t in img or t in nm: return p
    # 3) a known db port actually exposed (last resort, e.g. weird/renamed images)
    exposed = _exposed_ports(svc)
    for p in pm:
        if p in exposed: return p
    return None

# ── renderers ─────────────────────────────────────────────────────────────────
def render_transports(c):
    t = c['transports']; out = "  serversTransports:\n"
    if t.get('insecure_skip_verify', True):
        out += "    insecureTransport:\n      insecureSkipVerify: true\n"
    if t.get('h2c'):
        out += "    h2cTransport:\n      insecureSkipVerify: true\n"
    if t.get('custom_timeout'):
        out += ("    custom-timeout:\n      maxIdleConnsPerHost: 10\n"
                "      forwardingTimeouts:\n        readIdleTimeout: \"0s\"\n        pingTimeout: \"15s\"\n")
    return out

def render_shared_mw(c):
    f, h, t, u = c['features'], c['headers'], c['tunables'], c['urls']
    o = "  middlewares:\n"
    if f.get('https_header'):
        o += "\n    https-header:\n      headers:\n        customRequestHeaders:\n          X-Forwarded-Proto: \"https\"\n        customResponseHeaders:\n"
        o += f"          X-Frame-Options: \"{h['x_frame_options']}\"\n"
        if h.get('content_type_nosniff'): o += "          X-Content-Type-Options: \"nosniff\"\n"
        o += f"          X-XSS-Protection: \"{h['xss_protection']}\"\n"
        o += f"          Referrer-Policy: \"{h['referrer_policy']}\"\n"
        if h.get('permissions_policy_enabled'): o += f"          Permissions-Policy: \"{h['permissions_policy']}\"\n"
        if h.get('csp_enabled'): o += f"          Content-Security-Policy: \"{h['csp']}\"\n"
        o += f"          Strict-Transport-Security: \"{h['hsts']}\"\n"
        if h.get('hide_server'): o += "          Server: \"\"\n"
        o += f"          X-Robots-Tag: \"{h['robots']}\"\n"
    if f.get('https_redirect'):
        o += "\n    https-redirect:\n      redirectScheme:\n        scheme: https\n        permanent: true\n        port: \"443\"\n"
    if f.get('cloudflare_ipallow'):
        ranges = CF_IPS + LAN_IPS
        o += "\n    cloudflare-ipallow:\n      ipAllowList:\n        sourceRange:\n"
        o += ''.join(f"          - \"{r}\"\n" for r in ranges)
        o += "        ipStrategy:\n          depth: 1\n"
    if f.get('global_retry'):
        g = t['global_retry']
        o += f"\n    global-retry:\n      retry:\n        attempts: {g['attempts']}\n        initialInterval: {g['initial_interval']}\n"
    if f.get('compress'):
        cm = t['compress']
        o += "\n    compress:\n      compress:\n        minResponseBodyBytes: %d\n        encodings:\n" % cm['min_bytes']
        o += ''.join(f"          - {e}\n" for e in cm['encodings'])
        if cm.get('excluded_content_types'):
            o += "        excludedContentTypes:\n" + ''.join(f"          - {x}\n" for x in cm['excluded_content_types'])
    if f.get('inflight'):
        i = t['inflight']
        o += f"\n    inflight:\n      inFlightReq:\n        amount: {i['amount']}\n        sourceCriterion:\n          ipStrategy:\n            depth: {i['ip_depth']}\n"
    if f.get('buffering'):
        b = t['buffering']
        o += ("\n    buffering:\n      buffering:\n"
              f"        maxRequestBodyBytes: {b['max_request']}\n        memRequestBodyBytes: {b['mem_request']}\n"
              f"        maxResponseBodyBytes: {b['max_response']}\n        memResponseBodyBytes: {b['mem_response']}\n"
              f"        retryExpression: \"{b['retry_expression']}\"\n")
    if f.get('rate_limit'):
        r = t['rate_limit']
        o += (f"\n    rate-limit:\n      rateLimit:\n        average: {r['average']}\n        burst: {r['burst']}\n"
              f"        period: {r['period']}\n        sourceCriterion:\n          ipStrategy:\n            depth: {r['ip_depth']}\n")
    if f.get('authentik'):
        o += f"\n    authentik-auth:\n      forwardAuth:\n        address: \"{u['authentik']}/outpost.goauthentik.io/auth/traefik\"\n        trustForwardHeader: true\n        authResponseHeaders:\n"
        o += ''.join(f"          - {hh}\n" for hh in c['authentik_response_headers'])
    if f.get('crowdsec'):
        o += f"\n    crowdsec_bouncer:\n      forwardAuth:\n        address: \"{u['crowdsec']}/api/v1/forwardAuth\"\n        trustForwardHeader: true\n"
    if f.get('error_pages'):
        o += "\n    error-pages-middleware:\n      errors:\n        status: \"400-599\"\n        service: error-pages-svc\n        query: \"/{status}.html\"\n"
    return o

def render_sablier(svc_name, container, c):
    ov = (c['sablier'].get('overrides') or {}).get(svc_name, {})
    names   = ov.get('names', container)
    display = ov.get('display', container)
    theme   = ov.get('theme', c['sablier']['default_theme'])
    dur     = ov.get('duration', c['sablier']['default_duration'])
    tmo     = ov.get('timeout', c['sablier']['default_timeout'])
    return (f"\n    sablier-{svc_name}:\n      plugin:\n        sablier:\n"
            f"          sablierUrl: \"{c['urls']['sablier']}\"\n          sessionDuration: \"{dur}\"\n"
            f"          names: \"{names}\"\n          dynamic:\n            displayName: \"{display}\"\n"
            f"            provider: \"docker\"\n            stopTimeout: \"30s\"\n            refreshFrequency: \"5s\"\n"
            f"            theme: \"{theme}\"\n            timeout: \"{tmo}\"\n            warmupPeriod: \"10s\"\n"
            f"            healthCheckPath: \"/\"\n            healthCheckInterval: \"2s\"\n"
            f"            scaling:\n              replicas: 1\n              minReplicas: 0\n              maxReplicas: 1\n")

def build_chain(c, sablier_name):
    f = c['features']
    gate = {'sablier': bool(sablier_name), 'cloudflare-ipallow': f.get('cloudflare_ipallow'),
            'https-header': f.get('https_header'), 'crowdsec_bouncer': f.get('crowdsec'),
            'authentik-auth': f.get('authentik'), 'global-retry': f.get('global_retry'),
            'compress': f.get('compress'), 'inflight': f.get('inflight'),
            'buffering': f.get('buffering'), 'rate-limit': f.get('rate_limit')}
    out = []
    for m in c['chain']:
        if m == 'sablier':
            if sablier_name: out.append(sablier_name)
        elif gate.get(m, True):
            out.append(m)
    return out

def render_router(name, host, domain, chain):
    return (f"    {name}-router:\n      rule: \"Host(`{host}.{domain}`)\"\n      service: {name}-svc\n"
            f"      entryPoints: [web]\n      middlewares: [{', '.join(chain)}]\n")

def render_service(name, container, port):
    return f"    {name}-svc:\n      loadBalancer:\n        servers: [{{ url: \"http://{container}:{port}\" }}]\n"

# ── TCP entrypoint derivation (generic) ───────────────────────────────────────
def derive_entrypoint(rname, port, cfg, existing):
    typ = cfg['tcp']['port_types'].get(port)
    if not typ: return None
    raw = rname[:-4] if rname.endswith('-tcp') else rname
    toks = []
    for p in re.split(r'[-_]', raw):
        if not p or p in TYPE_TOKENS: continue
        # strip a type word glued onto the end of a single token (pritunlmongo -> pritunl)
        for tt in sorted(TYPE_TOKENS, key=len, reverse=True):
            if p != tt and p.endswith(tt) and len(p) > len(tt) + 1:
                p = p[:-len(tt)]; break
        toks.append(p)
    inst = '-'.join(toks)
    cands = []
    if inst: cands.append(f"{typ}-{inst}")
    if port == 3306 and inst: cands += [f"mysql-{inst}", f"mariadb-{inst}"]
    if port == 27017 and inst: cands.append(f"mongodb-{inst}")
    if port == 7687: cands.append("neo4j-bolt")
    if port == 5672 and inst: cands += [f"amqp-{inst}", "amqp"]
    if port == 5984 and inst: cands += [f"couchdb-{inst}", "couchdb"]
    cands += [f"{typ}-{cfg['tcp']['fallback_suffix']}", typ]
    for c in cands:
        if c in existing: return c
    # nothing exists yet → propose the primary candidate (will be created)
    return cands[0]

def main():
    args = sys.argv[1:]
    force = '--force' in args
    sandbox = None
    if '--sandbox' in args: sandbox = args[args.index('--sandbox')+1]
    pos = [a for a in args if not a.startswith('--') and a not in (sandbox or '',)]
    target = pos[0] if pos else 'all'
    cfg = load_cfg()
    out_dir = sandbox or DYN_DIR
    os.makedirs(out_dir, exist_ok=True)
    dom = cfg['domain']
    domain = dom.get('secondary') if dom.get('use') == 'secondary' else dom.get('primary')
    excl = tuple(s + '.yml' for s in cfg.get('exclude_suffixes', []))
    # harvest real subdomains from the CURRENT dynamics (compose lacks Host labels)
    hmap = harvest_hosts(DYN_DIR)

    if target == 'all':
        files = sorted(f for f in os.listdir(STACKS_DIR) if f.endswith('.yml') and not f.endswith(excl))
    else:
        files = [target if target.endswith('.yml') else target + '.yml']

    # detect installed infra across ALL stacks (so 'auto' toggles resolve the same
    # for every file, even when generating just one) and resolve any 'auto' features
    scan = sorted(f for f in os.listdir(STACKS_DIR) if f.endswith('.yml') and not f.endswith(excl))
    present = detect_infra(STACKS_DIR, scan)
    cfg = resolve_auto(cfg, present)
    autos = [k for k in ('authentik','crowdsec','sablier','error_pages')
             if str((load_cfg()['features']).get(k)).lower() == 'auto']
    if autos:
        print(f"Infra detected: {', '.join(sorted(present)) or 'none'}")
        for k in autos: print(f"  auto:{k} -> {'ON' if cfg['features'][k] else 'off'}")

    # existing traefik entrypoints (for TCP matching) + their ports
    existing_eps = set(); existing_ep_ports = {}
    try:
        tcmd = yaml.safe_load(open(TRAEFIK_STACK))['services']['traefik'].get('command', [])
        for a in tcmd:
            m = re.search(r'entrypoints\.([a-z0-9-]+)\.address=:(\d+)', str(a))
            if m: existing_eps.add(m.group(1)); existing_ep_ports[m.group(1)] = int(m.group(2))
            else:
                m = re.search(r'entrypoints\.([a-z0-9-]+)\.address', str(a))
                if m: existing_eps.add(m.group(1))
    except Exception: pass

    needed_eps = {}     # name -> port  (entrypoints the TCP routers want)
    gen = 0
    for fn in files:
        sp = os.path.join(STACKS_DIR, fn)
        if not os.path.exists(sp): continue
        op = os.path.join(out_dir, fn)
        if os.path.exists(op) and not force and not sandbox:
            print(f"  skip (exists): {fn}"); continue
        try: data = yaml.safe_load(open(sp))
        except Exception as e: print(f"  parse error {fn}: {e}"); continue
        svcs = (data or {}).get('services') or {}
        R=S=M=''; TR=TS=''
        for sn, sv in svcs.items():
            if not isinstance(sv, dict): continue
            container = sv.get('container_name', sn)
            dp = db_port(sn, sv, cfg)
            if dp and cfg['generate']['tcp'] and cfg['tcp']['enabled']:
                rn = f"{sn}-tcp"
                ep = derive_entrypoint(rn, dp, cfg, existing_eps)
                if ep:
                    needed_eps.setdefault(ep, dp)
                    TR += (f"    {rn}:\n      rule: \"HostSNI(`*`)\"\n      entryPoints: [{ep}]\n      service: {rn}-svc\n")
                    TS += (f"    {rn}-svc:\n      loadBalancer:\n        servers:\n          - address: \"{container}:{dp}\"\n")
                continue
            if not has_traefik(sv): continue
            host = get_host(sv, sn, cfg, hmap); port = get_port(sv)
            sab = f"sablier-{sn}" if (cfg['features']['sablier'] and sablier_on(sv)) else ''
            if cfg['generate']['routers']:
                R += render_router(sn, host, domain, build_chain(cfg, sab))
            if cfg['generate']['services']:
                S += render_service(sn, container, port)
            if sab:
                M += render_sablier(sn, container, cfg)
        if not R and not S and not TR:
            print(f"  skip (nothing): {fn}"); continue
        out = "http:\n" + (render_transports(cfg) if cfg['generate']['transports'] else "")
        if R: out += "\n  routers:\n\n" + R
        if S: out += "\n  services:\n\n" + S
        if cfg['generate']['middlewares']:
            out += "\n" + render_shared_mw(cfg)
        if M: out += M
        if TR:
            out += "\ntcp:\n  routers:\n" + TR + "\n  services:\n" + TS
        open(op, 'w').write(out)
        print(f"  generated: {fn}")
        gen += 1

    # ── entrypoints: reuse existing, assign unique free ports to genuinely-new ──
    new_eps = {k: v for k, v in needed_eps.items() if k not in existing_eps}
    print(f"\nGenerated {gen} dynamic config(s) into {out_dir}")
    if cfg['tcp'].get('generate_entrypoints'):
        print(f"DB entrypoints referenced: {len(needed_eps)} "
              f"({len(needed_eps)-len(new_eps)} matched existing, {len(new_eps)} new)")
        if new_eps:
            assigned, blacklist = assign_ports(new_eps, existing_ep_ports, cfg)
            print("New entrypoints to add to Traefik (append-only):")
            for k, p in sorted(assigned.items(), key=lambda x: x[1]):
                print(f"  + --entrypoints.{k}.address=:{p}")
            print(f"Ports to reserve in PORT_BLACKLIST so the packer skips them: "
                  f"{', '.join(str(p) for p in sorted(assigned.values()))}")
            if '--merge-entrypoints' in args and not sandbox:
                merge_into_net2(assigned)
            else:
                print("(dry-run — pass --merge-entrypoints to write net_2 + blacklist)")

def assign_ports(new_eps, existing_ep_ports, cfg):
    """Give each NEW entrypoint a unique free port: start at base_ports[type],
    skip ports already used by entrypoints, already blacklisted, or assigned
    this run. Returns (assigned{name:port}, blacklist_set)."""
    try:
        sys.path.insert(0, '/usr/local/lib'); import stacks_collision as col
        conf = col.load_conf()
        blacklist = set(int(x) for x in str(conf.get('PORT_BLACKLIST','')).split(',') if x.strip().isdigit())
    except Exception:
        blacklist = {22,80,443,3306,5432,6379,27017,2375,2376}
    base = cfg['tcp']['base_ports']
    taken = set(existing_ep_ports.values()) | blacklist
    assigned = {}
    for name in sorted(new_eps):
        typ = name.split('-')[0]
        p = base.get(typ, new_eps[name])
        while p in taken or p in assigned.values():
            p += 1
        assigned[name] = p
    return assigned, blacklist

def merge_into_net2(assigned):
    """APPEND-ONLY: add new --entrypoints lines into traefik's command in net_2,
    skipping any that already exist, and reserve each port in PORT_BLACKLIST.
    Never renumbers or removes an existing entrypoint."""
    import shutil, time
    bak = f"{TRAEFIK_STACK}.bak-{int(time.time())}"
    shutil.copy2(TRAEFIK_STACK, bak)
    lines = open(TRAEFIK_STACK).read().splitlines(keepends=True)
    have = set(re.search(r'entrypoints\.([a-z0-9-]+)\.address', l).group(1)
               for l in lines if re.search(r'entrypoints\.([a-z0-9-]+)\.address', l))
    # find the traefik command: list and the last existing entrypoint line (to match indent + insert after)
    last_idx = indent = None
    for i, l in enumerate(lines):
        m = re.search(r'^(\s*)-\s*"--entrypoints\.[a-z0-9-]+\.address', l)
        if m: last_idx = i; indent = m.group(1)
    if last_idx is None:
        print("  ! could not locate entrypoint block in net_2 — no changes made"); return
    add = [f'{indent}- "--entrypoints.{k}.address=:{p}"\n'
           for k, p in sorted(assigned.items(), key=lambda x: x[1]) if k not in have]
    if not add:
        print("  all entrypoints already present — nothing to merge"); return
    lines[last_idx+1:last_idx+1] = add
    open(TRAEFIK_STACK, 'w').writelines(lines)
    ok, where = reserve_ports(sorted(assigned.values()))
    note = f"reserved their ports in {where}" if ok else f"WARN: could not reserve ports ({where})"
    print(f"  merged {len(add)} entrypoint(s) into net_2 (backup: {bak}); {note}")

def reserve_ports(ports):
    """Reserve ports so the IP/port packer never reuses them. Writes to the
    EFFECTIVE config source: stacks.yaml `port_blacklist` if present (it wins
    over stacks.conf), otherwise stacks.conf PORT_BLACKLIST."""
    ports = [str(p) for p in ports]
    try:
        sys.path.insert(0, '/usr/local/lib'); import stacks_config as sc
        if os.path.isfile(sc.YAML_PATH):
            cur = sc.yaml_get_list('port_blacklist')
            add = [p for p in ports if p not in cur]
            if add: sc.yaml_set_list('port_blacklist', cur + add)
            return True, 'stacks.yaml'
    except Exception:
        pass
    try:
        sys.path.insert(0, '/usr/local/lib'); import stacks_collision as col
        for p in ports: col.add_port_blacklist(p)
        return True, 'stacks.conf'
    except Exception as e:
        return False, str(e)

if __name__ == '__main__':
    main()
