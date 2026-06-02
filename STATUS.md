# stacks - Capability & Wiring Status
_Last updated: 2026-06-02_

## PHILOSOPHY (do not blur these two commands)
- FIX = applies MY preferences from the config files. Shapes the compose the way I want it
        (enrichment, networks, depends_on policy). Opinionated, intentional.
- REPAIR = does whatever it takes to make the stack START, without changing what fix decided.
        Fixes breakage: bad indentation, YAML errors, missing/corrupt chunks. When a piece is
        broken or missing, pulls that exact piece from a known-good snapshot (taken during a
        stable startup) and injects it back. Preserves fix's choices; only restores what broke.

