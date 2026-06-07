#!/usr/bin/env python3
"""
stacks_reclaim.py — reclaim disk by removing UNUSED tagged images, by size.

Lists every local image largest-first, classifies each as:
  • in-use     — a container (running OR stopped) is built on it, OR it is
                 referenced by image: in a stack compose file
  • unused     — tagged, but no container uses it and no stack references it
  • dangling   — untagged <none>:<none> leftovers (always safe to remove)

CRITICAL SAFETY: most stacks here are on-demand (Sablier) and sit DOWN most of
the time, so "no running container" does NOT mean unused. An image referenced by
any compose file is protected (config RECLAIM_PROTECT_STACK_IMAGES=1, default on).
Removal uses `docker rmi` WITHOUT --force, so an image still wired to any
container can never be pulled out from under it — Docker refuses and we skip it.

CLI:
    stacks_reclaim.py report  [--json] [--all] [--min-size MB]
    stacks_reclaim.py clean   [--auto] [--dangling] [--dry-run] [--min-size MB]
                              [--force]            # allow rmi --force (untag only)
"""
import os, sys, re, json, glob, subprocess, time

STACKS_DIR = os.environ.get("STACKS_DIR", "/srv/stacks/Stacks")
CONF_DIR   = os.path.expanduser(os.environ.get("STACKS_CONFIG_DIR", "~/.config/stacks"))
CONF_DIR   = os.path.expanduser(CONF_DIR)

# ───────────────────────── config ─────────────────────────
def load_conf():
    cfg = {}
    conf = os.path.join(CONF_DIR, "stacks.conf")
    if os.path.isfile(conf):
        for line in open(conf, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    try:
        sys.path.insert(0, "/usr/local/lib")
        import stacks_config as _sc
        cfg.update(_sc.load())
    except Exception:
        pass
    return cfg


def _bool(cfg, key, default="1"):
    return str(cfg.get(key, default)).strip().lower() not in ("0", "", "false", "no", "off")


# ───────────────────────── helpers ─────────────────────────
def _human(n):
    """bytes → human (decimal, matching docker)."""
    if n is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1000 or u == "TB":
            return (f"{f:.0f}{u}" if u == "B" or f >= 100 else f"{f:.1f}{u}")
        f /= 1000.0


def _run(args, timeout=60):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class _R:  # noqa
            returncode = 1; stdout = ""; stderr = str(e)
        return _R()


def stack_referenced_images():
    """Set of image refs (repo:tag) named by image: in any compose file."""
    refs = set()
    for fpath in glob.glob(os.path.join(STACKS_DIR, "*.yml")):
        try:
            for m in re.finditer(r'^\s*image:\s*([^\s#\n]+)', open(fpath, errors="replace").read(), re.M):
                img = m.group(1).strip().strip("'\"")
                if img:
                    refs.add(img)
                    if ":" not in img.split("/")[-1]:   # bare repo → :latest
                        refs.add(img + ":latest")
        except Exception:
            pass
    return refs


def container_image_ids():
    """Full image IDs every container (running OR stopped) is built on, plus the
    image *references* those containers report (name form)."""
    ids, names = set(), set()
    r = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Image}}"])
    if r.returncode != 0:
        return ids, names
    cids = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        cid, _, img = line.partition("\t")
        cids.append(cid.strip())
        if img.strip():
            names.add(img.strip())
    # resolve each container to its real image ID (handles name drift / retags)
    for cid in cids:
        ri = _run(["docker", "inspect", "--format", "{{.Image}}", cid], timeout=15)
        if ri.returncode == 0 and ri.stdout.strip():
            ids.add(ri.stdout.strip())
    return ids, names


def list_images():
    """Every local image as a dict: id, ref (repo:tag), size_bytes, dangling."""
    r = _run(["docker", "images", "--no-trunc", "--format",
              "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}"])
    out = []
    if r.returncode != 0:
        return out
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        iid, repo, tag, size = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        dangling = (repo == "<none>" or tag == "<none>")
        ref = "<none>" if dangling else f"{repo}:{tag}"
        out.append({"id": iid, "ref": ref, "repo": repo, "tag": tag,
                    "size": _parse_size(size), "size_h": size, "dangling": dangling})
    return out


def _parse_size(s):
    """'4.59GB' / '276MB' / '0B' → bytes (decimal, matching docker images)."""
    m = re.match(r'^([\d.]+)\s*([KMGT]?B)$', s.strip(), re.I)
    if not m:
        return 0
    val = float(m.group(1))
    mult = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}.get(m.group(2).upper(), 1)
    return int(val * mult)


