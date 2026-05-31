#!/usr/bin/env python3
import sys, re, os

path = sys.argv[1]
svc  = sys.argv[2]
val  = sys.argv[3]
skip = sys.argv[4].split() if len(sys.argv) > 4 else []

content = open(path).read()

if svc == "__all__":
    lines = content.splitlines()
    result = []
    skip_current = False
    for line in lines:
        m = re.match(r'\s+container_name:\s+(\S+)', line)
        if m:
            skip_current = m.group(1) in skip
        if not skip_current:
            line = re.sub(r'traefik\.enable=(true|false)', f'traefik.enable={val}', line)
        result.append(line)
    new_content = '\n'.join(result)
    if new_content != content:
        open(path, 'w').write(new_content)
else:
    if svc in skip:
        sys.exit(0)
    idx = content.find(f'container_name: {svc}')
    if idx < 0:
        sys.exit(0)
    end = content.find('\n  #', idx)
    if end < 0: end = len(content)
    block = content[idx:end]
    new_block = re.sub(r'traefik\.enable=(true|false)', f'traefik.enable={val}', block)
    if new_block != block:
        open(path, 'w').write(content[:idx] + new_block + content[end:])
