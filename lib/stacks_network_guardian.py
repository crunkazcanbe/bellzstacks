#!/usr/bin/env python3
"""
stacks_network_guardian.py — SAFE REPLACEMENT

The original guardian rewrote stack & core files with blind string-replace,
had a broken subnet-scan regex (\\count) that made it think every subnet was
free, and force-injected traefik_net into services. That corrupted core files
and clobbered working configs.

This replacement does the SAME job (define missing networks/volumes into the
smallest creator file, with correct non-colliding subnets) by reusing the
audited logic in stacks_fix.py. It does NOT touch service files, does NOT
inject traefik_net anywhere, and only ever INSERTS into creator files (never
deletes a line). Every write is backed up with a .bak-<timestamp>.

It's called the same way the old one was:
    python3 /usr/local/lib/stacks_network_guardian.py
so nothing in the main `stacks` script needs to change.
"""
import os
import sys
import importlib.util

FIX_PATH = "/usr/local/lib/stacks_fix.py"


def _load_fixer():
    if not os.path.isfile(FIX_PATH):
        return None
    try:
        spec = importlib.util.spec_from_file_location("stacks_fix", FIX_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"Guardian: could not load fixer ({e}); skipping safely.")
        return None


def run_guardian():
    sf = _load_fixer()
    if sf is None:
        # Fail safe: do nothing rather than risk corrupting files.
        print("SUCCESS: Guardian idle (fixer unavailable) — no changes made.")
        return

    cfg = sf.load_conf()
    sd = cfg.get("STACKS_DIR", "/srv/stacks/Stacks")
    if not os.path.isdir(sd):
        print("SUCCESS: Guardian idle (stacks dir missing) — no changes made.")
        return

    # Respect the same toggle the fixer uses. If the user turned network/volume
    # auto-define OFF, the guardian stays out of the way entirely.
    if not sf.on(cfg.get("FIX_DEFINE_NETVOL", "1")):
        print("SUCCESS: Guardian disabled via FIX_DEFINE_NETVOL=0 — no changes.")
        return

    # Discover creator files by CONTENT (not hard-coded names).
    creators = sf.discover_creator_files(sd)
    needed_nets, needed_vols = sf.collect_service_refs(sd, creators)

    defined_nets = set().union(*[c["nets"] for c in creators.values()]) if creators else set()
    defined_vols = set().union(*[c["vols"] for c in creators.values()]) if creators else set()

    missing_nets = needed_nets - defined_nets
    missing_vols = needed_vols - defined_vols

    if not (missing_nets or missing_vols):
        print("SUCCESS: Infrastructure synchronized. No drift detected.")
        return

    # Pick smallest creator; if none exist, bootstrap into smallest file overall.
    if creators:
        target_path = min(creators, key=lambda p: creators[p]["size"])
    else:
        target_path = sf.smallest_file_overall(sd)
        if not target_path:
            print("SUCCESS: Guardian idle (no compose files) — no changes made.")
            return

    used = sf.all_used_subnets(creators, cfg.get("FIX_SUBNET_BASE", "10.50"))
    added = sf.add_to_creator(
        target_path, missing_nets, missing_vols,
        cfg.get("FIX_SUBNET_BASE", "10.50"), used, dry_run=False
    )

    if added:
        print(f"SUCCESS: Guardian optimized infrastructure inside "
              f"{os.path.basename(target_path)}")
    else:
        print("SUCCESS: Infrastructure synchronized. No drift detected.")


if __name__ == '__main__':
    run_guardian()
