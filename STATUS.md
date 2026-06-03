# stacks status — 2026-06-03

## DONE & committed (262d7bf)
- Family detection fixed (NON_FAMILY_ROOTS: open/agent/cloudflared/minecraft/pritunl/tailscale/provisioner)
- Loner rename collapses underscores (open_webui -> openwebui, etc.)
- postgres_db -> openwebui_db
- Domain normalization: container domainname -> <name>.example.com (FIX_NORMALIZE_DOMAINS), blacklist example.org (netbird)
- stacks fix = ZERO reverts. 4 root causes fixed: stale positions, common-caps double-merge, set_networks_authoritative skips network_mode, orphan-volume stripper keeps external:true
- IP collision auto-move gated behind IP_COLLISION_AUTOFIX (default off)
- stacks fix loading bar: single logo, art-filtered, shows current stack

## DONE this session (2026-06-03)
- NEW lib/stacks_fix_dynamic.py: reconciles dynamic Traefik configs against real container_names.
  Skips IP backends, auto-fixes separator-variant drift, REPORTS orphans (never deletes). .bak-dynfix backups.
- Dynamics wired into the dispatcher:
  - stacks dynamics [name...] fix          -> reconcile names
  - stacks dynamics [name...] repair        -> structural (stacks_repair_dynamic.py, was menu-only)
  - stacks fix                              -> now fixes compose AND dynamics (FIX_DYNAMICS toggle, default 1)
  - stacks up <stack> fix / repair          -> per-stack reconciles + repairs its matching dynamic
  - 'dynamics'/'dyn' keyword sets DO_DYNAMICS
  - TUI menu Fix buttons call `stacks fix`, so they inherit dynamics automatically (no menu change needed)
- info now shows SEPARATE labeled 20-line logs, stacked, no dup: Fix / Repair / Dynamics / Up.
  Per-step logs FIXSTEP_LOG/REPAIRSTEP_LOG/DYNSTEP_LOG; shared _log_tail helper.
- Fixed blank action-line in fix bar: python3 -u (was block-buffering through the pipe).
- Fixed config leak: _CONF_DIR was used before it was set -> options dumped to /stacks.conf (root); reordered, deleted junk.
- PATH gotcha: ~/bin/stacks was a stale May-29 copy shadowing /usr/local/bin/stacks; now a symlink to it.

## NEXT (not done)
- DB auto-naming: detect app that owns each DB, rename to <app>_db. NOTE: apps connect by IP (@192.168.1.x:5432) NOT container name.
- Convert connection strings IP -> container name (needs shared networks; verify first)
- 49 orphan refs in dynamics (bookstack-db, your-spotify-*, komodo-mongo, etc.) reported by `stacks dynamics fix` — decide remove vs remap.
- Optionally split repair into its own log in standalone `stacks fix` (currently inside fix log; already split in up/dynamics paths).

## STATE
- 30 stack files VALID. Renames applied to stacks + dynamics. Code at github.com/crunkazcanbe/stacks
