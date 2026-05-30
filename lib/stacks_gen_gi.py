#!/usr/bin/env python3
import sys, os, re

conf_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/global_inject.conf"
stacks_dir = sys.argv[2] if len(sys.argv) > 2 else "/srv/stacks/Stacks"
ncores = os.cpu_count() or 8

# Scan stacks dir for unique prefixes
prefixes = set()
if os.path.isdir(stacks_dir):
    for f in os.listdir(stacks_dir):
        if f.endswith(".yml") or f.endswith(".yaml"):
            name = f.replace(".yml","").replace(".yaml","")
            m = re.match(r"^([a-zA-Z]+)", name)
            if m:
                prefixes.add(m.group(1))

prefixes = sorted(prefixes)
usable = max(ncores // 2, 4)

# Assign cores
heavy_prefixes = {"ai", "ml", "llm"}
core_map = {}
regular = [p for p in prefixes if p not in heavy_prefixes]
for i, p in enumerate(regular):
    core_map[p] = str(i % usable)
for p in prefixes:
    if p in heavy_prefixes:
        core_map[p] = f"0-{ncores-1}"

lines = [
    "# ==============================================================================",
    "# global_inject.conf — Keys injected into every service by stacks fix",
    "# Auto-generated on first run. Edit freely.",
    "# Values: 0=disabled, 1=add-only, force=always override",
    "# _FORCE=1 forces individual key. FORCE_ALL=1 forces everything.",
    "# Anchor keys -> x-common-caps block. Service keys -> each service.",
    "# ==============================================================================",
    "",
    "FORCE_ALL=0",
    "",
    "# -- Stop behavior (-> anchor) ------------------------------------------------",
    "INJECT_STOP_GRACE=1",
    "INJECT_STOP_GRACE_FORCE=0",
    "STOP_GRACE_PERIOD=120s",
    "STOP_SIGNAL=SIGTERM",
    "",
    "# -- Logging (-> anchor) ------------------------------------------------------",
    "INJECT_LOGGING=1",
    "INJECT_LOGGING_FORCE=0",
    "LOGGING_DRIVER=json-file",
    "LOGGING_MAX_SIZE=50m",
    "LOGGING_MAX_FILE=5",
    "",
    "# -- Restart policy (-> anchor) -----------------------------------------------",
    "INJECT_RESTART=0",
    "INJECT_RESTART_FORCE=0",
    "RESTART_POLICY=unless-stopped",
    "",
    "# -- Resource limits (-> each service) ----------------------------------------",
    "INJECT_DEPLOY=0",
    "INJECT_DEPLOY_FORCE=0",
    "DEPLOY_MEMORY_LIMIT=2G",
    "DEPLOY_CPU_LIMIT=0.20",
    "DEPLOY_MEMORY_RESERVATION=256M",
    "",
    "# -- Block IO (-> each service) -----------------------------------------------",
    "INJECT_BLKIO=0",
    "INJECT_BLKIO_FORCE=0",
    "BLKIO_WEIGHT=500",
    "BLKIO_READ_BPS=750mb",
    "BLKIO_WRITE_BPS=750mb",
    "",
    "# -- ulimits (-> each service) ------------------------------------------------",
    "INJECT_ULIMITS=0",
    "INJECT_ULIMITS_FORCE=0",
    "ULIMIT_NOFILE_SOFT=65535",
    "ULIMIT_NOFILE_HARD=65535",
    "ULIMIT_NPROC=65535",
    "",
    f"# -- CPU core pinning (-> each service) --------------------------------------",
    f"# Detected {len(prefixes)} stack prefix(es): {', '.join(prefixes)}",
    f"# System has {ncores} cores. Containers use 0-{usable-1}, host keeps {usable}-{ncores-1}",
    "INJECT_CPUSET=0",
    "INJECT_CPUSET_FORCE=0",
    "CPU_SHARES_default=256",
    "CPU_SHARES_heavy=4096",
    f"CPUSET_default=0-{usable-1}",
]

for p, core in core_map.items():
    lines.append(f"CPUSET_{p}={core}")

lines += [
    "# Container names that get all cores (space-separated)",
    "CPUSET_heavy_containers=",
    "",
    "# -- Custom YAML injected into x-common-caps anchor --------------------------",
    "[custom_anchor]",
    "[/custom_anchor]",
    "",
    "# -- Custom YAML injected into every service ----------------------------------",
    "[custom_service]",
    "[/custom_service]",
]

os.makedirs(os.path.dirname(conf_path), exist_ok=True)
open(conf_path, "w").write("\n".join(lines) + "\n")
print(f"Generated {conf_path} with {len(prefixes)} prefixes: {', '.join(prefixes)}")
