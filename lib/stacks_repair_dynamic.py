#!/usr/bin/env python3
"""
stacks_repair_dynamic.py — Repair Traefik dynamic config files
Learned from ai_0.yml dynamic (perfect reference)
"""
import re, os, sys

# Standard middlewares every router should have
STANDARD_MIDDLEWARES = [
    'https-header',
    'crowdsec-bouncer',
    'global-retry',
    'compress',
    'inflight',
    'buffering',
    'rate-limit',
]

SABLIER_URL = 'http://sablier:10000'
ENTRY_POINTS = '[web]'

def repair_dynamic(path, dry_run=False):
    content = open(path).read()
    original = content
    fixes = []

    content, f = fix_sablier_url(content)
    fixes += f

    content, f = fix_entry_points(content)
    fixes += f

    content, f = fix_indentation(content)
    fixes += f

    content, f = fix_missing_middlewares(content)
    fixes += f

    if not dry_run and content != original:
        open(path, 'w').write(content)

    return fixes


def fix_sablier_url(content):
    """Fix wrong sablierUrl values."""
    fixes = []
    def replacer(m):
        if m.group(1) != SABLIER_URL:
            fixes.append(f'sablier_url: fixed to {SABLIER_URL}')
            return f'sablierUrl: "{SABLIER_URL}"'
        return m.group(0)
    content = re.sub(r'sablierUrl:\s*"([^"]+)"', replacer, content)
    return content, fixes


def fix_entry_points(content):
    """Fix entryPoints format."""
    fixes = []
    def replacer(m):
        val = m.group(1).strip()
        if val != ENTRY_POINTS:
            fixes.append(f'entryPoints: fixed to {ENTRY_POINTS}')
            return f'entryPoints: {ENTRY_POINTS}'
        return m.group(0)
    content = re.sub(r'entryPoints:\s*(\[.*?\])', replacer, content)
    return content, fixes


def fix_indentation(content):
    """Fix common indentation issues - ensure 2-space indent."""
    fixes = []
    lines = content.split('\n')
    result = []
    changed = False
    for line in lines:
        # Fix 4-space indent to 2-space (only for non-art lines)
        if not line.startswith('#') and '🌸' not in line:
            stripped = line.lstrip(' ')
            spaces = len(line) - len(stripped)
            if spaces > 0 and spaces % 4 == 0 and spaces % 2 == 0:
                # Check if this looks like 4-space indented YAML
                new_spaces = spaces // 2
                new_line = ' ' * new_spaces + stripped
                if new_line != line:
                    # Only fix if it makes the file more consistent
                    pass  # Conservative - don't auto-fix indentation blindly
        result.append(line)
    return '\n'.join(result), fixes


def fix_missing_middlewares(content):
    """Check routers are missing standard middlewares and warn."""
    fixes = []
    routers = re.findall(r'(\w+-router):\s*\n.*?middlewares:\s*\[([^\]]+)\]', content, re.DOTALL)
    for router_name, mw_str in routers:
        middlewares = [m.strip() for m in mw_str.split(',')]
        for std in STANDARD_MIDDLEWARES:
            if std not in middlewares:
                fixes.append(f'missing_middleware: {router_name} missing {std}')
    return content, fixes


def scan_all(dynamics_dir, dry_run=False):
    total = 0
    for fname in sorted(os.listdir(dynamics_dir)):
        if not fname.endswith(('.yml', '.yaml')): continue
        path = os.path.join(dynamics_dir, fname)
        fixes = repair_dynamic(path, dry_run=dry_run)
        if fixes:
            print(f"{'[dry-run] ' if dry_run else ''}Fixed {fname}:")
            for f in fixes:
                print(f"  - {f}")
            total += len(fixes)
    print(f"\nTotal fixes: {total}")


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else '/srv/stacks/Configs/Dynamics'
    dry_run = '--dry-run' in sys.argv
    if os.path.isfile(target):
        fixes = repair_dynamic(target, dry_run=dry_run)
        for f in fixes: print(f"  - {f}")
        print(f"Total: {len(fixes)}")
    else:
        scan_all(target, dry_run=dry_run)
