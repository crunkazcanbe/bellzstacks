#!/usr/bin/env python3
"""
stacks regsearch — half-screen registry search TUI
Enter = docker pull the selected image directly
"""

import concurrent.futures
import curses
import json
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (regsearch/2.0)"
TIMEOUT = 15
PAGE_SIZE_PER_REGISTRY = 100


def http_get_json(url, headers=None, timeout=TIMEOUT):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            if not body.strip():
                return {"_error": "empty response"}
            return json.loads(body)
    except json.JSONDecodeError as e:
        return {"_error": f"invalid JSON: {e}"}
    except Exception as e:
        return {"_error": str(e)}


def search_docker_hub(keyword, page, limit):
    url = f"https://hub.docker.com/v2/search/repositories/?query={urllib.parse.quote(keyword)}&page_size={limit}&page={page}"
    data = http_get_json(url)
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("results", []):
        ns = r.get("repo_owner") or "library"
        name = r.get("repo_name", "")
        out.append({
            "name": name, "namespace": ns, "registry": "docker.io",
            "pull": f"{ns}/{name}" if ns != "library" else name,
            "stars": r.get("star_count"), "pulls": r.get("pull_count"),
            "desc": (r.get("short_description") or "").strip(),
            "official": r.get("is_official", False),
            "url": f"https://hub.docker.com/r/{ns}/{name}"
        })
    return out


def search_ghcr(keyword, page, limit):
    url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(keyword)}+packages:>=1&per_page={limit}&page={page}"
    data = http_get_json(url, headers={"Accept": "application/vnd.github+json"})
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("items", []):
        owner = r.get("owner", {}).get("login", "")
        name = r.get("name", "")
        out.append({
            "name": name, "namespace": owner, "registry": "ghcr.io",
            "pull": f"ghcr.io/{owner}/{name}".lower(),
            "stars": r.get("stargazers_count"),
            "desc": (r.get("description") or "").strip(),
            "url": r.get("html_url", "")
        })
    return out


def search_quay(keyword, page, limit):
    url = f"https://quay.io/api/v1/find/repositories?query={urllib.parse.quote(keyword)}&page={page}&includeUsage=true"
    data = http_get_json(url)
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("results", [])[:limit]:
        ns = r.get("namespace", {})
        ns_name = ns.get("name") if isinstance(ns, dict) else (ns or "")
        name = r.get("name", "")
        out.append({
            "name": name, "namespace": ns_name, "registry": "quay.io",
            "pull": f"quay.io/{ns_name}/{name}" if ns_name else name,
            "stars": r.get("popularity"), "pulls": r.get("usage_count"),
            "desc": (r.get("description") or "").strip(),
            "url": f"https://quay.io/repository/{ns_name}/{name}" if ns_name else ""
        })
    return out


def search_lscr(keyword, page, limit):
    url = f"https://hub.docker.com/v2/repositories/linuxserver/?page_size={limit}&page={page}&name={urllib.parse.quote(keyword)}"
    data = http_get_json(url)
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("results", [])[:limit]:
        name = r.get("name", "")
        out.append({
            "name": name, "namespace": "linuxserver", "registry": "lscr.io",
            "pull": f"lscr.io/linuxserver/{name}",
            "stars": r.get("star_count"), "pulls": r.get("pull_count"),
            "desc": (r.get("description") or "").strip(),
            "url": f"https://hub.docker.com/r/linuxserver/{name}"
        })
    return out


def search_bitnami(keyword, page, limit):
    url = f"https://hub.docker.com/v2/repositories/bitnami/?page_size={limit}&page={page}&name={urllib.parse.quote(keyword)}"
    data = http_get_json(url)
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("results", [])[:limit]:
        name = r.get("name", "")
        out.append({
            "name": name, "namespace": "bitnami", "registry": "docker.io/bitnami",
            "pull": f"bitnami/{name}",
            "stars": r.get("star_count"), "pulls": r.get("pull_count"),
            "desc": (r.get("description") or "").strip(),
            "url": f"https://hub.docker.com/r/bitnami/{name}"
        })
    return out


def search_gitlab(keyword, page, limit):
    url = f"https://gitlab.com/api/v4/projects?search={urllib.parse.quote(keyword)}&per_page={limit}&page={page}&order_by=stars"
    data = http_get_json(url)
    if isinstance(data, dict) and "_error" in data:
        return [{"_error": data["_error"]}]
    if not isinstance(data, list):
        return [{"_error": "gitlab returned non-list"}]
    out = []
    for r in data[:limit]:
        path = r.get("path_with_namespace", "")
        if not path:
            continue
        out.append({
            "name": r.get("path", ""), "namespace": r.get("namespace", {}).get("path", ""),
            "registry": "registry.gitlab.com",
            "pull": f"registry.gitlab.com/{path}",
            "stars": r.get("star_count"),
            "desc": (r.get("description") or "").strip(),
            "url": r.get("web_url", "")
        })
    return out


