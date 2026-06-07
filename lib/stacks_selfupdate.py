#!/usr/bin/env python3
"""
stacks_selfupdate.py — check GitHub for updates to the stacks program (which
includes the TUI menu, stacks_menu.py) and apply them on request.

Model: the program is deployed from a git clone via its install.sh
(`cp bin/stacks /usr/local/bin`, `cp lib/*.py /usr/local/lib`). "Update" =
git fetch the clone, and if origin is ahead, `git pull --ff-only` then re-run
install.sh. The installed files are ALWAYS backed up first (reversible), and if
the installed copy has local edits not in the clone we warn before overwriting.

CLI:
    stacks_selfupdate.py check   [--json]   # fetch + report (default)
    stacks_selfupdate.py apply              # pull + backup + install
    stacks_selfupdate.py where              # print the detected repo dir
"""
import os, sys, json, glob, subprocess, time, shutil

CONF_DIR = os.path.expanduser(os.environ.get("STACKS_CONFIG_DIR", "~/.config/stacks"))
CONF_DIR = os.path.expanduser(CONF_DIR)
BACKUP_DIR = os.path.join(CONF_DIR, "selfupdate-backups")
INSTALL_BIN = "/usr/local/bin/stacks"
INSTALL_LIB = "/usr/local/lib"

CANDIDATE_REPOS = [
    "~/stacks", "~/git/stacks", "~/src/stacks",
    "~/.local/share/stacks", "~/projects/stacks",
]


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


def _git(repo, *args, timeout=60):
    try:
        return subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class _R:  # noqa
            returncode = 1; stdout = ""; stderr = str(e)
        return _R()


def _is_stacks_repo(path):
    return (os.path.isdir(os.path.join(path, ".git"))
            and os.path.isfile(os.path.join(path, "install.sh"))
            and os.path.isfile(os.path.join(path, "lib", "stacks_menu.py")))


def repo_dir():
    """Locate the stacks git clone. Config STACKS_REPO_DIR wins; else autodetect."""
    cfg = load_conf()
    p = cfg.get("STACKS_REPO_DIR", "").strip()
    if p:
        p = os.path.expanduser(p)
        if _is_stacks_repo(p):
            return p
    for cand in CANDIDATE_REPOS:
        cand = os.path.expanduser(cand)
        if _is_stacks_repo(cand):
            return cand
    return None


def branch_of(repo):
    cfg = load_conf()
    b = cfg.get("STACKS_UPDATE_BRANCH", "").strip()
    if b:
        return b
    r = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "master"


def _installed_dirty(repo):
    """True if installed /usr/local files differ from what's in the clone now
    (i.e. local edits that an install would overwrite). Returns (dirty, files)."""
    diffs = []
    rb = os.path.join(repo, "bin", "stacks")
    if os.path.isfile(rb) and os.path.isfile(INSTALL_BIN):
        if not _same(rb, INSTALL_BIN):
            diffs.append("bin/stacks")
    for f in glob.glob(os.path.join(repo, "lib", "*.py")):
        inst = os.path.join(INSTALL_LIB, os.path.basename(f))
        if os.path.isfile(inst) and not _same(f, inst):
            diffs.append("lib/" + os.path.basename(f))
    return bool(diffs), diffs


def _same(a, b):
    try:
        return open(a, "rb").read() == open(b, "rb").read()
    except Exception:
        return False


def status():
    """Fetch origin and report. Network call — cache the result in the caller."""
    repo = repo_dir()
    if not repo:
        return {"error": "No stacks git clone found. Set STACKS_REPO_DIR in stacks.conf "
                         "to the folder you installed from (the one with install.sh)."}
    branch = branch_of(repo)
    f = _git(repo, "fetch", "origin", branch, timeout=45)
    fetch_err = "" if f.returncode == 0 else (f.stderr or f.stdout).strip()[:160]
    cur = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    latest = _git(repo, "rev-parse", "--short", f"origin/{branch}").stdout.strip()
    behind = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}").stdout.strip() or "0"
    ahead = _git(repo, "rev-list", "--count", f"origin/{branch}..HEAD").stdout.strip() or "0"
    log = _git(repo, "log", "--oneline", "--no-decorate", f"HEAD..origin/{branch}")
    changelog = [l for l in log.stdout.strip().split("\n") if l.strip()] if log.returncode == 0 else []
    dirty, dirty_files = _installed_dirty(repo)
    try:
        behind_n = int(behind)
    except ValueError:
        behind_n = 0
    return {
        "repo": repo, "branch": branch,
        "current": cur, "latest": latest,
        "behind": behind_n, "ahead": int(ahead) if ahead.isdigit() else 0,
        "changelog": changelog,
        "installed_dirty": dirty, "dirty_files": dirty_files,
        "fetch_error": fetch_err,
        "up_to_date": (behind_n == 0 and not fetch_err),
    }