def classify(min_size=0):
    """Return (rows, summary). rows sorted largest-first, each tagged with
    'status' in {in-use, unused, dangling}."""
    cfg = load_conf()
    protect_stacks = _bool(cfg, "RECLAIM_PROTECT_STACK_IMAGES", "1")
    stack_refs = stack_referenced_images() if protect_stacks else set()
    used_ids, used_names = container_image_ids()

    rows = []
    for img in list_images():
        if img["size"] < min_size:
            continue
        if img["dangling"]:
            status, why = "dangling", "untagged leftover"
        elif img["id"] in used_ids:
            status, why = "in-use", "container"
        elif img["ref"] in used_names or img["repo"] in used_names:
            status, why = "in-use", "container"
        elif protect_stacks and (img["ref"] in stack_refs or img["repo"] in stack_refs):
            status, why = "in-use", "stack file"
        else:
            status, why = "unused", "no container, no stack"
        img["status"], img["why"] = status, why
        rows.append(img)

    rows.sort(key=lambda r: r["size"], reverse=True)
    summary = {"total": len(rows)}
    for st in ("in-use", "unused", "dangling"):
        sel = [r for r in rows if r["status"] == st]
        summary[st] = {"count": len(sel), "bytes": sum(r["size"] for r in sel)}
    summary["reclaimable_bytes"] = summary["unused"]["bytes"] + summary["dangling"]["bytes"]
    return rows, summary


def docker_df_reclaimable():
    """Docker's authoritative image reclaimable bytes (accounts for shared layers)."""
    r = _run(["docker", "system", "df", "--format", "{{.Type}}\t{{.Reclaimable}}"])
    if r.returncode != 0:
        return None
    for line in r.stdout.strip().split("\n"):
        if line.lower().startswith("images"):
            m = re.search(r'([\d.]+\s*[KMGT]?B)', line.split("\t")[-1])
            if m:
                return _parse_size(m.group(1))
    return None


def remove(rows, force=False, dry_run=False):
    """rmi each row; returns (removed_count, freed_bytes_nominal, errors[])."""
    removed, freed, errors = 0, 0, []
    for r in rows:
        target = r["id"] if r["dangling"] else (r["ref"] if r["ref"] != "<none>" else r["id"])
        if dry_run:
            removed += 1; freed += r["size"]; continue
        args = ["docker", "rmi"] + (["--force"] if force else []) + [target]
        res = _run(args, timeout=120)
        if res.returncode == 0:
            removed += 1; freed += r["size"]
        else:
            errors.append((r["ref"], (res.stderr or res.stdout).strip().split("\n")[-1][:120]))
    return removed, freed, errors


# ────────────────────────────── CLI ──────────────────────────────
def _parse_flags(args):
    opts = {"min_size": 0}
    i = 0
    flags = set()
    while i < len(args):
        a = args[i]
        if a == "--min-size" and i + 1 < len(args):
            try:
                opts["min_size"] = int(float(args[i + 1]) * 1e6)
            except ValueError:
                pass
            i += 2; continue
        if a.startswith("--"):
            flags.add(a)
        i += 1
    opts["flags"] = flags
    return opts


def cmd_report(args):
    opts = _parse_flags(args)
    rows, summ = classify(opts["min_size"])
    if "--json" in opts["flags"]:
        print(json.dumps({"summary": summ, "images": rows}, indent=2)); return
    show_all = "--all" in opts["flags"]

    print(f"\n\033[1;35m🧹 Image disk reclaim\033[0m   ({summ['total']} images scanned)\n")
    print(f"  \033[1;32min-use\033[0m    {summ['in-use']['count']:>3}   {_human(summ['in-use']['bytes']):>9}")
    print(f"  \033[1;33munused\033[0m    {summ['unused']['count']:>3}   {_human(summ['unused']['bytes']):>9}")
    print(f"  \033[1;31mdangling\033[0m  {summ['dangling']['count']:>3}   {_human(summ['dangling']['bytes']):>9}")
    df = docker_df_reclaimable()
    stack_only = sum(r["size"] for r in rows if r["status"] == "in-use" and r["why"] == "stack file")
    print(f"\n  \033[1mReclaimable now (safe): ~{_human(summ['reclaimable_bytes'])}\033[0m "
          f"— unused + dangling, protects stacks")
    print(f"  \033[1maggressive: ~{_human(summ['reclaimable_bytes'] + stack_only)}\033[0m "
          f"— also drops {_human(stack_only)} of idle stack images (re-pull on next up)")
    print(f"  \033[2mdocker reports {_human(df)} 'reclaimable' overall (counts every stopped-stack image)\033[0m\n")

    cand = [r for r in rows if r["status"] in ("unused", "dangling")]
    shown = cand if show_all else cand[:25]
    if not cand:
        print("  ✓ Nothing to reclaim — every image is in use.\n"); return
    print("  \033[2mLargest reclaimable images:\033[0m")
    for r in shown:
        col = "\033[1;31m" if r["dangling"] else "\033[1;33m"
        tag = "dangling" if r["dangling"] else "unused"
        print(f"    {col}{_human(r['size']):>9}\033[0m  {tag:<8} {r['ref'][:54]}")
    if not show_all and len(cand) > len(shown):
        print(f"    \033[2m… +{len(cand) - len(shown)} more (use --all)\033[0m")
    print("\n  Reclaim:  stacks reclaim clean            (interactive)")
    print("            stacks reclaim clean --auto     (remove all unused+dangling)")
    print("            stacks reclaim clean --dangling (only untagged leftovers)\n")


