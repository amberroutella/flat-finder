"""Parse Square Yards project pages from their schema.org JSON-LD (and, for unit sizes, the page text).

Square Yards embeds one ApartmentComplex node per project: name, url, address, geo, a RERA identifier,
additionalProperty rows (status, type, unit configuration, land area), an AggregateOffer price and floor plans.
Everything here is defensive: a field that is missing or in an unexpected shape is left out, never guessed.
"""
import json
import re

LD = re.compile(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', re.S | re.I)
PROJECT_URL = r'https://www\.squareyards\.com/{slug}-residential-property/[a-z0-9\-]+/\d+/project'
UNIT_TEXT = re.compile(r'(\d(?:\.\d)?)\s*BHK[^<>"{}\n]{0,40}?-\s*([\d,]+(?:\.\d+)?)\s*sq\.?\s*ft', re.I)
BLOCK_TITLES = ("security alert", "access denied", "we'll be back soon", "just a moment", "attention required")

# Magicbricks property-type codes that the rest of the pipeline already understands
KIND_CODE = {"apartment": "10002", "flat": "10002", "penthouse": "10002", "studio": "10002", "builder floor": "10003",
             "villa": "10017", "house": "10017", "plot": "10000", "land": "10000"}


def ld_blocks(html):
    out = []
    for m in LD.finditer(html):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return out


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def is_blocked(html):
    t = re.search(r"<title>([^<]*)", html or "", re.I)
    return len(html or "") < 20_000 or bool(t and any(b in t.group(1).lower() for b in BLOCK_TITLES))


def project_urls(html, slug):
    return sorted(set(re.findall(PROJECT_URL.format(slug=re.escape(slug)), html)))


def _types(n):
    t = n.get("@type")
    return [t] if isinstance(t, str) else list(t or [])


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _name(v):
    if isinstance(v, dict):
        return v.get("name")
    if isinstance(v, list):
        return next((_name(x) for x in v if _name(x)), None)
    return v if isinstance(v, str) else None


def project_nodes(blocks):
    """ApartmentComplex-like nodes that carry a project id in their url, with the geo that precedes them if needed."""
    nodes = []
    for n in walk(blocks):
        url = n.get("url") or ""
        if re.search(r"/\d+/project/?$", url) and n.get("name") and any(
                t in ("ApartmentComplex", "Residence", "Accommodation", "Place", "Product", "RealEstateListing") for t in _types(n)):
            nodes.append(n)
    return nodes


def parse_node(n, html_text=""):
    url = n["url"]
    pid = re.search(r"/(\d+)/project", url).group(1)
    props = {}
    for p in n.get("additionalProperty") or []:
        if isinstance(p, dict) and p.get("name"):
            props[str(p["name"]).strip().lower()] = p
    geo = n.get("geo") or {}
    street = ((n.get("address") or {}).get("streetAddress") or "").strip()
    locality = re.sub(r",?\s*Dehradun.*$", "", street, flags=re.I).strip(" ,") or street or None
    rera = next((i.get("value") for i in (n.get("identifier") or []) if isinstance(i, dict) and i.get("propertyID") == "RERA"), None)

    def prop(*keys):
        for k, p in props.items():
            if any(w in k for w in keys):
                return p
        return None

    cfg = (prop("unit configuration") or {}).get("value")
    ptype = (prop("property type") or {}).get("value")
    area = prop("total land area")
    acres = _num(area.get("value")) if area and "ac" in str(area.get("unitCode") or area.get("unitText") or "").lower() else None
    units = _num((prop("number of units", "total units") or {}).get("value"))
    towers = _num((prop("number of towers", "total towers") or {}).get("value"))
    offers = n.get("offers") or {}
    low, high = _num(offers.get("lowPrice")), _num(offers.get("highPrice"))
    if low is None:
        low = _num(offers.get("price"))

    units_list = []
    for fp in n.get("accommodationFloorPlan") or []:
        if not isinstance(fp, dict):
            continue
        m = UNIT_TEXT.search(str(fp.get("name") or ""))
        bhk = int(float(m.group(1))) if m else (int(_num(fp.get("numberOfBedrooms")) or 0) or None)
        size = _num(m.group(2)) if m else _num((fp.get("floorSize") or {}).get("value"))
        if size:
            units_list.append({"bhk": bhk, "sqft": size})
    units_from_text = False
    if not units_list and html_text:  # last resort: unit lines as they appear in the page text; marked so they can be audited
        units_from_text = True
        units_list = [{"bhk": int(float(b)), "sqft": _num(s)} for b, s in UNIT_TEXT.findall(html_text) if _num(s)]
    seen, units_clean = set(), []
    for u in units_list:
        if (u["bhk"], u["sqft"]) not in seen:
            seen.add((u["bhk"], u["sqft"]))
            units_clean.append(u)
    kind = KIND_CODE.get(next((w for w in KIND_CODE if w in str(ptype or cfg or "").lower()), ""), "10002")
    for u in units_clean:
        u["kind"] = kind

    amenities = []
    for a in n.get("amenityFeature") or []:
        nm = _name(a)
        if nm:
            amenities.append(str(nm).strip())

    return {"mb_id": "sy" + pid, "name": n["name"].strip(), "developer": _name(n.get("brand") or n.get("provider") or n.get("creator")),
            "locality": locality, "lat": _num(geo.get("latitude")), "lng": _num(geo.get("longitude")),
            "status": (prop("project status") or {}).get("value"),
            "possession": (prop("possession") or {}).get("value"),
            "rera_id": rera, "units": int(units) if units else None, "towers": int(towers) if towers else None, "acres": acres,
            "price_min": low, "price_max": high,
            "config_text": " ".join(str(x) for x in (cfg, ptype) if x) or None,
            "amenities": amenities, "card_units": units_clean, "units_from_text": units_from_text and bool(units_clean),
            "url": url, "source": "squareyards"}


def parse_project_page(html, url):
    """The project's own node from its page (the one whose url is the page url), plus unit lines from the page text."""
    nodes = project_nodes(ld_blocks(html))
    mine = [n for n in nodes if n["url"].rstrip("/") == url.rstrip("/")] or nodes[:1]
    if not mine:
        return None
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)  # visible text only: scripts hold other projects' data
    text = re.sub(r"<[^>]+>", " ", text)
    return parse_node(mine[0], text)
