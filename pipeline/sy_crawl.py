"""Polite, cached, resumable Square Yards crawler for cities with no usable Magicbricks project list.

usage: python sy_crawl.py list <city>      # list pages -> out/<city>/sy_urls.json (project page addresses)
       python sy_crawl.py projects <city>  # every project page -> out/<city>/mb_projects.json
       python sy_crawl.py show <url>       # fetch one project page and print what was read (for debugging)

<city> needs "squareyards": {"slug": "dehradun"} in data/cities.json.
Rules: robots.txt is checked before every request; one request per second; pages are cached; if the site
answers with a block or error page the crawl stops instead of retrying or working around it.
"""
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.request
import urllib.robotparser

import sy_parse

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "sy"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
BASE = "https://www.squareyards.com"
UA = "Mozilla/5.0 (compatible; flat-finder/0.1; +https://github.com/kairothq/flat-finder)"
DELAY = 1.0
MAX_LIST_PAGES = 150
SEEDS = ("new-launch-projects-in-{slug}", "under-construction-projects-in-{slug}", "affordable-apartment-in-{slug}",
         "ready-to-move-by-best-developers-and-builders-in-{slug}")


class Blocked(Exception):
    pass


_robots = None


def allowed(url):
    global _robots
    if _robots is None:
        _robots = urllib.robotparser.RobotFileParser()
        try:
            _robots.parse(urllib.request.urlopen(urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": UA}), timeout=30)
                          .read().decode("utf-8", "ignore").splitlines())
        except Exception as e:
            sys.exit(f"could not read robots.txt ({e}); not crawling without it")
    return _robots.can_fetch("*", url)


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")
    if f.exists() and f.stat().st_size > 2000:
        return gzip.decompress(f.read_bytes()).decode("utf-8", "ignore")
    if not allowed(url):
        print("  robots.txt disallows", url, flush=True)
        return None
    for attempt in range(2):
        try:
            html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40).read().decode("utf-8", "ignore")
            time.sleep(DELAY)
            if sy_parse.is_blocked(html):
                raise Blocked(f"{url} came back as a block or empty page ({len(html)} bytes); stopping, not working around it")
            f.write_bytes(gzip.compress(html.encode("utf-8"), 9))
            return html
        except Blocked:
            raise
        except Exception as e:
            print("  retry", attempt + 1, url, e, flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def cfg_for(city):
    if city not in CITIES or "squareyards" not in CITIES[city]:
        sys.exit(f'add "squareyards": {{"slug": "<city>"}} to {city} in data/cities.json first')
    return CITIES[city]["squareyards"]["slug"], ROOT / "out" / city


def list_pages(slug):
    return [f"{BASE}/{s.format(slug=slug)}" for s in SEEDS]


def follow_links(html, slug):
    """Other list pages for the same city (zones, localities, builders) linked from a list page."""
    pat = rf'https://www\.squareyards\.com/(?:[a-z0-9\-]*projects[a-z0-9\-]*|affordable-apartment-in)[a-z0-9\-]*{re.escape(slug)}[a-z0-9\-]*(?=["\'<\s#?])'
    return sorted(set(re.findall(pat, html)))


def crawl_list(city):
    slug, out = cfg_for(city)
    todo, seen, urls = list_pages(slug), set(), set()
    while todo and len(seen) < MAX_LIST_PAGES:
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        html = fetch(u)
        if not html:
            continue
        found = sy_parse.project_urls(html, slug)
        urls.update(found)
        for link in follow_links(html, slug):
            if link not in seen and link not in todo:
                todo.append(link)
        print(f"list {len(seen)}: +{len(found)} (total {len(urls)} projects) {u}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sy_urls.json").write_text(json.dumps(sorted(urls), indent=0))
    print("list pages read", len(seen), "project pages found", len(urls))


def crawl_projects(city):
    slug, out = cfg_for(city)
    urls = json.loads((out / "sy_urls.json").read_text())
    target = out / "mb_projects.json"
    if target.exists():
        try:
            old = json.loads(target.read_text())
        except ValueError:
            old = []
        if any(p.get("source") not in ("squareyards", "openstreetmap") for p in old):
            sys.exit(f"{target} holds a Magicbricks crawl; not overwriting it")
    projects, skipped = [], []
    for i, u in enumerate(urls, 1):
        html = fetch(u)
        p = sy_parse.parse_project_page(html, u) if html else None
        if p and p["lat"] and p["lng"]:
            projects.append(p)
        else:
            skipped.append(u)
        if i % 25 == 0 or i == len(urls):
            print(f"project {i}/{len(urls)}: {len(projects)} read, {len(skipped)} skipped", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(projects, indent=0))
    (out / "sy_skipped.json").write_text(json.dumps(skipped, indent=0))
    n = len(projects) or 1
    print(f"written {len(projects)} projects; with RERA {sum(bool(p['rera_id']) for p in projects)}, with unit sizes "
          f"{sum(bool(p['card_units']) for p in projects)}, with a price {sum(bool(p['price_min']) for p in projects)}, "
          f"with amenities {sum(bool(p['amenities']) for p in projects)}, with a developer {sum(bool(p['developer']) for p in projects)}"
          f" (of {n}); skipped {len(skipped)} (see sy_skipped.json)")


def show(url):
    html = fetch(url)
    if not html:
        sys.exit("not fetched")
    blocks = sy_parse.ld_blocks(html)
    print("ld+json blocks:", len(blocks), "| project nodes:", len(sy_parse.project_nodes(blocks)))
    print("nodes:", json.dumps(sy_parse.node_summary(html), indent=1))
    print("raw fields:", json.dumps(sy_parse.raw_fields(html), indent=1))
    print(json.dumps(sy_parse.parse_project_page(html, url), indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "show":
            show(sys.argv[2])
        elif cmd in ("list", "projects"):
            {"list": crawl_list, "projects": crawl_projects}[cmd](sys.argv[2])
        else:
            sys.exit(__doc__)
    except Blocked as e:
        sys.exit(str(e))
