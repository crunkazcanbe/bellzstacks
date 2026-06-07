#!/usr/bin/env python3
"""
stacks_volclean.py — strip UNUSED top-level named-volume declarations.

When a service is moved to a bind mount, its old top-level `volumes:` entry is
left orphaned — declared but referenced by nothing — yet Compose still tries to
create it. This finds declarations no service references and removes them, backing
up every file first.

SAFETY: a volume is only an orphan if BOTH (a) YAML analysis shows no service
mounts it, AND (b) its name does not appear as a mount source anywhere in the
file's text. A volume that is used is never removed. Removal is textual (only the
orphan's block is deleted; the rest of the file is untouched), and if the whole
top-level `volumes:` section becomes empty its header is removed too.

CLI:
    stacks_volclean.py report [--json]
    stacks_volclean.py clean [--auto] [stack ...]
"""
import os, sys, re, glob, json, shutil, time

STACKS_DIR = os.environ.get("STACKS_DIR", "/srv/stacks/Stacks")
BACKUP_DIR = os.path.expanduser("~/.config/stacks/volclean-backups")

try:
    import yaml
except Exception:
    yaml = None


def _is_named(src):
    """A volume mount source is a NAMED volume (not a bind mount/path)."""
    src = str(src).strip()
    return bool(src) and not src.startswith(("/", ".", "~", "$"))


def _referenced_as_mount(text, name):
    """Textual safety net: does `name` appear as a mount SOURCE in a service?"""
    n = re.escape(name)
    pats = [
        r'-\s*["\']?' + n + r':',            # short form:  - name:/path
        r'source:\s*["\']?' + n + r'["\']?(\s|$)',   # long form:  source: name
    ]
    return any(re.search(p, text, re.M) for p in pats)


def analyze(path):
    """Return (declared:set, used:set, orphans:sorted list) for one compose file."""
    if not yaml:
        return set(), set(), []
    try:
        data = yaml.safe_load(open(path, encoding="utf-8", errors="replace"))
    except Exception:
        return set(), set(), []
    if not isinstance(data, dict):
        return set(), set(), []
    topvols = data.get("volumes") or {}
    if not isinstance(topvols, dict):
        return set(), set(), []
    declared = set(topvols.keys())
    used = set()
    for _svc, body in (data.get("services") or {}).items():
        if not isinstance(body, dict):
            continue
        for v in (body.get("volumes") or []):
            if isinstance(v, str):
                src = v.split(":")[0].strip()
                if _is_named(src):
                    used.add(src)
            elif isinstance(v, dict):
                src = v.get("source")
                if src is not None and _is_named(src):
                    used.add(str(src))
    text = open(path, encoding="utf-8", errors="replace").read()
    orphans = sorted(n for n in declared
                     if n not in used and not _referenced_as_mount(text, n))
    return declared, used, orphans


