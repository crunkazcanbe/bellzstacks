#!/usr/bin/env python3
"""
stacks_image_history.py — per-image version history + rollback.

Keeps a SQLite history of every distinct image digest we've seen for each
`repo:tag` referenced by the stacks, so you can roll a container back to an
older version. Config:
    IMAGE_HISTORY_ENABLED = 1     # record snapshots
    IMAGE_HISTORY_KEEP    = 10    # versions kept per image (oldest pruned)

CLI:
    stacks_image_history.py snapshot          # record current digest of every image
    stacks_image_history.py list <image>      # show recorded versions, newest first
    stacks_image_history.py rollback <image> <digest>   # pin+retag+(caller recreates)
    stacks_image_history.py prune             # enforce keep-count on all images
"""
import os, sys, time, json, sqlite3, subprocess, re

CONF_DIR = os.path.expanduser(os.environ.get("STACKS_CONFIG_DIR", "~/.config/stacks"))
CONF_DIR = os.path.expanduser(CONF_DIR)
DB_PATH  = os.path.join(CONF_DIR, "image_history.db")

# Reuse the updates module's image discovery + digest helpers when available.
sys.path.insert(0, "/usr/local/lib")
try:
    import stacks_updates as _su
except Exception:
    _su = None


def load_conf():
    """Read a few keys from stacks.conf (+ stacks.yaml overlay via stacks_config)."""
    cfg = {}
    conf = os.path.join(CONF_DIR, "stacks.conf")
    if os.path.isfile(conf):
        for line in open(conf, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    try:
        import stacks_config as _sc
        cfg.update(_sc.load())
    except Exception:
        pass
    return cfg


def keep_count():
    try:
        n = int(load_conf().get("IMAGE_HISTORY_KEEP", "10"))
        return max(1, n)
    except Exception:
        return 10


def enabled():
    return str(load_conf().get("IMAGE_HISTORY_ENABLED", "1")).strip() not in ("0", "", "false", "no")


def _db():
    os.makedirs(CONF_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS versions (
        image      TEXT NOT NULL,
        digest     TEXT NOT NULL,
        image_id   TEXT,
        first_seen INTEGER,
        last_seen  INTEGER,
        PRIMARY KEY (image, digest))""")
    return con


def short(d):
    """Short form of a sha256:... digest for display."""
    if not d:
        return "—"
    d = d.split(":")[-1]
    return d[:12]


def _inspect(image):
    """Return (digest, image_id) for a locally-present image, or (None, None)."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format",
             "{{index .RepoDigests 0}}|{{.Id}}", image],
            capture_output=True, text=True, timeout=8)
        if r.returncode == 0 and r.stdout.strip():
            rd, _, iid = r.stdout.strip().partition("|")
            digest = rd.split("@", 1)[1] if "@" in rd else ""
            return (digest or None), (iid.strip() or None)
    except Exception:
        pass
    return None, None


def record(image, digest=None, image_id=None):
    """Upsert the current (or supplied) version for `image`, then prune to keep-count.
    Returns the digest recorded, or None if nothing to record."""
    if digest is None:
        digest, image_id = _inspect(image)
    if not digest:
        return None
    now = int(time.time())
    con = _db()
    try:
        cur = con.execute("SELECT 1 FROM versions WHERE image=? AND digest=?", (image, digest))
        if cur.fetchone():
            con.execute("UPDATE versions SET last_seen=?, image_id=COALESCE(?, image_id) "
                        "WHERE image=? AND digest=?", (now, image_id, image, digest))
        else:
            con.execute("INSERT INTO versions(image,digest,image_id,first_seen,last_seen) "
                        "VALUES(?,?,?,?,?)", (image, digest, image_id, now, now))
        con.commit()
        _prune(con, image, keep_count())
    finally:
        con.close()
    return digest


def _prune(con, image, keep):
    rows = con.execute("SELECT digest FROM versions WHERE image=? ORDER BY last_seen DESC",
                       (image,)).fetchall()
    extra = [r[0] for r in rows[keep:]]
    for d in extra:
        con.execute("DELETE FROM versions WHERE image=? AND digest=?", (image, d))
    if extra:
        con.commit()


def history(image):
    """Recorded versions for an image, newest-first. Marks the one in use now."""
    con = _db()
    try:
        rows = con.execute(
            "SELECT digest,image_id,first_seen,last_seen FROM versions "
            "WHERE image=? ORDER BY last_seen DESC", (image,)).fetchall()
    finally:
        con.close()
    cur_digest, _ = _inspect(image)
    out = []
    for digest, iid, fs, ls in rows:
        out.append({"image": image, "digest": digest, "image_id": iid,
                    "first_seen": fs, "last_seen": ls, "short": short(digest),
                    "current": (digest == cur_digest)})
    return out


