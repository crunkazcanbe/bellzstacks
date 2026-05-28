#!/usr/bin/env python3
import os, re
STACKS_DIR = "/srv/stacks/Stacks"
OUT = "~/.config/stacks/all_services.txt"
lines = ["# ALL SERVICES — StacksServer\n# Format: stack | service | image\n# =========================================\n\n"]
stacks = sorted([f for f in os.listdir(STACKS_DIR) if f.endswith('.yml')])
total = 0
for yml in stacks:
    stack = yml.replace('.yml','')
    lines.append(f"# ── {stack.upper()} ──────────────────────────────────────\n")
    in_services = False
    current = None
    image = ''
    for line in open(os.path.join(STACKS_DIR, yml)):
        s = line.rstrip()
        if re.match(r'^services:', s): in_services = True; continue
        if re.match(r'^[a-zA-Z]', s) and not s.startswith(' ') and in_services: in_services = False; continue
        if not in_services: continue
        m = re.match(r'^  ([a-zA-Z0-9_.-]+):\s*$', s)
        if m:
            if current: lines.append(f"{stack:<12} | {current:<35} | {image}\n"); total += 1
            current = m.group(1); image = ''
            continue
        if current:
            im = re.match(r'\s+image:\s+(.+)', s)
            if im: image = im.group(1).strip()
    if current: lines.append(f"{stack:<12} | {current:<35} | {image}\n"); total += 1
    lines.append("\n")
open(OUT, 'w').writelines(lines)
print(f"  \033[1;32m✔ {total} services written to:\033[0m {OUT}")
