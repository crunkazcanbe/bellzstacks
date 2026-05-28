#!/usr/bin/env python3
"""
stacks_fix.py — Automated compose file fixer for StacksServer
Fixes:
  1. Missing Docker networks (creates them)
  2. Missing Docker volumes (creates them)  
  3. Auto-injects smart healthchecks based on image type
Usage:
  stacks_fix.py all
  stacks_fix.py <stackname>
  stacks_fix.py <stackname> <servicename>
"""
import sys, os, re, subprocess

STACKS_DIR = "/srv/stacks/Stacks"

G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; C="\033[1;36m"; M="\033[1;35m"; X="\033[0m"

def pr(msg): print(msg, flush=True)

# ── Healthcheck templates ──────────────────────────────────────────────────────
HEALTHCHECKS = [
    (r'postgres|pgvecto|timescale',
     ['CMD-SHELL', 'pg_isready -U postgres || exit 1'],
     '10s','5s',10,'30s'),
    (r'mariadb|mysql',
     ['CMD-SHELL', 'healthcheck.sh --connect --innodb_initialized || exit 1'],
     '10s','5s',10,'30s'),
    (r'redis(?!.*insight)',
     ['CMD', 'redis-cli', 'ping'],
     '10s','3s',10,'10s'),
    (r'mongo(?!.*express|.*compass)',
     ['CMD-SHELL', "mongosh --quiet --eval \"db.adminCommand('ping').ok\" || exit 1"],
     '10s','5s',10,'30s'),
    (r'elasticsearch|opensearch',
     ['CMD-SHELL', 'curl -sf http://localhost:9200/_cluster/health || exit 1'],
     '30s','10s',5,'60s'),
    (r'qdrant',
     ['CMD-SHELL', 'curl -sf http://localhost:6333/healthz || exit 1'],
     '10s','5s',10,'30s'),
    (r'neo4j',
     ['CMD-SHELL', 'curl -sf http://localhost:7474 || exit 1'],
     '15s','5s',10,'60s'),
    (r'influxdb',
     ['CMD-SHELL', 'curl -sf http://localhost:8086/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'couchdb',
     ['CMD-SHELL', 'curl -sf http://localhost:5984/_up || exit 1'],
     '10s','5s',10,'30s'),
    (r'rabbitmq',
     ['CMD', 'rabbitmq-diagnostics', 'ping'],
     '15s','5s',10,'30s'),
    (r'minio',
     ['CMD-SHELL', 'curl -sf http://localhost:9000/minio/health/live || exit 1'],
     '10s','5s',10,'30s'),
    (r'surrealdb|surreal',
     ['CMD-SHELL', 'curl -sf http://localhost:8000/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'traefik',
     ['CMD', 'traefik', 'healthcheck'],
     '10s','5s',5,'10s'),
    (r'nginx-proxy-manager|jc21/nginx',
     ['CMD-SHELL', 'curl -sf http://localhost:81/api || exit 1'],
     '15s','5s',10,'30s'),
    (r'nginx(?!.*proxy.*manager)|openresty',
     ['CMD-SHELL', 'curl -sf http://localhost/ || exit 1'],
     '10s','5s',5,'10s'),
    (r'caddy',
     ['CMD-SHELL', 'caddy validate --config /etc/caddy/Caddyfile || exit 1'],
     '10s','5s',5,'10s'),
    (r'authelia',
     ['CMD-SHELL', 'wget -qO- http://localhost:9091/api/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'goauthentik.*server|authentik.*server',
     ['CMD-SHELL', 'ak healthcheck || exit 1'],
     '10s','5s',10,'60s'),
    (r'vaultwarden|bitwarden',
     ['CMD-SHELL', 'curl -sf http://localhost:80/alive || exit 1'],
     '10s','5s',10,'30s'),
    (r'crowdsec(?!.*bouncer)',
     ['CMD-SHELL', 'cscli version || exit 1'],
     '15s','5s',5,'30s'),
    (r'grafana',
     ['CMD-SHELL', 'curl -sf http://localhost:3000/api/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'prometheus',
     ['CMD-SHELL', 'wget -qO- http://localhost:9090/-/healthy || exit 1'],
     '10s','5s',5,'30s'),
    (r'netdata',
     ['CMD-SHELL', 'curl -sf http://localhost:19999/api/v1/info || exit 1'],
     '15s','5s',5,'30s'),
    (r'uptime.kuma',
     ['CMD-SHELL', 'curl -sf http://localhost:3001 || exit 1'],
     '10s','5s',10,'30s'),
    (r'wazuh.*dashboard',
     ['CMD-SHELL', 'curl -skf https://localhost:5601/api/status || exit 1'],
     '30s','10s',10,'120s'),
    (r'wazuh.*manager',
     ['CMD-SHELL', '/var/ossec/bin/wazuh-control status | grep -q running || exit 1'],
     '15s','5s',10,'60s'),
    (r'jellyfin',
     ['CMD-SHELL', 'curl -sf http://localhost:8096/health || exit 1'],
     '15s','5s',10,'60s'),
    (r'immich.*server|immich.*microservices',
     ['CMD-SHELL', 'curl -sf http://localhost:3001/api/server-info/ping || exit 1'],
     '10s','5s',10,'60s'),
    (r'nextcloud',
     ['CMD-SHELL', 'curl -sf http://localhost/status.php | grep -q ok || exit 1'],
     '30s','10s',10,'120s'),
    (r'gitea',
     ['CMD-SHELL', 'curl -sf http://localhost:3000/api/v1/version || exit 1'],
     '10s','5s',10,'30s'),
    (r'portainer',
     ['CMD-SHELL', 'curl -sf https://localhost:9443/api/system/status || curl -sf http://localhost:9000/api/system/status || exit 1'],
     '10s','5s',10,'30s'),
    (r'ollama',
     ['CMD-SHELL', 'curl -sf http://localhost:11434/api/version || exit 1'],
     '10s','5s',10,'30s'),
    (r'open.webui|openwebui',
     ['CMD-SHELL', 'curl -sf http://localhost:8080/health || exit 1'],
     '10s','5s',10,'60s'),
    (r'searxng',
     ['CMD-SHELL', 'curl -sf http://localhost:8080/ || exit 1'],
     '10s','5s',10,'30s'),
    (r'litellm',
     ['CMD-SHELL', 'curl -sf http://localhost:4000/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'n8n',
     ['CMD-SHELL', 'curl -sf http://localhost:5678/healthz || exit 1'],
     '10s','5s',10,'60s'),
    (r'netbird.*server',
     ['CMD-SHELL', 'curl -sf http://localhost:80/api/v1/setup-keys || exit 1'],
     '15s','5s',10,'30s'),
    (r'adguard',
     ['CMD-SHELL', 'curl -sf http://localhost:3000 || exit 1'],
     '10s','5s',10,'30s'),
    (r'pihole',
     ['CMD-SHELL', 'curl -sf http://localhost/admin/api.php || exit 1'],
     '10s','5s',10,'30s'),
    (r'technitium',
     ['CMD-SHELL', 'curl -sf http://localhost:5380 || exit 1'],
     '10s','5s',10,'30s'),
    (r'letta',
     ['CMD-SHELL', 'wget -qO- http://localhost:8283/v1/health || exit 1'],
     '10s','5s',10,'60s'),
    (r'speaches',
     ['CMD-SHELL', 'wget -qO- http://localhost:8000/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'whisper|faster.whisper',
     ['CMD-SHELL', 'wget -qO- http://localhost:8000/health || exit 1'],
     '10s','5s',10,'30s'),
    (r'playwright',
     ['CMD-SHELL', 'wget -qO- http://localhost:3000 || exit 1'],
     '10s','5s',10,'30s'),
]

def get_healthcheck(image, ports):
    img = image.lower().split(':')[0]
    for pattern, cmd, interval, timeout, retries, start in HEALTHCHECKS:
        if re.search(pattern, img, re.I):
            return cmd, interval, timeout, retries, start
    # Port-based fallback
    port_map = {
        '80':'http://localhost:80/',
        '3000':'http://localhost:3000/',
        '8080':'http://localhost:8080/',
        '8000':'http://localhost:8000/',
        '9000':'http://localhost:9000/',
        '5000':'http://localhost:5000/',
        '4000':'http://localhost:4000/',
        '7860':'http://localhost:7860/',
        '3001':'http://localhost:3001/',
    }
    for p in ports:
        m = re.search(r':(\d+):\d+', p)
        if m and m.group(1) in port_map:
            url = port_map[m.group(1)]
            return (['CMD-SHELL', f'wget -qO- {url} || exit 1'],
                    '30s','10s',5,'60s')
    return (['CMD-SHELL', 'wget -qO- http://localhost:8080/ || exit 1'],
            '30s','10s',5,'60s')

def format_healthcheck(cmd, interval, timeout, retries, start):
    """Format healthcheck as proper YAML lines with 4-space indent"""
    lines = ['    healthcheck:']
    lines.append('      test:')
    for item in cmd:
        lines.append(f'        - "{item}"')
    lines.append(f'      interval: {interval}')
    lines.append(f'      timeout: {timeout}')
    lines.append(f'      retries: {retries}')
    lines.append(f'      start_period: {start}')
    return '\n'.join(lines) + '\n'

# ── Parse services properly ────────────────────────────────────────────────────
def parse_services_with_positions(path):
    """
    Returns list of dicts with:
      name, image, ports, has_healthcheck, 
      block_start (line index of '  name:'), 
      block_end (line index of last line before next service or EOF)
    """
    lines = open(path).readlines()
    services = []
    in_services = False
    current = None
    
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        
        # Detect services: section
        if re.match(r'^services:\s*$', stripped):
            in_services = True
            continue
        
        # Detect end of services section
        if in_services and re.match(r'^[a-zA-Z]', stripped) and not stripped.startswith(' '):
            if current:
                current['block_end'] = i - 1
                services.append(current)
                current = None
            in_services = False
            continue
        
        if not in_services:
            continue
        
        # Detect service definition — MUST be exactly 2-space indent
        # and NOT start with x- (anchors) and NOT be a comment
        m = re.match(r'^  ([a-zA-Z0-9][a-zA-Z0-9_.\-]*):\s*$', stripped)
        if m and not m.group(1).startswith('x-'):
            if current:
                current['block_end'] = i - 1
                services.append(current)
            current = {
                'name': m.group(1),
                'image': '',
                'ports': [],
                'has_healthcheck': False,
                'block_start': i,
                'block_end': len(lines) - 1,
            }
            continue
        
        if current:
            # image:
            im = re.match(r'^\s+image:\s+(.+)', stripped)
            if im: current['image'] = im.group(1).strip()
            # ports
            pm = re.match(r'^\s+-\s+"?(\S+:\d+:\d+)', stripped)
            if pm: current['ports'].append(pm.group(1))
            # healthcheck
            if re.match(r'^\s+healthcheck:\s*$', stripped):
                current['has_healthcheck'] = True
    
    if current:
        services.append(current)
    
    return services, lines

# ── Inject healthcheck into a service block ────────────────────────────────────
def inject_hc_into_service(lines, svc):
    """
    Find the right place inside svc's block to inject healthcheck.
    Insert it before blkio_config / ulimits / deploy / logging / labels
    or at end of block if none found.
    Skips if healthcheck already exists.
    """
    if svc['has_healthcheck']:
        return lines
    
    hc_cmd, interval, timeout, retries, start = get_healthcheck(
        svc['image'], svc['ports'])
    hc_text = format_healthcheck(hc_cmd, interval, timeout, retries, start)
    
    # Find insertion point within this service's block
    # Insert before blkio_config, ulimits, deploy, logging, or storage_opt
    # or just before the block_end
    insert_after = None
    
    for i in range(svc['block_start'], svc['block_end'] + 1):
        l = lines[i].rstrip()
        # These are typically the last fields — insert healthcheck before them
        if re.match(r'^\s+(blkio_config|ulimits|deploy|storage_opt):', l):
            insert_after = i
            break
    
    if insert_after is None:
        # Insert at end of block
        insert_after = svc['block_end'] + 1
    
    new_lines = lines[:insert_after] + [hc_text] + lines[insert_after:]
    return new_lines

# ── Network/volume helpers ─────────────────────────────────────────────────────
def get_declared_networks(path):
    content = open(path).read()
    in_nets = False; nets = []
    for line in content.splitlines():
        if re.match(r'^networks:', line): in_nets = True; continue
        if re.match(r'^[a-zA-Z]', line) and not line.startswith(' '): in_nets = False
        if not in_nets: continue
        m = re.match(r'^  ([a-zA-Z0-9_.\-]+):', line)
        if m: nets.append(m.group(1))
    return nets

def get_declared_volumes(path):
    content = open(path).read()
    in_vols = False; vols = []
    for line in content.splitlines():
        if re.match(r'^volumes:', line): in_vols = True; continue
        if re.match(r'^[a-zA-Z]', line) and not line.startswith(' '): in_vols = False
        if not in_vols: continue
        m = re.match(r'^  ([a-zA-Z0-9_.\-]+):', line)
        if m: vols.append(m.group(1))
    return vols

def net_exists(name):
    return subprocess.run(['docker','network','inspect',name],
                         capture_output=True).returncode == 0

def vol_exists(name):
    return subprocess.run(['docker','volume','inspect',name],
                         capture_output=True).returncode == 0

# ── Fix a single stack ─────────────────────────────────────────────────────────
def fix_stack(path, target_svc=None):
    stack_name = os.path.basename(path).replace('.yml','')
    pr(f"\n{C}🔧 Fixing: {stack_name}{X}")
    changes = 0
    
    # ── 1. Networks — warn only, never create (core stacks define them)
    for net in get_declared_networks(path):
        if not net_exists(net):
            pr(f"  {R}⚠ Missing network: {net} — add to a core stack to create it{X}")
    
    # ── 2. Volumes ─────────────────────────────────────────────────────────
    for vol in get_declared_volumes(path):
        if not vol_exists(vol):
            pr(f"  {Y}⚡ Creating volume: {vol}{X}")
            r = subprocess.run(['docker','volume','create',vol],
                             capture_output=True, text=True)
            if r.returncode == 0:
                pr(f"  {G}✔ Volume created: {vol}{X}"); changes += 1
            else:
                pr(f"  {R}✘ Failed: {r.stderr.strip()[:60]}{X}")
    
    # ── 3. Healthchecks ────────────────────────────────────────────────────
    services, lines = parse_services_with_positions(path)
    
    if target_svc:
        services = [s for s in services if s['name'] == target_svc]
    
    # Process in REVERSE order so line numbers stay valid
    for svc in reversed(services):
        if not svc['image']:
            pr(f"  {C}  {svc['name']}: no image, skipping{X}")
            continue
        if svc['has_healthcheck']:
            pr(f"  {C}  {svc['name']}: already has healthcheck{X}")
            continue
        
        img_short = svc['image'].split('/')[-1].split(':')[0]
        pr(f"  {Y}💉 {svc['name']} ({img_short}){X}")
        lines = inject_hc_into_service(lines, svc)
        changes += 1
        pr(f"  {G}✔ Healthcheck added{X}")
    
    # Write back
    if changes > 0:
        open(path, 'w').writelines(lines)
        pr(f"  {G}✔ {stack_name}: {changes} fix(es) applied{X}")
    else:
        pr(f"  {G}✔ {stack_name}: nothing to fix{X}")
    
    return changes

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    target = args[0] if args else 'all'
    svc    = args[1] if len(args) > 1 else None
    
    pr(f"\n{M}╔══════════════════════════════════════╗{X}")
    pr(f"{M}║   🔧 STACKS STACK FIXER               ║{X}")
    pr(f"{M}╚══════════════════════════════════════╝{X}")
    
    if target in ('all','--all'):
        files = sorted([os.path.join(STACKS_DIR,f)
                       for f in os.listdir(STACKS_DIR) if f.endswith('.yml')])
    else:
        fname = target if target.endswith('.yml') else target+'.yml'
        fpath = os.path.join(STACKS_DIR, fname)
        if not os.path.isfile(fpath):
            pr(f"{R}✘ Stack not found: {target}{X}"); sys.exit(1)
        files = [fpath]
    
    total = 0
    for f in files:
        if os.path.isfile(f):
            total += fix_stack(f, svc)
    
    pr(f"\n{G}✨ Done — {total} total fix(es) applied{X}\n")

if __name__ == '__main__':
    main()