def cmd_clean(args):
    opts = _parse_flags(args)
    rows, summ = classify(opts["min_size"])
    flags = opts["flags"]
    dangling_only = "--dangling" in flags
    aggressive = ("--aggressive" in flags) or ("--stacks-too" in flags)
    everything = ("--everything" in flags) or ("--nuke" in flags) or ("--all-images" in flags)
    auto = "--auto" in flags
    dry = "--dry-run" in flags
    force = "--force" in flags or everything

    # ── pick the tier ──────────────────────────────────────
    if everything:
        # NUKE: every image, including ones a container uses (force rmi). Images
        # held by a RUNNING container can't actually be removed and are skipped.
        cand = list(rows)
        mode = "EVERYTHING (incl. in-use — force)"
    elif aggressive:
        # Max space: delete everything NOT tied to a real container, including
        # idle stack images (they re-pull on next 'up'). Mirrors last night's pass.
        cand = [r for r in rows if r["why"] != "container"]
        mode = "aggressive (all but container-bound)"
    elif dangling_only:
        cand = [r for r in rows if r["status"] == "dangling"]
        mode = "dangling only"
    else:
        cand = [r for r in rows if r["status"] in ("unused", "dangling")]
        mode = "safe (unused + dangling)"
    if not cand:
        print("✓ Nothing to reclaim."); return

    nominal = sum(r["size"] for r in cand)
    print(f"\n\033[1mMode: {mode}\033[0m")
    print(f"{len(cand)} image(s) to remove — ~{_human(nominal)} nominal.")
    if everything:
        print("\033[1;31m⚠ This removes images your running stacks use — they will re-pull on next start.\033[0m")
    elif aggressive:
        print("\033[1;33m⚠ Idle stack images will be deleted and re-pulled the next time those stacks start.\033[0m")
    if dry:
        for r in cand:
            lbl = r["status"] if r["status"] != "in-use" else f"in-use:{r['why']}"
            print(f"  would remove  {_human(r['size']):>9}  {lbl:<14} {r['ref'][:50]}")
        print(f"\n(dry-run) would remove {len(cand)} images.\n"); return

    if not auto:
        for r in cand[:30]:
            lbl = r["status"] if r["status"] != "in-use" else f"in-use:{r['why']}"
            print(f"  {_human(r['size']):>9}  {lbl:<14} {r['ref'][:50]}")
        if len(cand) > 30:
            print(f"  … +{len(cand) - 30} more")
        prompt = "Type DELETE to confirm: " if everything else f"\nRemove these {len(cand)} images? [y/N]: "
        ans = input(prompt).strip()
        if (everything and ans != "DELETE") or (not everything and ans.lower() != "y"):
            print("Aborted."); return

    removed, freed, errors = remove(cand, force=force, dry_run=False)
    print(f"\n✓ Removed {removed}/{len(cand)} images (~{_human(freed)} nominal).")
    if errors:
        print(f"  {len(errors)} could not be removed (still referenced — skipped):")
        for ref, msg in errors[:8]:
            print(f"    • {ref}: {msg}")
        if len(errors) > 8:
            print(f"    … +{len(errors) - 8} more")
    df = docker_df_reclaimable()
    if df is not None:
        print(f"  Docker still reports {_human(df)} reclaimable.\n")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "report"
    rest = args[1:]
    if cmd == "report":
        cmd_report(rest)
    elif cmd == "clean":
        cmd_clean(rest)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
