#!/usr/bin/env python3
"""
stacks_dedupe.py — find & resolve duplicate container definitions across stacks.

Two containers can't share a container_name, so when the same container_name is
declared in more than one *.yml, only ONE can ever run — the rest silently lose
the name race. This finds those collisions and (optionally) removes the duplicate
service block from the stack(s) you don't want, backing up every file it edits.

Detection is YAML-aware (resolves anchors/merges); removal is textual (deletes
just the service's block, leaving the rest of the file — comments, anchors,
formatting — untouched). Every edited file is backed up first.

CLI:
    stacks_dedupe.py report [--json]          # list duplicates (read-only)
    stacks_dedupe.py fix                       # interactive: pick a keeper per clash
    stacks_dedupe.py fix --auto               # keep the running / most-complete one
    stacks_dedupe.py keep <cname> <stack>     # keep <cname> in <stack>, strip the rest
"""
import os, sys, re, glob, json, shutil, subprocess, time

STACKS_DIR = os.environ.get("STACKS_DIR", "/srv/stacks/Stacks")
BACKUP_DIR = os.path.expanduser("~/.config/stacks/dedupe-backups")

try:
    import yaml
except Exception:
    yaml = None


def _stack_files():
    return sorted(glob.glob(os.path.join(STACKS_DIR, "*.yml")))


def _parse(file):
    """{service_name: {container_name, image, explicit_cname}} for one compose file."""
    out = {}
    data = None
    if yaml:
        try:
            data = yaml.safe_load(open(file, encoding="utf-8", errors="replace"))
        except Exception:
            data = None
    if isinstance(data, dict) and isinstance(data.get("services"), dict):
        for svc, body in data["services"].items():
            body = body if isinstance(body, dict) else {}
            cn = body.get("container_name")
            out[svc] = {"container_name": str(cn) if cn else svc,
                        "image": str(body.get("image") or ""),
                        "explicit_cname": cn is not None}
        return out
    # Fallback: indentation-aware regex (used only if YAML fails to parse)
    cur = None
    in_services = False
    for line in open(file, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if re.match(r'^services:\s*$', line):
            in_services = True; continue
        if in_services and re.match(r'^\S', line):
            in_services = False
        if not in_services:
            continue
        m = re.match(r'^  ([A-Za-z0-9._-]+):\s*$', line)
        if m:
            cur = m.group(1)
            out[cur] = {"container_name": cur, "image": "", "explicit_cname": False}
        elif cur:
            mc = re.match(r'^\s+container_name:\s*([^\s#]+)', line)
            if mc:
                out[cur]["container_name"] = mc.group(1).strip('"\'')
                out[cur]["explicit_cname"] = True
            mi = re.match(r'^\s+image:\s*([^\s#]+)', line)
            if mi:
                out[cur]["image"] = mi.group(1).strip('"\'')
    return out


def scan():
    """container_name -> [ {stack, file, service, image, explicit} ]"""
    by_cname = {}
    for f in _stack_files():
        stack = os.path.basename(f)[:-4]
        for svc, info in _parse(f).items():
            by_cname.setdefault(info["container_name"], []).append(
                {"stack": stack, "file": f, "service": svc,
                 "image": info["image"], "explicit": info["explicit_cname"]})
    return by_cname


def duplicates():
    """Only the container_names declared in more than one stack file."""
    return {cn: locs for cn, locs in scan().items()
            if len({l["stack"] for l in locs}) > 1}


def _docker_info():
    """{container_name: (state, compose_project)} for every container docker knows."""
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format",
             '{{.Names}}\t{{.State}}\t{{.Label "com.docker.compose.project"}}'],
            capture_output=True, text=True, timeout=8)
        out = {}
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            if parts and parts[0]:
                out[parts[0]] = (parts[1] if len(parts) > 1 else "",
                                 parts[2] if len(parts) > 2 else "")
        return out
    except Exception:
        return {}


def _docker_states():
    """{container_name: state} (compat shim)."""
    return {n: v[0] for n, v in _docker_info().items()}


def _service_line_count(file, service):
    """How many lines the service's block spans (a proxy for 'completeness')."""
    s, e = _block_bounds(file, service)
    return (e - s) if s is not None else 0


def _block_bounds(file, service):
    """(start, end) line indices of a service block (end exclusive), or (None,None)."""
    lines = open(file, encoding="utf-8", errors="replace").read().split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(rf'^  {re.escape(service)}:\s*$', l):
            start = i; break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() == "":
            continue
        if re.match(r'^  \S', l) or re.match(r'^\S', l):  # next sibling service / top-level key
            end = j; break
    return start, end