def _backup(path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dst = os.path.join(BACKUP_DIR, f"{os.path.basename(path)}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(path, dst)
    return dst


def strip_orphans(path, orphans):
    """Remove orphan entries from the top-level volumes: section. Returns (n, backup)."""
    if not orphans:
        return 0, None
    raw = open(path, encoding="utf-8", errors="replace").read()
    lines = raw.split("\n")
    vstart = next((i for i, l in enumerate(lines) if re.match(r'^volumes:\s*$', l)), None)
    if vstart is None:
        return 0, None
    vend = len(lines)
    for j in range(vstart + 1, len(lines)):
        if lines[j].strip() == "":
            continue
        if re.match(r'^\S', lines[j]):       # next top-level key
            vend = j
            break
    section = lines[vstart + 1:vend]
    new_section, removed, i = [], 0, 0
    while i < len(section):
        m = re.match(r'^  ([A-Za-z0-9._-]+):', section[i])
        if m and m.group(1) in orphans:
            i += 1
            while i < len(section) and re.match(r'^    ', section[i]):   # 4+ space continuation
                i += 1
            removed += 1
        else:
            new_section.append(section[i]); i += 1
    if not removed:
        return 0, None
    bak = _backup(path)
    has_entry = any(re.match(r'^  \S', l) for l in new_section)
    if has_entry:
        rebuilt = lines[:vstart] + [lines[vstart]] + new_section + lines[vend:]
    else:                                    # volumes section now empty → drop header
        rebuilt = lines[:vstart] + lines[vend:]
    out = "\n".join(rebuilt).rstrip("\n") + "\n"
    open(path, "w", encoding="utf-8").write(out)
    return removed, bak


def scan_all():
    """[(stack, path, declared, used, orphans)] for every stack with orphans."""
    rows = []
    for path in sorted(glob.glob(os.path.join(STACKS_DIR, "*.yml"))):
        declared, used, orphans = analyze(path)
        if orphans:
            rows.append((os.path.basename(path)[:-4], path, declared, used, orphans))
    return rows


def ensure_named_decls(path):
    """Inverse of strip: add a top-level declaration for every NAMED volume a
    service references but that isn't declared (so the file is valid in 'named'
    mode). Returns (added_count, backup or None)."""
    declared, used, _orph = analyze(path)
    missing = sorted(used - declared)
    if not missing:
        return 0, None
    bak = _backup(path)
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    add = [f"  {n}:" for n in missing]
    vstart = next((i for i, l in enumerate(lines) if re.match(r'^volumes:\s*$', l)), None)
    if vstart is None:                                   # no volumes: section → append one
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines += ["volumes:"] + add
    else:                                                # insert at end of existing section
        vend = len(lines)
        for j in range(vstart + 1, len(lines)):
            if lines[j].strip() == "":
                continue
            if re.match(r'^\S', lines[j]):
                vend = j
                break
        lines = lines[:vend] + add + lines[vend:]
    open(path, "w", encoding="utf-8").write("\n".join(lines).rstrip("\n") + "\n")
    return len(missing), bak


def scan_missing():
    """[(stack, path, missing_list)] for stacks referencing undeclared named vols."""
    rows = []
    for path in sorted(glob.glob(os.path.join(STACKS_DIR, "*.yml"))):
        declared, used, _ = analyze(path)
        missing = sorted(used - declared)
        if missing:
            rows.append((os.path.basename(path)[:-4], path, missing))
    return rows


# ────────────────────────────── CLI ──────────────────────────────
def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "report"
    rows = scan_all()

    if cmd == "report":
        if "--json" in args:
            print(json.dumps({s: orph for s, _p, _d, _u, orph in rows}, indent=2)); return
        if not rows:
            print("✓ No unused top-level named volumes."); return
        total = sum(len(o) for *_x, o in rows)
        print(f"⚠ {total} unused top-level named-volume declaration(s) in {len(rows)} stack(s):\n")
        for stack, _p, decl, _u, orph in rows:
            print(f"  {stack:<14} {len(decl):>3} declared → {len(orph)} unused: "
                  f"{', '.join(orph[:6])}{' …' if len(orph) > 6 else ''}")
        print("\nClean up:  stacks volclean clean          (interactive, per-stack)")
        print("           stacks volclean clean --auto   (strip them all, with backups)")

    elif cmd == "clean":
        if not rows:
            print("✓ Nothing to clean."); return
        auto = "--auto" in args
        only = set(a for a in args[1:] if not a.startswith("-"))
        total = 0
        for stack, path, _d, _u, orph in rows:
            if only and stack not in only:
                continue
            if not auto:
                print(f"\n{stack}: {len(orph)} unused → {', '.join(orph)}")
                ans = input("  strip these? [y/N/q]: ").strip().lower()
                if ans == "q":
                    break
                if ans != "y":
                    print("  skipped."); continue
            n, bak = strip_orphans(path, orph)
            total += n
            print(f"  ✓ {stack}: stripped {n}  (backup: {bak})")
        print(f"\nDone — removed {total} unused volume declaration(s). "
              f"Backups in {BACKUP_DIR}")

    elif cmd == "ensure":
        miss = scan_missing()
        if not miss:
            print("✓ Every referenced named volume is already declared."); return
        only = set(a for a in args[1:] if not a.startswith("-"))
        total = 0
        for stack, path, missing in miss:
            if only and stack not in only:
                continue
            n, bak = ensure_named_decls(path)
            total += n
            print(f"  ✓ {stack}: added {n} declaration(s)  (backup: {bak})")
        print(f"\nDone — added {total} top-level volume declaration(s).")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