def _repo_no_tag(image):
    """Strip a trailing :tag from the last path segment so we can pin @digest."""
    parts = image.rsplit(":", 1)
    if len(parts) == 2 and "/" not in parts[1]:
        return parts[0]
    return image


def record_all():
    """Snapshot the current digest of every image referenced by the stacks that
    is present locally. Returns (recorded, total). Per-image inspect (thorough)."""
    if not _su:
        return 0, 0
    images = _su.get_all_images()
    rec = 0
    for image in images:
        if record(image):
            rec += 1
    return rec, len(images)


def record_from_docker_images(only_stack_images=True):
    """Fast snapshot: parse a single `docker images --digests` call and record
    every locally-present repo:tag (optionally limited to images the stacks use).
    Much cheaper than record_all() — use this for background/periodic snapshots.
    Returns (recorded, scanned)."""
    try:
        r = subprocess.run(
            ["docker", "images", "--digests", "--format",
             "{{.Repository}}:{{.Tag}}\t{{.Digest}}\t{{.ID}}"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return 0, 0
    if r.returncode != 0:
        return 0, 0
    wanted = set(_su.get_all_images().keys()) if (only_stack_images and _su) else None
    now = int(time.time())
    rec = 0; scanned = 0; touched = set()
    con = _db()
    try:
        for line in r.stdout.strip().split("\n"):
            if not line.strip() or "\t" not in line:
                continue
            parts = line.split("\t")
            image = parts[0].strip()
            digest = parts[1].strip() if len(parts) > 1 else ""
            iid = parts[2].strip() if len(parts) > 2 else None
            if image.endswith(":<none>") or digest in ("", "<none>"):
                continue
            if "@" in digest:
                digest = digest.split("@", 1)[1]
            if wanted is not None and image not in wanted:
                continue
            scanned += 1
            cur = con.execute("SELECT 1 FROM versions WHERE image=? AND digest=?", (image, digest))
            if cur.fetchone():
                con.execute("UPDATE versions SET last_seen=?, image_id=COALESCE(?, image_id) "
                            "WHERE image=? AND digest=?", (now, iid, image, digest))
            else:
                con.execute("INSERT INTO versions(image,digest,image_id,first_seen,last_seen) "
                            "VALUES(?,?,?,?,?)", (image, digest, iid, now, now))
            touched.add(image); rec += 1
        con.commit()
        for im in touched:
            _prune(con, im, keep_count())
    finally:
        con.close()
    return rec, scanned


def rollback(image, digest):
    """Pin `image` to an older `digest`: pull it by digest, then retag the
    repo:tag to it. Caller recreates the container afterward.
    Returns (ok, message)."""
    repo = _repo_no_tag(image)
    ref = f"{repo}@{digest}"
    # 1) make sure the old version is present (fast if layers are cached)
    p = subprocess.run(["docker", "pull", ref], capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        return False, f"pull {ref} failed: {(p.stderr or p.stdout).strip()[:140]}"
    # 2) point repo:tag at the pinned digest
    t = subprocess.run(["docker", "tag", ref, image], capture_output=True, text=True, timeout=30)
    if t.returncode != 0:
        return False, f"tag failed: {(t.stderr or t.stdout).strip()[:140]}"
    record(image, digest=digest)
    return True, f"{image} -> {short(digest)} (recreate to apply)"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "snapshot":
        if not enabled():
            print("image history disabled (IMAGE_HISTORY_ENABLED=0)"); return
        thorough = "--thorough" in args
        rec, tot = record_all() if thorough else record_from_docker_images()
        print(f"recorded {rec}/{tot} images into {DB_PATH} (keep {keep_count()} each)")
    elif cmd == "list" and len(args) >= 2:
        for v in history(args[1]):
            mark = " (current)" if v["current"] else ""
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(v["last_seen"]))
            print(f"  {v['short']}  last_seen {when}{mark}")
    elif cmd == "rollback" and len(args) >= 3:
        ok, msg = rollback(args[1], args[2])
        print(("OK: " if ok else "FAIL: ") + msg)
        sys.exit(0 if ok else 1)
    elif cmd == "prune":
        con = _db()
        try:
            imgs = [r[0] for r in con.execute("SELECT DISTINCT image FROM versions").fetchall()]
            for im in imgs:
                _prune(con, im, keep_count())
        finally:
            con.close()
        print(f"pruned to keep {keep_count()} per image ({len(imgs)} images)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
