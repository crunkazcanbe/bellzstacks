cat > /home/user/stacks/README.md << 'EOF'
# 🐳 Stacks

> A powerful Docker stack management CLI and TUI — built entirely with AI assistance (Claude by Anthropic).



![Platform](https://img.shields.io/badge/platform-Linux-blue)
![Shell](https://img.shields.io/badge/shell-bash%20%2F%20python3-green)
![License](https://img.shields.io/badge/license-MIT-purple)



---

## What is Stacks?

Stacks is a full-featured Docker Compose stack manager built for homelabs and self-hosted infrastructure. It started as a simple bash script and grew into a 500KB+ system with a full curses TUI, registry search, auto-repair, dynamic config generation, and more.

**Built entirely through AI-assisted development with Claude (Anthropic)** — every feature, fix, and refactor was designed and implemented in collaboration with Claude over dozens of sessions.

---

## Features

### CLI (`stacks` command)
- `stacks up / down / start / stop / restart` — manage individual stacks or all at once
- `stacks fix` — auto-fix compose files (healthchecks, networks, IPs, labels)
- `stacks repair` — deep repair of corrupt YAML, bad anchors, duplicate keys
- `stacks build` — interactive service scaffolder with Docker Hub search
- `stacks scale` — toggle Sablier zero-scale on/off per stack or container
- `stacks proxy` — toggle Traefik routing on/off
- `stacks art` — inject/strip ASCII art headers into compose files
- `stacks gen` — generate Traefik dynamic configs from compose files
- `stacks snapshot` — snapshot stack state before changes
- `stacks search` — search 10+ container registries
- `stacks describe` — manage per-stack service descriptions
- `stacks backup` — backup stack configs

### TUI (`stacks menu`)
A full curses-based terminal UI with 8 tabs:

| Tab | Features |
|-----|----------|
| **Containers** | Live list with memory usage, image size, start/stop/restart/inspect |
| **Stacks** | All stacks with service count, file size, total image size, RAM usage |
| **Logs** | Browse all stacks log files with sizes |
| **Dynamics** | Traefik dynamic configs — edit, repair, regenerate, art inject |
| **Art** | Inject/strip ASCII art, manage art config |
| **Backup** | Run backups, view logs, restore |
| **Build** | Full interactive build wizard with multi-registry image search |
| **Configs** | Edit all config files including per-stack descriptions |

### Build Wizard
- Search 10+ registries (Docker Hub, GitHub, Quay, GitLab, LinuxServer, Bitnami, MCR, and more)
- Left/right to switch registries, letter filter, inline search
- Auto-detects next available IP
- Reads `build.conf` for all scaffold options (CPU, memory, blkio, ulimits, logging, DNS)
- Auto-writes to per-stack descriptions file
- Auto-syncs `all_services.txt`
- Back navigation with ESC

### Registry Search
- 10+ registries searched in parallel
- Alphabet filter, inline `/` search
- Shows download count, stars, local image size
- Filters out helm charts automatically

### Auto-Repair System
- Fixes corrupt YAML anchors
- Repairs duplicate labels, broken healthchecks
- Fixes network priority, sablier groups
- Repairs Traefik dynamic configs
- Many more things i cant remember

---

## Installation

```bash
git clone https://github.com/crunkazcanbe/stacks.git
cd stacks
sudo bash install.sh
