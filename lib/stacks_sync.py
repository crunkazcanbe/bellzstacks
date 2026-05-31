#!/usr/bin/env python3
"""
stacks_sync.py — Sync descriptions and all_services.txt from compose files
Run automatically after stacks up/down/build or manually
"""
import os, re, glob

STACKS_DIR = "/srv/stacks/Stacks"
CONF_DIR   = os.path.expanduser("~/.config/stacks")
DESC_DIR   = os.path.join(CONF_DIR, "descriptions")
SVC_FILE   = os.path.join(CONF_DIR, "all_services.txt")

def get_default_desc():
    try:
        for line in open(os.path.join(CONF_DIR, "stacks.conf")):
            l = line.strip()
            if l.startswith("BUILD_DEFAULT_DESC="):
                return l.split("=",1)[1].strip('" ')
    except: pass
    return "A powerful service running on StacksServer. Edit this description."

def parse_stack(fpath):
    """Get all services and images from a compose file."""
    services = []
    try:
        content = open(fpath).read()
        in_services = False
        current_svc = None
        current_img = ""
        for line in content.split("\n"):
            if line.strip() == "services:":
                in_services = True; continue
            if in_services and re.match(r"^(networks|volumes|configs|secrets):", line):
                in_services = False; continue
            if in_services and re.match(r"^  [a-zA-Z0-9_-]+:\s*$", line):
                if current_svc: services.append((current_svc, current_img))
                current_svc = line.strip().rstrip(":")
                current_img = ""
            if in_services and current_svc and "image:" in line:
                current_img = line.split("image:",1)[1].strip().strip("'\"")
            if in_services and current_svc and "container_name:" in line:
                current_svc = line.split("container_name:",1)[1].strip()
        if current_svc: services.append((current_svc, current_img))
    except: pass
    return services

def sync_descriptions(stack_name, services, default_desc):
    """Add missing services to descriptions file."""
    os.makedirs(DESC_DIR, exist_ok=True)
    desc_file = os.path.join(DESC_DIR, f"{stack_name}.conf")
    try: existing = open(desc_file).read()
    except: existing = f"# {stack_name} — Service Descriptions\n# Edit the description under each service name.\n#\n"
    
    added = 0
    for svc, img in services:
        # Normalize - treat dash and underscore as same
        svc_norm = svc.replace("-","_")
        exists = re.search(rf"^{re.escape(svc)}\s*$", existing, re.MULTILINE)
        exists_norm = re.search(rf"^{re.escape(svc_norm)}\s*$", existing, re.MULTILINE)
        if not exists and not exists_norm:
            existing += f"\n{svc}\n# {default_desc}\n"
            added += 1
    
    if added:
        open(desc_file, "w").write(existing)
    return added

def sync_all_services(stack_name, services):
    """Update all_services.txt with new services."""
    try: existing = open(SVC_FILE).read()
    except: existing = "# ALL SERVICES — StacksServer\n# Format: stack | service | image\n# =========================================\n"
    
    added = 0
    section = f"# ── {stack_name.upper()}"
    for svc, img in services:
        if f"| {svc} " not in existing and f"| {svc}\n" not in existing:
            entry = f"{stack_name:<12} | {svc:<35} | {img}"
            if section in existing:
                lines = existing.split("\n")
                for i, l in enumerate(lines):
                    if l.startswith(section):
                        lines.insert(i+1, entry)
                        break
                existing = "\n".join(lines)
            else:
                existing += f"\n{section} ──────────────────────────────────────\n{entry}\n"
            added += 1
    
    if added:
        open(SVC_FILE, "w").write(existing)
    return added

def main():
    default_desc = get_default_desc()
    total_desc = 0
    total_svc = 0
    
    for fpath in sorted(glob.glob(f"{STACKS_DIR}/*.yml")):
        stack_name = os.path.basename(fpath).replace(".yml","")
        services = parse_stack(fpath)
        if not services: continue
        total_desc += sync_descriptions(stack_name, services, default_desc)
        total_svc  += sync_all_services(stack_name, services)
    
    if total_desc or total_svc:
        print(f"Sync: +{total_desc} descriptions, +{total_svc} all_services entries")

if __name__ == "__main__":
    main()