def recommend_keeper(cname, locs):
    """Pick which stack should keep cname, with a human reason.
    Priority: the stack that actually owns the live container (by compose project)
    → any stack owning an existing container → running state → most-complete block."""
    info = _docker_info()
    state, project = info.get(cname, ("", ""))
    # 1) the stack whose compose project actually created this container
    if project:
        owner = [l for l in locs if l["stack"] == project]
        if owner:
            verb = "running" if state.lower() == "running" else state or "present"
            return owner[0]["stack"], f"owns the live container ({verb})"
    # 2) container exists but project label didn't match a stack — favour running
    if state.lower() == "running":
        return locs[0]["stack"], "container is running"
    if state:
        return locs[0]["stack"], f"docker already has it ({state})"
    # 3) nothing in docker → keep the most complete definition
    best = max(locs, key=lambda l: _service_line_count(l["file"], l["service"]))
    return best["stack"], "most complete definition"


def _backup(file):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"{os.path.basename(file)}.{ts}.bak")
    shutil.copy2(file, dst)
    return dst


def remove_service(file, service):
    """Delete a service block from a file (after backing the file up)."""
    start, end = _block_bounds(file, service)
    if start is None:
        return False, f"'{service}' not found in {os.path.basename(file)}", None
    bak = _backup(file)
    lines = open(file, encoding="utf-8", errors="replace").read().split("\n")
    removed = end - start
    del lines[start:end]
    out = "\n".join(lines).rstrip("\n") + "\n"   # always end with exactly one newline
    open(file, "w", encoding="utf-8").write(out)
    return True, f"removed '{service}' ({removed} lines) from {os.path.basename(file)}", bak


def keep_in(cname, keep_stack):
    """Keep cname in keep_stack; strip its block from every other stack. Returns log."""
    locs = duplicates().get(cname)
    if not locs:
        return [(False, f"no duplicate named '{cname}'", None)]
    if keep_stack not in {l["stack"] for l in locs}:
        return [(False, f"'{cname}' is not in stack '{keep_stack}'", None)]
    log = []
    for loc in locs:
        if loc["stack"] == keep_stack:
            continue
        log.append(remove_service(loc["file"], loc["service"]))
    return log


# ────────────────────────────── CLI ──────────────────────────────
def _print_report(dups):
    if not dups:
        print("✓ No duplicate container_names across stacks.")
        return
    states = _docker_states()
    print(f"⚠ {len(dups)} duplicate container_name(s) — only one of each can run:\n")
    for cn in sorted(dups):
        locs = dups[cn]
        keep, why = recommend_keeper(cn, locs)
        st = states.get(cn, "—")
        print(f"  ● {cn}   (docker: {st})")
        for l in locs:
            tag = "  ← keep (%s)" % why if l["stack"] == keep else ""
            img = f"  [{l['image']}]" if l["image"] else ""
            print(f"      {l['stack']:<12} svc:{l['service']}{img}{tag}")
        print()
    print("Resolve:  stacks dedupe fix         (choose per clash)")
    print("          stacks dedupe fix --auto  (keep running/most-complete)")
    print("          stacks dedupe keep <name> <stack>")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "report"

    if cmd == "report":
        dups = duplicates()
        if "--json" in args:
            print(json.dumps({k: v for k, v in dups.items()}, indent=2)); return
        _print_report(dups)

    elif cmd == "keep" and len(args) >= 3:
        for ok, msg, _ in keep_in(args[1], args[2]):
            print(("✓ " if ok else "✗ ") + msg)

    elif cmd == "fix":
        dups = duplicates()
        if not dups:
            print("✓ Nothing to fix — no duplicates."); return
        auto = "--auto" in args
        for cn in sorted(dups):
            locs = dups[cn]
            keep, why = recommend_keeper(cn, locs)
            if auto:
                chosen = keep
                print(f"● {cn}: keeping '{chosen}' ({why})")
            else:
                print(f"\n● {cn} is in: " + ", ".join(l["stack"] for l in locs))
                print(f"  recommended keeper: {keep} ({why})")
                ans = input(f"  keep which stack? [{keep}] (or 's' to skip): ").strip()
                if ans.lower() == "s":
                    print("  skipped."); continue
                chosen = ans or keep
                if chosen not in {l["stack"] for l in locs}:
                    print(f"  '{chosen}' isn't one of them — skipped."); continue
            for ok, msg, bak in keep_in(cn, chosen):
                print("   " + ("✓ " if ok else "✗ ") + msg + (f"  (backup: {bak})" if bak else ""))
        print("\nDone. Run 'stacks up' to apply (recreates the kept containers cleanly).")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
