#!/usr/bin/env python3
"""
stacks_describe — inject service descriptions from conf files
Conf dir: ~/.config/stacks/descriptions/
Usage: stacks_describe.py all | stackname
"""
import sys, os, re

STACKS_DIR  = "/srv/stacks/Stacks"
CONF_DIR    = "/home/user/.config/stacks/descriptions"

LOOKUP = {
    "ollama":"Local LLM inference server with AMD ROCm GPU acceleration",
    "comfyui":"Node-based Stable Diffusion image generation GUI",
    "openwebui":"Elegant chat frontend for local LLMs and RAG",
    "playwright":"Headless browser for AI web scraping and automation",
    "searxng":"Privacy-respecting metasearch engine for AI web search",
    "n8n":"Visual drag-and-drop workflow automation platform",
    "letta":"Autonomous agents with persistent long-term memory",
    "litellm":"Multi-provider AI gateway standardizing LLM APIs",
    "langflow":"Visual LLM pipeline and agent framework builder",
    "langfuse":"LLM observability and prompt management platform",
    "traefik":"Cloud-native reverse proxy and load balancer",
    "sablier":"Container wake-on-demand autoscaling service",
    "authelia":"Single sign-on authentication and authorization server",
    "crowdsec":"Collaborative intrusion detection and prevention system",
    "portainer":"Web UI for managing Docker containers and stacks",
    "rancher":"Enterprise Kubernetes and container management platform",
    "gitea":"Lightweight self-hosted Git repository service",
    "nextcloud":"Self-hosted cloud storage and collaboration suite",
    "immich":"High-performance self-hosted photo and video backup",
    "grafana":"Analytics and monitoring dashboard platform",
    "prometheus":"Time-series metrics collection and alerting system",
    "loki":"Log aggregation system designed for Grafana",
    "pihole":"Network-wide DNS ad blocking server",
    "adguard":"DNS-based ad and tracker blocking server",
    "technitium":"Advanced self-hosted DNS server with web UI",
    "wazuh":"Open source SIEM security monitoring platform",
    "vaultwarden":"Lightweight self-hosted Bitwarden password manager",
    "jellyfin":"Free self-hosted media streaming server",
    "postgres":"Robust open source relational database server",
    "mariadb":"High-performance MySQL-compatible database server",
    "redis":"In-memory data structure store and cache",
    "mongodb":"NoSQL document-oriented database server",
    "neo4j":"Native graph database for connected data",
    "qdrant":"High-performance vector similarity search engine",
    "surrealdb":"Multi-model cloud-native database engine",
    "minio":"S3-compatible high-performance object storage server",
    "netbird":"WireGuard-based zero-config mesh VPN platform",
    "tailscale":"Zero-config WireGuard mesh VPN client",
    "cloudflared":"Cloudflare Tunnel daemon for secure external access",
    "pangolin":"Secure tunnel relay for private network access",
    "wazuhindexer":"Wazuh SIEM data indexing and storage engine",
    "wazuhmanager":"Wazuh security event collection and analysis hub",
    "wazuhdashboard":"Wazuh SIEM web dashboard and visualization UI",
    "generator":"Wazuh configuration and certificate generator",
    "pangolinclient":"Secure Pangolin tunnel client for remote access",
    "gerbil":"Pangolin tunnel relay service component",
    "errorpages":"Custom styled HTTP error pages for Traefik",
    "authentik":"Open source identity provider and SSO platform",
    "jellyseerr":"Media request management for Jellyfin",
    "zoraxy":"Simple self-hosted reverse proxy manager",
    "openresty":"Nginx-based web platform with Lua scripting",
    "defectdojo":"DevSecOps vulnerability management platform",
    "voidauth":"Lightweight authentication proxy service",
    "dockhand":"Docker webhook and automation handler",
    "speaches":"OpenAI-compatible speech-to-text API server",
    "whisper":"Fast Whisper speech recognition backend",
    "terminalagent":"Open Interpreter AI code execution agent",
    "opennotebook":"AI-powered Jupyter-style notebook interface",
    "browserless":"Headless Chrome browser as a service",
    "gooseagent":"AI coding agent with tool use capabilities",
    "tabby":"Self-hosted AI coding assistant server",
    "hermes":"Custom AI agent hub and workspace platform",
    "zep":"Long-term memory store for AI assistants",
    "memos":"Lightweight self-hosted memo and note service",
    "supabase":"Open source Firebase alternative platform",
    "librechat":"Enhanced multi-provider AI chat interface",
    "exo":"Distributed AI inference cluster framework",
    "dockmate":"Docker container management and monitoring UI",
    "glance":"Self-hosted dashboard for server overview",
    "coolify":"Self-hosted Heroku and Netlify alternative PaaS",
    "dokploy":"Free self-hosted app deployment platform",
    "pterodactyl":"Open source game server management panel",
    "penpot":"Open source design and prototyping platform",
    "appsmith":"Low-code platform for building internal tools",
    "tooljet":"Open source low-code application builder",
    "syncthing":"Continuous peer-to-peer file synchronization",
    "invidious":"Privacy-respecting YouTube frontend",
    "mealie":"Self-hosted recipe manager and meal planner",
    "tandoor":"Recipe management platform with meal planning",
    "homeassistant":"Open source home automation platform",
    "nodered":"Flow-based visual IoT programming tool",
    "mosquitto":"Lightweight MQTT message broker",
    "dify":"Open source LLM app development platform",
    "windmill":"Open source developer platform for scripts",
    "netdata":"Real-time infrastructure monitoring and alerting",
    "komodo":"Container and server management platform",
    "beszel":"Lightweight server resource monitoring hub",
    "dozzle":"Real-time Docker container log viewer",
    "ntopng":"High-speed network traffic analysis tool",
    "headscale":"Self-hosted Tailscale control server",
    "headplane":"Web UI management panel for Headscale",
    "clamav":"Open source antivirus engine and scanner",
    "odoo":"Open source ERP and business application suite",
    "dolibarr":"Open source ERP and CRM platform",
    "gamevault":"Self-hosted game library and launcher",
    "romm":"Self-hosted retro game ROM manager",
    "webtop":"Full Linux desktop environment in the browser",
    "scrutiny":"Hard drive SMART monitoring dashboard",
    "duplicati":"Encrypted cloud backup solution",
    "borgmatic":"Automated BorgBackup wrapper utility",
    "provisioner":"NetBird management server provisioner",
    "trivy":"Container and filesystem vulnerability scanner",
    "redroid":"Android container for x86 hosts via KVM",
    "dokku":"Docker-powered mini-Heroku PaaS platform",
}