def search_mcr(keyword, page, limit):
    cat = http_get_json("https://mcr.microsoft.com/v2/_catalog?n=10000")
    if "_error" in cat:
        return [{"_error": cat["_error"]}]
    matches = [r for r in cat.get("repositories", []) if keyword.lower() in r.lower()]
    start = (page - 1) * limit
    out = []
    for repo in matches[start:start + limit]:
        out.append({
            "name": repo.split("/")[-1],
            "namespace": "/".join(repo.split("/")[:-1]) or "",
            "registry": "mcr.microsoft.com",
            "pull": f"mcr.microsoft.com/{repo}",
            "desc": "Microsoft Container Registry image",
        })
    return out


def search_artifacthub(keyword, page, limit):
    offset = (page - 1) * limit
    url = f"https://artifacthub.io/api/v1/packages/search?ts_query_web={urllib.parse.quote(keyword)}&limit={limit}&offset={offset}"
    data = http_get_json(url)
    if "_error" in data:
        return [{"_error": data["_error"]}]
    out = []
    for r in data.get("packages", [])[:limit]:
        repo = r.get("repository", {})
        kind = repo.get("kind_name", "helm")
        name = r.get("name", "")
        repo_name = repo.get("name", "")
        pull = f"helm install {name} {repo_name}/{name}" if kind == "helm" else f"docker pull {repo_name}/{name}"
        out.append({
            "name": name, "namespace": repo_name,
            "registry": f"artifacthub:{kind}",
            "pull": pull,
            "stars": r.get("stars"),
            "desc": (r.get("description") or "").strip(),
            "url": f"https://artifacthub.io/packages/{kind}/{repo_name}/{name}"
        })
    return out


