#!/usr/bin/env python3
"""
stacks_fix_dynamic.py — Reconcile Traefik dynamic config files against the
authoritative container names declared in the compose stacks.

Two places in a dynamic reference a container name:
  1. service backend URLs :  url: "http://<host>:<port>"
  2. sablier middleware   :  names: "<c1>,<c2>"

Rules (intentionally conservative — these are live routing files):
  - IP-address hosts (e.g. 192.168.1.50) are LEFT ALONE.  Converting IP->name
    is a separate task (needs shared networks verified first).
  - A token that already matches a real container_name is LEFT ALONE.
  - A stale token is matched to a real name by separator-insensitive compare
    (drop - _ . , lowercase).  If EXACTLY ONE real name matches -> rewrite.
  - Ambiguous (>1 match) or unmatched (orphan) tokens are LEFT ALONE and
    REPORTED so the human can decide.

A .bak-dynfix-<ts> backup is written before a file is changed.

CLI:
  stacks_fix_dynamic.py all            [--dry-run]   # every dynamic
  stacks_fix_dynamic.py <name> [...]   [--dry-run]   # stack name(s) or dynamic file(s)

Env overrides: STACKS_DIR, DYNAMICS_DIR
"""
import os, re, sys, glob, time, shutil

DEFAULT_STACKS = "/srv/stacks/Stacks"
DEFAULT_DYN    = "/srv/stacks/Configs/Dynamics"

_IP_RE  = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
# url: "http://host:8080"   (quotes optional, http/https)
_URL_RE = re.compile(r'(url:\s*["\']?https?://)([A-Za-z0-9_.\-]+)(:\d+)')
# names: "a,b,c"
_NAMES_RE = re.compile(r'(names:\s*["\'])([^"\']+)(["\'])')


def _norm(name):
    return name.replace("-", "").replace("_", "").replace(".", "").lower()


def build_auth(stacks_dir):
    """Return (auth_set, norm_map) from every container_name in the stacks.
    norm_map maps separator-stripped form -> sorted list of real names."""
    auth = set()
    for f in glob.glob(os.path.join(stacks_dir, "*.yml")):
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for cn in re.findall(r"container_name:\s*(\S+)", txt):
            auth.add(cn.strip().strip('"').strip("'"))
    norm_map = {}
    for a in auth:
        norm_map.setdefault(_norm(a), []).append(a)
    for k in norm_map:
        norm_map[k] = sorted(norm_map[k])
    return auth, norm_map


def _resolve(token, auth, norm_map):
    """Return (status, value).
    status: 'ok' (already valid), 'ip', 'map' (value=new name),
            'orphan' (no match), 'ambiguous' (value=candidates)."""
    if _IP_RE.match(token):
        return "ip", token
    if token in auth:
        return "ok", token
    cands = norm_map.get(_norm(token), [])
    if len(cands) == 1 and cands[0] != token:
        return "map", cands[0]
    if len(cands) > 1:
        return "ambiguous", cands
    return "orphan", token


def fix_text(text, auth, norm_map):
    """Return (new_text, changes, orphans). changes=[(kind,old,new)],
    orphans=[(kind,token,detail)]."""
    changes = []
    orphans = []

    def url_sub(m):
        host = m.group(2)
        st, val = _resolve(host, auth, norm_map)
        if st == "map":
            changes.append(("url", host, val))
            return m.group(1) + val + m.group(3)
        if st == "orphan":
            orphans.append(("url", host, "no container"))
        elif st == "ambiguous":
            orphans.append(("url", host, "ambiguous: " + ",".join(val)))
        return m.group(0)

    text = _URL_RE.sub(url_sub, text)

    def names_sub(m):
        toks = [t.strip() for t in m.group(2).split(",")]
        out = []
        for t in toks:
            if not t:
                continue
            st, val = _resolve(t, auth, norm_map)
            if st == "map":
                changes.append(("names", t, val))
                out.append(val)
            else:
                if st == "orphan":
                    orphans.append(("names", t, "no container"))
                elif st == "ambiguous":
                    orphans.append(("names", t, "ambiguous: " + ",".join(val)))
                out.append(t)
        return m.group(1) + ",".join(out) + m.group(3)

    text = _NAMES_RE.sub(names_sub, text)
    return text, changes, orphans


def fix_file(path, auth, norm_map, dry_run=False):
    try:
        original = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return {"path": path, "error": str(e), "changes": [], "orphans": []}
    new, changes, orphans = fix_text(original, auth, norm_map)
    wrote = False
    if changes and new != original and not dry_run:
        shutil.copy2(path, path + ".bak-dynfix-%d" % int(time.time()))
        open(path, "w", encoding="utf-8").write(new)
        wrote = True
    return {"path": path, "changes": changes, "orphans": orphans, "wrote": wrote}


def find_targets(names, dyn_dir):
    """Map user tokens (stack names / dynamic stems / files) to dynamic paths."""
    allf = [f for f in sorted(glob.glob(os.path.join(dyn_dir, "*.yml")))
            if ".bak" not in os.path.basename(f)]
    if not names or names == ["all"]:
        return allf
    out = []
    for tok in names:
        b = os.path.basename(tok)
        # exact file
        cand = os.path.join(dyn_dir, b)
        if os.path.isfile(cand) and ".bak" not in b:
            out.append(cand); continue
        # stack name (ai_0) or stem (ai0) -> <stem>-*.yml
        stem = b.replace(".yml", "").replace("_", "")
        m = [f for f in allf if os.path.basename(f).split("-")[0] == stem]
        if m:
            out.extend(m)
        else:
            sys.stderr.write("  no dynamic for '%s'\n" % tok)
    # de-dup preserve order
    seen = set(); uniq = []
    for f in out:
        if f not in seen:
            seen.add(f); uniq.append(f)
    return uniq


def main(argv):
    stacks_dir = os.environ.get("STACKS_DIR", DEFAULT_STACKS)
    dyn_dir    = os.environ.get("DYNAMICS_DIR", DEFAULT_DYN)
    dry = "--dry-run" in argv
    names = [a for a in argv if not a.startswith("--")]

    auth, norm_map = build_auth(stacks_dir)
    if not auth:
        print("  \033[1;31m✘ no container_name found in %s\033[0m" % stacks_dir)
        return 1
    targets = find_targets(names, dyn_dir)
    if not targets:
        print("  no matching dynamic files")
        return 0

    tag = "[dry-run] " if dry else ""
    total_ch = 0
    orphan_lines = []
    for path in targets:
        r = fix_file(path, auth, norm_map, dry_run=dry)
        b = os.path.basename(path)
        if r.get("error"):
            print("  \033[1;31m✘ %s: %s\033[0m" % (b, r["error"])); continue
        if r["changes"]:
            total_ch += len(r["changes"])
            verb = "would fix" if dry else ("fixed" if r.get("wrote") else "fixed")
            print("  \033[1;32m✔ %s%s %s (%d)\033[0m" % (tag, verb, b, len(r["changes"])))
            for kind, old, new in r["changes"]:
                print("      %-6s %s -> %s" % (kind, old, new))
        for kind, tok, detail in r["orphans"]:
            orphan_lines.append("  \033[1;33m⚠ %-22s %-6s %s (%s)\033[0m" % (b, kind, tok, detail))

    if orphan_lines:
        print("\n\033[1;33m── Orphans / unresolved (left untouched, review manually) ──\033[0m")
        for ln in orphan_lines:
            print(ln)

    print("\n\033[1;36m%sTotal name fixes: %d across %d file(s); %d orphan ref(s)\033[0m"
          % (tag, total_ch, len(targets), len(orphan_lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
