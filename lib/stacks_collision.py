#!/usr/bin/env python3
"""
stacks_collision.py — IP and port collision detection
"""
import os, re, glob

STACKS_DIR = "/srv/stacks/Stacks"
CONF_FILE  = os.path.expanduser("~/.config/stacks/stacks.conf")

def load_conf():
    cfg = {
        "IP_RANGE_START": "192.168.1.200",
        "IP_RANGE_END":   "192.168.1.253",
        "IP_BLACKLIST":   "192.168.1.1,192.168.1.114,192.168.1.151",
        "IP_WHITELIST":   "",
        "PORT_BLACKLIST": "22,80,443,3306,5432,6379,27017",
    }
    try:
        for line in open(CONF_FILE):
            l = line.strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"')
    except: pass
    return cfg

def scan_all_ips():
    """Return {ip: [(stack, container)]} for all stacks."""
    ip_map = {}
    for fpath in sorted(glob.glob(f"{STACKS_DIR}/*.yml")):
        stack = os.path.basename(fpath).replace(".yml","")
        try:
            content = open(fpath).read()
            # Find container_name + ipv4_address pairs
            services = re.findall(
                r'container_name:\s*(\S+).*?ipv4_address:\s*([\d.]+)',
                content, re.DOTALL
            )
            for cname, ip in services:
                if ip not in ip_map:
                    ip_map[ip] = []
                ip_map[ip].append((stack, cname))
        except: pass
    return ip_map

def scan_all_ports():
    """Return {port: [(stack, container)]} for all stacks."""
    port_map = {}
    for fpath in sorted(glob.glob(f"{STACKS_DIR}/*.yml")):
        stack = os.path.basename(fpath).replace(".yml","")
        try:
            content = open(fpath).read()
            # Find container_name + port mappings
            blocks = re.findall(
                r'container_name:\s*(\S+)(.*?)(?=\n  [a-zA-Z]|\Z)',
                content, re.DOTALL
            )
            for cname, block in blocks:
                ports = re.findall(r'[\d.]+:(\d+):\d+', block)
                for port in ports:
                    if port not in port_map:
                        port_map[port] = []
                    port_map[port].append((stack, cname))
        except: pass
    return port_map

def get_collisions():
    """Return lists of IP and port collisions."""
    ip_map = scan_all_ips()
    port_map = scan_all_ports()
    cfg = load_conf()

    blacklist_ips = set(cfg["IP_BLACKLIST"].split(","))
    blacklist_ports = set(cfg["PORT_BLACKLIST"].split(","))

    ip_collisions = []
    for ip, owners in ip_map.items():
        if len(owners) > 1:
            ip_collisions.append({"ip": ip, "owners": owners, "type": "duplicate"})
        elif ip in blacklist_ips:
            ip_collisions.append({"ip": ip, "owners": owners, "type": "blacklisted"})

    port_collisions = []
    for port, owners in port_map.items():
        if len(owners) > 1:
            port_collisions.append({"port": port, "owners": owners, "type": "duplicate"})
        elif port in blacklist_ports:
            port_collisions.append({"port": port, "owners": owners, "type": "blacklisted"})

    return ip_collisions, port_collisions

def get_next_available_ip():
    """Get next available IP respecting range, blacklist, whitelist."""
    cfg = load_conf()
    ip_map = scan_all_ips()
    used = set(ip_map.keys())
    blacklist = set(cfg["IP_BLACKLIST"].split(","))
    whitelist = [x.strip() for x in cfg["IP_WHITELIST"].split(",") if x.strip()]

    if whitelist:
        for ip in whitelist:
            if ip not in used and ip not in blacklist:
                return ip
        return None

    # Use range
    try:
        start = int(cfg["IP_RANGE_START"].split(".")[-1])
        end   = int(cfg["IP_RANGE_END"].split(".")[-1])
        prefix = ".".join(cfg["IP_RANGE_START"].split(".")[:3])
        for i in range(start, end+1):
            ip = f"{prefix}.{i}"
            if ip not in used and ip not in blacklist:
                return ip
    except: pass
    return None

if __name__ == "__main__":
    ip_col, port_col = get_collisions()
    print(f"IP collisions:   {len(ip_col)}")
    for c in ip_col:
        print(f"  {c['type']:12} {c['ip']:18} {c['owners']}")
    print(f"Port collisions: {len(port_col)}")
    for c in port_col:
        print(f"  {c['type']:12} {c['port']:8} {c['owners']}")
    print(f"\nNext available IP: {get_next_available_ip()}")