def _backup_installed():
    """Snapshot current installed bin + lib *.py before overwriting."""
    dst = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(os.path.join(dst, "lib"), exist_ok=True)
    try:
        if os.path.isfile(INSTALL_BIN):
            shutil.copy2(INSTALL_BIN, os.path.join(dst, "stacks"))
        for f in glob.glob(os.path.join(INSTALL_LIB, "stacks_*.py")):
            shutil.copy2(f, os.path.join(dst, "lib", os.path.basename(f)))
    except Exception:
        pass
    return dst


def apply(allow_overwrite_local=False):
    """git pull --ff-only then run install.sh (with sudo). Returns (ok, msg, log)."""
    st = status()
    if st.get("error"):
        return False, st["error"], []
    repo, branch = st["repo"], st["branch"]
    log = []
    if st["behind"] == 0 and not st["fetch_error"]:
        return True, "Already up to date.", []
    if st["installed_dirty"] and not allow_overwrite_local:
        return (False,
                f"Installed copy has {len(st['dirty_files'])} local change(s) not in git "
                f"(e.g. {', '.join(st['dirty_files'][:4])}). These would be overwritten. "
                f"Re-run with apply --force to proceed anyway (a backup is always made).",
                st["dirty_files"])
    bak = _backup_installed()
    log.append(f"backed up installed files → {bak}")
    pull = _git(repo, "pull", "--ff-only", "origin", branch, timeout=120)
    log.append((pull.stdout or "").strip())
    if pull.returncode != 0:
        return False, f"git pull failed: {(pull.stderr or pull.stdout).strip()[:160]}", log
    inst = subprocess.run(["sudo", "bash", os.path.join(repo, "install.sh")],
                          capture_output=True, text=True, timeout=180)
    log.append((inst.stdout or "").strip())
    if inst.returncode != 0:
        return False, f"install.sh failed: {(inst.stderr or inst.stdout).strip()[:160]}", log
    return True, f"Updated to {st['latest']} ({st['behind']} commit(s)). Restart the menu to load it.", log


# ────────────────────────────── CLI ──────────────────────────────
def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "check"

    if cmd == "where":
        r = repo_dir()
        print(r or "(no stacks git clone found)")
        return

    if cmd in ("check", "status"):
        st = status()
        if st.get("error"):
            print("⚠ " + st["error"]); sys.exit(2)
        if "--json" in args:
            print(json.dumps(st, indent=2)); return
        print(f"\n\033[1;35m⬆ stacks self-update\033[0m   repo: {st['repo']}  ({st['branch']})")
        print(f"  installed commit: {st['current']}   latest on GitHub: {st['latest']}")
        if st["fetch_error"]:
            print(f"  \033[1;33m⚠ couldn't reach GitHub: {st['fetch_error']}\033[0m")
        if st["up_to_date"]:
            print("  \033[1;32m✓ Up to date.\033[0m\n")
        else:
            print(f"  \033[1;33m⬆ {st['behind']} update(s) available:\033[0m")
            for line in st["changelog"][:15]:
                print(f"      {line}")
            if len(st["changelog"]) > 15:
                print(f"      … +{len(st['changelog']) - 15} more")
            if st["installed_dirty"]:
                print(f"  \033[1;31m⚠ installed copy has local changes ({len(st['dirty_files'])} files) "
                      f"that update would overwrite — use 'apply --force'.\033[0m")
            print("\n  Update:  stacks update apply\n")
        return

    if cmd == "apply":
        force = "--force" in args or "-f" in args
        print("Updating stacks from GitHub…")
        ok, msg, log = apply(allow_overwrite_local=force)
        for l in log:
            if l:
                print("  " + l)
        print(("✓ " if ok else "✗ ") + msg)
        sys.exit(0 if ok else 1)

    print(__doc__)


if __name__ == "__main__":
    main()