def search_aws_ecr(keyword, page, limit):
    url = "https://gallery.ecr.aws/api/search"
    body = json.dumps({
        "operationName": "searchRepositoryCatalogData",
        "variables": {"searchTerm": keyword, "page": page, "size": limit, "sortBy": "POPULARITY"},
        "query": "query searchRepositoryCatalogData($searchTerm: String, $page: Int, $size: Int, $sortBy: String) { searchRepositoryCatalogData(searchTerm: $searchTerm, page: $page, size: $size, sortBy: $sortBy) { repositories { primaryRegistryAliasName repositoryName shortDescription downloadCount } } }"
    }).encode()
    try:
        req = urllib.request.Request(url, data=body,
            headers={"User-Agent": UA, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return [{"_error": f"ecr: {str(e)[:40]}"}]
    out = []
    repos = data.get("data", {}).get("searchRepositoryCatalogData", {}).get("repositories", []) or []
    for r in repos[:limit]:
        ns = r.get("primaryRegistryAliasName") or ""
        name = r.get("repositoryName") or ""
        if not name:
            continue
        out.append({
            "name": name, "namespace": ns, "registry": "public.ecr.aws",
            "pull": f"public.ecr.aws/{ns}/{name}" if ns else name,
            "pulls": r.get("downloadCount"),
            "desc": (r.get("shortDescription") or "").strip(),
        })
    return out


REGISTRIES = {
    "Docker Hub":       search_docker_hub,
    "GitHub (ghcr.io)": search_ghcr,
    "Quay.io":          search_quay,
    "GitLab Registry":  search_gitlab,
    "AWS Public ECR":   search_aws_ecr,
    "LinuxServer.io":   search_lscr,
    "Bitnami":          search_bitnami,
    "Microsoft MCR":    search_mcr,
    "ArtifactHub":      search_artifacthub,
}


def search_all(keyword, page, limit_per_reg):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(REGISTRIES)) as ex:
        futures = {ex.submit(fn, keyword, page, limit_per_reg): name for name, fn in REGISTRIES.items()}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = [{"_error": str(e)}]
    return results


def human_num(n):
    if n is None: return ""
    try: n = int(n)
    except: return str(n)
    for u in ["", "K", "M", "B"]:
        if abs(n) < 1000: return f"{n}{u}"
        n /= 1000
    return f"{n:.1f}T"


def trunc(s, n):
    if not s: return ""
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


def docker_pull_inline(pull_cmd, stdscr, panel_top, panel_h, w):
    """Run docker pull and show live output inside the panel."""
    full_h, full_w = stdscr.getmaxyx()
    image = pull_cmd.replace("docker pull ", "").strip()

    # Clear panel
    for row in range(panel_top, full_h):
        try:
            stdscr.addstr(row, 0, " " * (w - 1))
        except curses.error:
            pass

    try:
        stdscr.addnstr(panel_top, 0,
            f" ⬇  Pulling: {image} ".ljust(w - 1), w - 1,
            curses.color_pair(7) | curses.A_BOLD)
    except curses.error:
        pass

    stdscr.refresh()
    curses.endwin()

    # Run docker pull in foreground so output streams normally
    print(f"\n\033[1;35m⬇  docker pull {image}\033[0m")
    ret = subprocess.call(["docker", "pull", image])
    if ret == 0:
        print(f"\033[1;32m✔  Pull complete: {image}\033[0m")
    else:
        print(f"\033[1;31m✘  Pull failed (exit {ret})\033[0m")
    print("\n\033[1;36mPress Enter to return to search...\033[0m")
    input()

    # Re-init curses
    stdscr = curses.initscr()
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_MAGENTA, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(8, curses.COLOR_WHITE, -1)
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    return stdscr


class TUI:
    def __init__(self, stdscr, keyword="", select_mode=False):
        self.stdscr = stdscr
        self.keyword = keyword
        self.select_mode = select_mode
        self.page = 1
        self.results = []
        self.filtered = []
        self.cursor = 0
        self.scroll = 0
        self.registry_filter = "ALL"
        self.status_msg = "[/]search  [↑↓]nav  [n/p]page  [f]filter  [i]info  [Enter]PULL  [q]quit"
        self.loading = False

        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_BLUE, -1)
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(8, curses.COLOR_WHITE, -1)

        if keyword:
            self.do_search()

    def get_panel(self):
        full_h, full_w = self.stdscr.getmaxyx()
        panel_h = full_h
        panel_top = 0
        return panel_top, panel_h, full_w

    def do_search(self):
        if not self.keyword:
            return
        self.loading = True
        self.draw()
        self.stdscr.refresh()
        results_by_reg = search_all(self.keyword, self.page, PAGE_SIZE_PER_REGISTRY)
        self.results = []
        for reg_name, items in results_by_reg.items():
            for item in items:
                if "_error" in item:
                    continue
                item["_source"] = reg_name
                self.results.append(item)
        self.apply_filter()
        self.cursor = 0
        self.scroll = 0
        self.loading = False
        self.status_msg = f"[/]search  [↑↓]nav  [n/p]page  [f]filter  [i]info  [Enter]PULL  [q]quit  │  {len(self.results)} results p{self.page}"

    def apply_filter(self):
        if self.registry_filter == "ALL":
            self.filtered = list(self.results)
        else:
            self.filtered = [r for r in self.results if r.get("_source") == self.registry_filter]

    def prompt(self, prompt_text):
        full_h, full_w = self.stdscr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        try:
            self.stdscr.addstr(full_h - 1, 0, " " * (full_w - 1))
            self.stdscr.addstr(full_h - 1, 0, prompt_text)
        except curses.error:
            pass
        self.stdscr.refresh()
        try:
            s = self.stdscr.getstr(full_h - 1, len(prompt_text), 100).decode("utf-8", errors="replace")
        except KeyboardInterrupt:
            s = ""
        curses.noecho()
        curses.curs_set(0)
        return s.strip()

    def draw(self):
        full_h, full_w = self.stdscr.getmaxyx()
        panel_top, panel_h, w = self.get_panel()

        # Only clear the bottom half — leave top alone
        for row in range(panel_top, full_h):
            try:
                self.stdscr.addstr(row, 0, " " * (w - 1))
            except curses.error:
                pass

        # Separator
        try:
            self.stdscr.addnstr(panel_top, 0,
                f"─── 🔍 regsearch: '{self.keyword}' │ page {self.page} │ {self.registry_filter} ".ljust(w - 1),
                w - 1, curses.color_pair(3) | curses.A_BOLD)
        except curses.error:
            pass

        if self.loading:
            try:
                self.stdscr.addnstr(panel_top + panel_h // 2, max(0, (w - 16) // 2),
                    "  Searching...  ", w - 1, curses.color_pair(3) | curses.A_BOLD)
            except curses.error:
                pass
            return

        body_start = panel_top + 1
        body_height = panel_h - 3  # sep + desc + status

        if not self.filtered:
            try:
                self.stdscr.addnstr(body_start, 2,
                    "No results. Type / to search.", w - 3, curses.color_pair(3))
            except curses.error:
                pass
        else:
            if self.cursor < self.scroll:
                self.scroll = self.cursor
            elif self.cursor >= self.scroll + body_height:
                self.scroll = self.cursor - body_height + 1

            for i in range(body_height):
                idx = self.scroll + i
                if idx >= len(self.filtered):
                    break
                r = self.filtered[idx]
                y = body_start + i
                selected = (idx == self.cursor)
                line = f" {r.get('pull', '')}"
                stats = []
                if r.get("stars"):
                    stats.append(f"★{human_num(r['stars'])}")
                if r.get("pulls"):
                    stats.append(f"↓{human_num(r['pulls'])}")
                stats_str = " ".join(stats)
                source = r.get("_source", "")
                full = f"{line:<{max(20, w - len(stats_str) - len(source) - 8)}} {stats_str} [{source}]"
                try:
                    if selected:
                        self.stdscr.addnstr(y, 0, full.ljust(w - 1), w - 1,
                            curses.color_pair(7) | curses.A_BOLD)
                    else:
                        self.stdscr.addnstr(y, 0, full, w - 1, curses.color_pair(1))
                except curses.error:
                    pass

        # Desc line
        desc_y = full_h - 2
        if self.filtered and 0 <= self.cursor < len(self.filtered):
            r = self.filtered[self.cursor]
            desc = trunc(r.get("desc", ""), w - 4)
            try:
                self.stdscr.addnstr(desc_y, 0, f" {desc}", w - 1, curses.color_pair(2))
            except curses.error:
                pass

        # Status
        try:
            self.stdscr.addnstr(full_h - 1, 0,
                self.status_msg.ljust(w - 1), w - 1, curses.color_pair(7))
        except curses.error:
            pass

    def show_info(self, r):
        full_h, full_w = self.stdscr.getmaxyx()
        panel_top, panel_h, w = self.get_panel()

        full_desc = r.get("desc", "")
        if "docker.io" in r.get("registry", "") or r.get("registry") == "lscr.io":
            ns = r.get('namespace', 'library') or 'library'
            url = f"https://hub.docker.com/v2/repositories/{ns}/{r['name']}/"
            try:
                data = http_get_json(url, timeout=3)
                if "_error" not in data:
                    full_desc = data.get("full_description") or data.get("description") or full_desc
            except:
                pass

        lines = [
            f"Name:     {r.get('name')}",
            f"Registry: {r.get('registry')}",
            f"Pull:     {r.get('pull')}",
        ]
        stats = []
        if r.get('stars'): stats.append(f"Stars: {r['stars']}")
        if r.get('pulls'): stats.append(f"Pulls: {r['pulls']}")
        if stats: lines.append(f"Stats:    {', '.join(stats)}")
        if r.get("official"): lines.append("Official: Yes")
        if r.get("url"): lines.append(f"URL:      {r.get('url')}")
        lines += ["", "Description:", "─" * 20]
        for para in full_desc.split('\n'):
            wrapped = textwrap.wrap(para, width=w - 6)
            lines.extend(wrapped if wrapped else [""])

        scroll_idx = 0
        while True:
            for row in range(panel_top, full_h):
                try:
                    self.stdscr.addstr(row, 0, " " * (w - 1))
                except curses.error:
                    pass
            try:
                self.stdscr.addnstr(panel_top, 0,
                    " Image Details ".center(w - 1), w - 1,
                    curses.color_pair(7) | curses.A_BOLD)
            except curses.error:
                pass
            for i in range(panel_h - 2):
                curr_idx = scroll_idx + i
                if curr_idx < len(lines):
                    try:
                        self.stdscr.addnstr(panel_top + 1 + i, 2,
                            lines[curr_idx][:w - 4], w - 4, curses.color_pair(8))
                    except curses.error:
                        pass
            try:
                self.stdscr.addnstr(full_h - 1, 0,
                    " [↑/↓] scroll  [q/ESC] close ".ljust(w - 1), w - 1,
                    curses.color_pair(7))
            except curses.error:
                pass
            self.stdscr.refresh()
            k = self.stdscr.getch()
            if k in (curses.KEY_UP, ord('k')):
                scroll_idx = max(0, scroll_idx - 1)
            elif k in (curses.KEY_DOWN, ord('j')):
                scroll_idx = min(max(0, len(lines) - (panel_h - 2)), scroll_idx + 1)
            elif k in (ord('q'), 27, ord('i')):
                break

    def filter_menu(self):
        opts = ["ALL"] + sorted(set(r.get("_source", "") for r in self.results))
        full_h, full_w = self.stdscr.getmaxyx()
        panel_top, panel_h, w = self.get_panel()
        sel = 0
        while True:
            for row in range(panel_top, full_h):
                try:
                    self.stdscr.addstr(row, 0, " " * (w - 1))
                except curses.error:
                    pass
            try:
                self.stdscr.addnstr(panel_top, 0,
                    " Filter by Registry ".center(w - 1), w - 1,
                    curses.color_pair(7) | curses.A_BOLD)
            except curses.error:
                pass
            for i, o in enumerate(opts):
                y = panel_top + 2 + i
                if y >= full_h - 2:
                    break
                try:
                    if i == sel:
                        self.stdscr.addnstr(y, 2, f"▶ {o}".ljust(w - 4), w - 4,
                            curses.color_pair(7) | curses.A_BOLD)
                    else:
                        self.stdscr.addnstr(y, 2, f"  {o}", w - 4, curses.color_pair(1))
                except curses.error:
                    pass
            try:
                self.stdscr.addnstr(full_h - 1, 0,
                    " [↑/↓] navigate  [Enter] select  [q] cancel ".ljust(w - 1), w - 1,
                    curses.color_pair(7))
            except curses.error:
                pass
            self.stdscr.refresh()
            k = self.stdscr.getch()
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(opts)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(opts)
            elif k in (10, 13):
                self.registry_filter = opts[sel]
                self.apply_filter()
                self.cursor = 0
                self.scroll = 0
                return
            elif k in (ord("q"), 27):
                return

    def run(self):
        while True:
            self.draw()
            self.stdscr.refresh()
            k = self.stdscr.getch()
            if k in (ord("q"), 27):
                break
            elif k == ord("/"):
                kw = self.prompt(" Search: ")
                if kw:
                    self.keyword = kw
                    self.page = 1
                    self.registry_filter = "ALL"
                    self.do_search()
            elif k in (ord('n'), curses.KEY_RIGHT):
                if self.keyword:
                    self.page += 1
                    self.do_search()
            elif k in (ord('p'), curses.KEY_LEFT):
                if self.keyword and self.page > 1:
                    self.page -= 1
                    self.do_search()
            elif k in [ord(str(num)) for num in range(10)]:
                p_num = self.prompt(' Go to Page Number: ', initial=chr(k))
                if p_num and p_num.isdigit():
                    target_p = int(p_num)
                    if target_p > 0:
                        self.page = target_p
                        self.do_search()
            elif k == ord("f"):
                if self.results:
                    self.filter_menu()
            elif k == ord("i"):
                if self.filtered and 0 <= self.cursor < len(self.filtered):
                    self.show_info(self.filtered[self.cursor])
            elif k in (curses.KEY_UP, ord("k")):
                if self.filtered:
                    self.cursor = max(0, self.cursor - 1)
            elif k in (curses.KEY_DOWN, ord("j")):
                if self.filtered:
                    self.cursor = min(len(self.filtered) - 1, self.cursor + 1)
            elif k == curses.KEY_PPAGE:
                if self.filtered:
                    self.cursor = max(0, self.cursor - 10)
            elif k == curses.KEY_NPAGE:
                if self.filtered:
                    self.cursor = min(len(self.filtered) - 1, self.cursor + 10)
            elif k in (10, 13):
                # ENTER = docker pull OR select mode
                if self.filtered and 0 <= self.cursor < len(self.filtered):
                    r = self.filtered[self.cursor]
                    pull_cmd = r.get('pull', '')
                    if pull_cmd and "helm install" not in pull_cmd:
                        if self.select_mode:
                            # Write selected image to temp file and exit
                            open("/tmp/stacks_build_selected","w").write(pull_cmd)
                            return
                        _, panel_h, w = self.get_panel()
                        full_h, _ = self.stdscr.getmaxyx()
                        self.stdscr = docker_pull_inline(
                            f"docker pull {pull_cmd}",
                            self.stdscr,
                            full_h - panel_h, panel_h, w
                        )
                        self.status_msg = f"✔ Pulled: {pull_cmd}  │  [/]search [↑↓]nav [q]quit"
                    else:
                        self.status_msg = f"Helm: {pull_cmd}"
            elif k == ord("g"):
                self.cursor = 0
            elif k == ord("G"):
                if self.filtered:
                    self.cursor = len(self.filtered) - 1


def main():
    import argparse
    p = argparse.ArgumentParser(prog="stacks regsearch")
    p.add_argument("keyword", nargs="?", default="")
    p.add_argument("--select", action="store_true", help="Select mode: write image to file instead of pulling")
    args = p.parse_args()
    curses.wrapper(lambda s: TUI(s, args.keyword, select_mode=args.select).run())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