def get_fallback(name, image=""):
    n = name.lower().replace("-","").replace("_","").replace(".","")
    img = image.lower().split("/")[-1].split(":")[0].replace("-","").replace("_","")
    for key, val in LOOKUP.items():
        k = key.replace("-","").replace("_","")
        if k == n or k == img: return val
    for key, val in LOOKUP.items():
        k = key.replace("-","").replace("_","")
        if k in n or k in img or n in k or img in k: return val
    return f"Self-hosted {name} service container"

def load_conf(stack_name):
    """Load description conf file, returns dict of {service: [lines]}"""
    conf_path = os.path.join(CONF_DIR, f"{stack_name}.conf")
    if not os.path.exists(conf_path):
        return {}
    descs = {}
    current_svc = None
    current_lines = []
    for line in open(conf_path):
        s = line.rstrip()
        # Skip blank lines between services
        if not s:
            if current_svc and current_lines:
                descs[current_svc] = current_lines
                current_svc = None
                current_lines = []
            continue
        # Comment lines — collect as description content
        if s.startswith('#'):
            if current_svc is not None:
                current_lines.append(s)
            continue
        # Non-comment, non-blank — this is a service name
        if current_svc and current_lines:
            descs[current_svc] = current_lines
        current_svc = s.strip()
        current_lines = []
    if current_svc and current_lines:
        descs[current_svc] = current_lines
    return descs

