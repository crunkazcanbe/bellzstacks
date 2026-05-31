#!/usr/bin/env python3
import sys, re, os

path = sys.argv[1]
svc  = sys.argv[2]
val  = sys.argv[3]
skip = sys.argv[4].split() if (len(sys.argv) > 4 and val == "true") else []
prefix = re.match(r'([a-zA-Z]+)', os.path.basename(path)).group(1)

content = open(path).read()

if svc == "__all__":
    lines = content.splitlines()
    result = []
    skip_current = False
    in_labels = False
    label_insert_idx = None
    has_sablier = False

    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'\s+container_name:\s+(\S+)', line)
        if m:
            if not skip_current and not has_sablier and label_insert_idx is not None:
                result.insert(label_insert_idx, f'      - "sablier.enable={val}"')
                result.insert(label_insert_idx + 1, f'      - "sablier.group={prefix}"')
            skip_current = m.group(1) in skip
            in_labels = False
            has_sablier = False
            label_insert_idx = None

        if not skip_current:
            if re.match(r'\s+labels:\s*$', line):
                in_labels = True
                has_sablier = False
            elif in_labels and line.strip().startswith('- '):
                if 'sablier.enable' in line:
                    has_sablier = True
                    line = re.sub(r'sablier\.enable=(true|false)', f'sablier.enable={val}', line)
                else:
                    label_insert_idx = len(result) + 1
            elif in_labels and line.strip() and not line.strip().startswith('-'):
                if not has_sablier and label_insert_idx is not None:
                    result.insert(label_insert_idx, f'      - "sablier.enable={val}"')
                    result.insert(label_insert_idx + 1, f'      - "sablier.group={prefix}"')
                    has_sablier = True
                in_labels = False

        result.append(line)
        i += 1

    new_content = '\n'.join(result)
    if new_content != content:
        open(path, 'w').write(new_content)
else:
    if svc in skip:
        sys.exit(0)
    idx = content.find(f'container_name: {svc}')
    if idx < 0: sys.exit(0)
    end = content.find('\n  #', idx)
    if end < 0: end = len(content)
    block = content[idx:end]
    if 'sablier.enable' in block:
        new_block = re.sub(r'sablier\.enable=(true|false)', f'sablier.enable={val}', block)
    else:
        label_idx = block.find('labels:')
        if label_idx >= 0:
            insert = block.find('\n', label_idx + len('labels:'))
            new_block = block[:insert] + f'\n      - "sablier.enable={val}"\n      - "sablier.group={prefix}"' + block[insert:]
        else:
            new_block = block
    if new_block != block:
        open(path, 'w').write(content[:idx] + new_block + content[end:])
