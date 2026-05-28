#!/usr/bin/env python3
import sys, os, re

action     = sys.argv[1] # inject or strip
target     = sys.argv[2] # all or specific file path
conf_path  = "/home/loveiznothin/.config/stacks/bellzart.conf"
url_conf   = "/home/loveiznothin/.config/stacks/stack_urls.conf"
mode       = sys.argv[3] if len(sys.argv) > 3 else "all"  # art, urls, or all
stacks_dir = "/home/bellzserver/MyDocker/Stacks"

art = {'header':'', 'footer':'', 'xcaps':'', 'networks':'', 'volumes':'', 'services':''}

if os.path.exists(conf_path):
    with open(conf_path, 'r') as f:
        conf_content = f.read()
    dir_match = re.search(r'^DEFAULT_STACKS_DIR=[\"\'](.*)[\"\']', conf_content, re.MULTILINE)
    if dir_match:
        stacks_dir = dir_match.group(1)

    for var, key in [
        ('_ba_header',   'header'),
        ('_ba_footer',   'footer'),
        ('_ba_xcaps',    'xcaps'),
        ('_ba_networks', 'networks'),
        ('_ba_volumes',  'volumes'),
        ('_ba_services', 'services'),
    ]:
        start_marker = f"##BELLZART_START_{key.upper()}"
        end_marker = f"##BELLZART_END_{key.upper()}"
        if start_marker in conf_content and end_marker in conf_content:
            art[key] = conf_content.split(start_marker)[1].split(end_marker)[0].strip('\n')

def get_custom_stack_directory(file_path):
    if not os.path.exists(url_conf): return ""
    stack_name = os.path.splitext(os.path.basename(file_path))[0]
    
    try:
        with open(url_conf, 'r') as f:
            lines = f.read().splitlines()
        
        target_section = f"[{stack_name}]"
        in_section = False
        dir_lines = []
        
        for line in lines:
            s_line = line.strip()
            if s_line.startswith("[") and s_line.endswith("]"):
                if s_line == target_section:
                    in_section = True
                    continue
                elif in_section:
                    break
                else:
                    in_section = False
                    continue
            
            if in_section:
                dir_lines.append(line)
                    
        if dir_lines:
            return "\n".join(dir_lines).strip('\n')
    except:
        pass
    return ""

def strip_file(path):
    if not os.path.exists(path): return
    lines = open(path).readlines()
    out = []
    skip = False
    for l in lines:
        if '##BELLZART_START' in l: skip = True; continue
        if '##BELLZART_END' in l: skip = False; continue
        if not skip: out.append(l)
    # Also remove large comment blocks (art/URLs = 3+ consecutive # lines)
    cleaned = []
    i = 0
    while i < len(out):
        if out[i].strip().startswith('#'):
            block = []
            while i < len(out) and out[i].strip().startswith('#'):
                block.append(out[i]); i += 1
            if len(block) < 3:
                cleaned.extend(block)
        else:
            cleaned.append(out[i]); i += 1
    open(path, 'w').writelines(cleaned)

def inject_file(path):
    if not os.path.exists(path): return
    content = open(path).read()
    if 'services:' not in content and 'networks:' not in content: return
    strip_file(path)
    custom_directory = get_custom_stack_directory(path)
    lines = open(path).readlines()
    out = []
    did = {k: False for k in art}
    for line in lines:
        s = line.rstrip()
        if not did['header'] and re.match(r'^name:', s):
            out.append(line)
            if art['header']: out.append(art['header'] + "\n")
            if custom_directory and mode in ("all","urls"): out.append("\n" + custom_directory + "\n")
            did['header'] = True
            continue
        if not did['header'] and re.match(r'^services:', s):
            if art['header']: out.append(art['header'] + "\n")
            if custom_directory and mode in ("all","urls"): out.append("\n" + custom_directory + "\n")
            did['header'] = True
        if not did['xcaps'] and re.match(r'^x-', s):
            if art['xcaps']: out.append(art['xcaps'] + "\n")
            did['xcaps'] = True
        if not did['networks'] and re.match(r'^networks:', s):
            if art['networks']: out.append(art['networks'] + "\n")
            did['networks'] = True
        if not did['volumes'] and re.match(r'^volumes:', s):
            if art['volumes']: out.append(art['volumes'] + "\n")
            did['volumes'] = True
        if not did['services'] and re.match(r'^services:', s):
            if art['services']: out.append(art['services'] + "\n")
            did['services'] = True
        out.append(line)
    if art['footer']: out.append(art['footer'] + "\n")
    open(path, 'w').writelines(out)

files = []
if target == '--all' or target == 'all':
    files = [os.path.join(stacks_dir, f) for f in os.listdir(stacks_dir) if f.endswith('.yml') or f.endswith('.yaml')]
elif os.path.isabs(target) and os.path.isfile(target):
    files = [target]
elif os.path.isfile(os.path.join(stacks_dir, target)):
    files = [os.path.join(stacks_dir, target)]
elif os.path.isfile(os.path.join(stacks_dir, target + ".yml")):
    files = [os.path.join(stacks_dir, target + ".yml")]

for f in files:
    strip_file(f) if action == "strip" else inject_file(f)
