#!/usr/bin/env python3
import os
import re
import sys

STACKS_DIR = "/srv/stacks/Stacks"
CORE_FILES = ["core_0.yml", "core_1.yml", "core_2.yml", "core_3.yml"]

def run_guardian():
    if not os.path.exists(STACKS_DIR):
        print("Error: Stacks directory not found.")
        return

    # Phase 1 & 2: Map services and cluster master prefixes across files
    all_files = [f for f in os.listdir(STACKS_DIR) if f.endswith('.yml')]
    service_groups = {}  # base_name -> list of (file_path, service_name)
    
    # Simple regex rules to find bases and filter out database/cache suffixes
    suffix_trim = r'[-_](db|redis|postgres|mysql|mongo|cache|database|server|worker|frontend|backend|query-service)$'

    for fname in all_files:
        fpath = os.path.join(STACKS_DIR, fname)
        with open(fpath, 'r') as f:
            content = f.read()
        
        # Pull raw service names
        for line in content.splitlines():
            m = re.match(r'^  ([a-zA-Z0-9_.\-]+):\s*$', line)
            if m and not m.group(1).startswith('x-'):
                svc = m.group(1)
                base = re.sub(suffix_trim, '', svc, flags=re.I)
                if base not in service_groups:
                    service_groups[base] = []
                service_groups[base].append((fpath, svc))

    # Identify shared master networks needed (associated with 2+ services)
    networks_to_create = set()
    for base, associations in service_groups.items():
        if len(associations) >= 2 and base not in ['core', 'provisioner']:
            networks_to_create.add(f"{base}_net")

    # Inject networks into individual stack files
    for fname in all_files:
        if fname in CORE_FILES:
            continue
        fpath = os.path.join(STACKS_DIR, fname)
        with open(fpath, 'r') as f:
            lines = f.readlines()

        modified = False
        in_services = False
        current_svc = None
        current_svc_indent = 0
        
        new_lines = []
        # Trace line by line to inject network priorities cleanly
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            new_lines.append(line)
            
            if line.startswith('services:'):
                in_services = True
                idx += 1
                continue
                
            if in_services:
                # If we hit root-level keys like networks/volumes, services context ended
                if re.match(r'^[a-zA-Z0-9_-]+:', line):
                    in_services = False
                
                # Identify an individual container definition
                svc_match = re.match(r'^  ([a-zA-Z0-9_.\-]+):\s*$', line)
                if svc_match:
                    current_svc = svc_match.group(1)
                    # Check if this container needs a shared network bridge
                    base_name = re.sub(suffix_trim, '', current_svc, flags=re.I)
                    target_net = f"{base_name}_net" if f"{base_name}_net" in networks_to_create else None
                    
                    # Scan ahead to see if a networks block exists for this service
                    has_networks_block = False
                    net_block_idx = -1
                    scan_idx = idx + 1
                    while scan_idx < len(lines):
                        scan_line = lines[scan_idx]
                        if re.match(r'^  [a-zA-Z0-9_.\-]+:\s*$', scan_line) or re.match(r'^[a-zA-Z0-9_-]+:', scan_line):
                            break # hit next container or root block
                        if re.match(r'^    networks:\s*$', scan_line):
                            has_networks_block = True
                            net_block_idx = scan_idx
                            break
                        scan_idx += 1
                    
                    # Assemble proper dual networks layout strings
                    net_payload = []
                    if target_net:
                        net_payload.append(f"      {target_net}:\n        priority: 500\n")
                    net_payload.append("      traefik_net:\n        priority: 1000\n")
                    
                    if has_networks_block:
                        # If networks block exists, check if traefik_net or custom net are missing
                        # We will skip manual insertion here to preserve complex multi-line routing arrays
                        pass
                    else:
                        # Insert standard clean networks layout context block right under image/container_name
                        insert_idx = idx + 1
                        while insert_idx < len(lines):
                            if re.match(r'^    (image|container_name):', lines[insert_idx]):
                                lines.insert(insert_idx + 1, "    networks:\n" + "".join(net_payload))
                                modified = True
                                break
                            insert_idx += 1
            idx += 1

        # Build external references array declarations up top
        with open(fpath, 'r') as f:
            updated_content = f.read()
            
        if modified:
            # Inject top-level external definitions if missing
            if "networks:" not in updated_content:
                top_nets = "networks:\n  traefik_net: {name: traefik_net, external: true}\n"
                for n in networks_to_create:
                    if n in updated_content and f"  {n}:" not in updated_content:
                        top_nets += f"  {n}: {{name: {n}, external: true}}\n"
                updated_content = top_nets + "\n" + updated_content
            else:
                for n in networks_to_create:
                    if n in updated_content and f"  {n}:" not in updated_content:
                        updated_content = updated_content.replace("networks:\n", f"networks:\n  {n}: {{name: {n}, external: true}}\n")
            
            with open(fpath, 'w') as f:
                f.write(updated_content)

    # Phase 3: Core File Subnet & Provisioner Synchronization
    smallest_core_file = None
    smallest_size = float('inf')
    existing_subnets = set()

    for cfile in CORE_FILES:
        cpath = os.path.join(STACKS_DIR, cfile)
        if os.path.exists(cpath):
            size = os.path.getsize(cpath)
            if size < smallest_size:
                smallest_size = size
                smallest_core_file = cpath
            
            # Scrape existing allocated subnets to avoid collisions
            with open(cpath, 'r') as f:
                subnets = re.findall(r'10\.50\.(\count[0-9]{1,3})\.0/24', f.read())
                for s in subnets:
                    existing_subnets.add(int(s))

    if not smallest_core_file:
        print("Error: Core files not accessible.")
        return

    # Find the next completely vacant subnet index slot
    next_subnet_idx = 70
    while next_subnet_idx in existing_subnets:
        next_subnet_idx += 1

    # Inject new bridges into the selected smallest core file configuration
    with open(smallest_core_file, 'r') as f:
        core_content = f.read()

    core_modified = False
    for net in sorted(networks_to_create):
        if f"  {net}:" not in core_content:
            net_definition = f'''  {net}:
    name: {net}
    driver: bridge
    attachable: true
    external: false
    internal: false
    enable_ipv6: false
    labels:
      - "com.stacks.network={net.replace('_net','')}"
      - "com.stacks.env=production"
    ipam:
      driver: default
      config:
        - subnet: 10.50.{next_subnet_idx}.0/24
          gateway: 10.50.{next_subnet_idx}.1
'''
            core_content = core_content.replace("networks:\n", f"networks:\n{net_definition}")
            next_subnet_idx += 1
            core_modified = True

    # Sync provisioner_1b runtime definitions array
    if core_modified:
        # Inject matching networks array mapping line into provisioner service container block
        for net in sorted(networks_to_create):
            if f'- "{net}"' not in core_content and f'- {net}' not in core_content:
                core_content = core_content.replace("    networks:\n", f"    networks:\n      - \"{net}\"\n")
        
        with open(smallest_core_file, 'w') as f:
            f.write(core_content)
        print(f"SUCCESS: Guardian optimized infrastructure inside {os.path.basename(smallest_core_file)}")
    else:
        print("SUCCESS: Infrastructure configurations fully synchronized. No drift detected.")

if __name__ == '__main__':
    run_guardian()