def parse_services(path):
    services = []
    in_services = False
    current = None
    current_data = {}
    for line in open(path):
        s = line.rstrip()
        if re.match(r'^services:', s):
            in_services = True; continue
        if re.match(r'^[a-zA-Z]', s) and not s.startswith(' ') and in_services:
            if current and current_data: services.append(current_data)
            in_services = False; continue
        if not in_services: continue
        m = re.match(r'^  ([a-zA-Z0-9_.\-]+):\s*$', s)
        if m:
            if current and current_data: services.append(current_data)
            current = m.group(1)
            current_data = {'name': current, 'image': '', 'container_name': current}
            continue
        if current:
            im = re.match(r'\s+image:\s+(.+)', s)
            if im: current_data['image'] = im.group(1).strip()
    if current and current_data: services.append(current_data)
    return services

def remove_existing_desc(lines_before_svc):
    """Remove any existing description block from end of lines list"""
    while lines_before_svc and lines_before_svc[-1].strip().startswith('#'):
        lines_before_svc.pop()
    return lines_before_svc

def inject_descriptions(path):
    stack_name = os.path.basename(path).replace('.yml','')
    services = parse_services(path)
    if not services:
        print(f"  No services in {stack_name}")
        return

    conf_descs = load_conf(stack_name)
    
    lines = open(path).readlines()
    out = []
    svc_num = 0
    i = 0
    
    while i < len(lines):
        line = lines[i]
        s = line.rstrip()
        m = re.match(r'^  ([a-zA-Z0-9_.\-]+):\s*$', s)
        if m:
            svc_name = m.group(1)
            # Check it's a real service
            is_service = False
            for j in range(i+1, min(i+6, len(lines))):
                if re.match(r'\s+(<<:|image:|container_name:)', lines[j]):
                    is_service = True; break
            
            if is_service:
                # Remove any existing desc block from end of out
                while out and out[-1].strip().startswith('#  #') or \
                      (out and re.match(r'\s+#\s*-{3,}', out[-1])):
                    out.pop()
                # Also remove the last block of # lines
                while out and out[-1].strip().startswith('#'):
                    last = out[-1].strip()
                    if any(x in last for x in ['---', 'Description:', '🐳', '✅']):
                        out.pop()
                    else:
                        break

                svc_num += 1
                # Get description
                if svc_name in conf_descs:
                    desc_lines = conf_descs[svc_name]
                else:
                    # Find by service in any format
                    found = None
                    for k in conf_descs:
                        if k.lower().replace('-','').replace('_','') == \
                           svc_name.lower().replace('-','').replace('_',''):
                            found = k; break
                    if found:
                        desc_lines = conf_descs[found]
                    else:
                        # Fallback to lookup
                        img = next((s['image'] for s in services if s['name']==svc_name), '')
                        desc_lines = [f"# {get_fallback(svc_name, img)}"]

                # Build description block
                display = svc_name.upper().replace('-',' ').replace('_',' ')
                block = f"  # ---------------------------------------------------------\n"
                block += f"  # {svc_num:02d}. {display} 🐳\n"
                for dl in desc_lines:
                    dl = dl.strip()
                    if not dl.startswith('#'):
                        dl = '# ' + dl
                    block += f"  {dl}\n"
                block += f"  # ---------------------------------------------------------\n"
                out.append(block)
        
        out.append(line)
        i += 1
    
    open(path, 'w').writelines(out)
    print(f"  ✔ {stack_name} — {svc_num} services described")

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target in ('all', '--all'):
        files = sorted([os.path.join(STACKS_DIR, f)
                       for f in os.listdir(STACKS_DIR) if f.endswith('.yml')])
    elif os.path.isfile(target):
        files = [target]
    elif os.path.isfile(os.path.join(STACKS_DIR, target + '.yml')):
        files = [os.path.join(STACKS_DIR, target + '.yml')]
    else:
        files = [os.path.join(STACKS_DIR, target)]

    print(f"\n\033[1;35m📝 Injecting service descriptions...\033[0m")
    for f in files:
        if os.path.isfile(f):
            inject_descriptions(f)
    print(f"\n\033[1;32m✔ Done\033[0m")
