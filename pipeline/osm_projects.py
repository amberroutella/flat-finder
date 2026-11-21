"""Build a society list from OpenStreetMap, for cities where no portal can be crawled.

usage: python osm_projects.py <city>   (run osm_fetch.py <city> first)
       -> out/<city>/mb_projects.json

Reads the named residential areas that osm_fetch.py saved and writes one project per society-sized area,
in the same shape build_city.py reads from the Magicbricks crawl. No prices, ratings, unit counts or
listings are invented: those fields are simply absent, so the site shows no price for these societies.
Bedroom sizes still come from data/verified/<city>*.json as usual.

Area size picks what counts as a society. Whole neighbourhoods are not societies, but they are used to fill
in each society's locality (the smallest neighbourhood that contains it).
"""
import json
import pathlib
import re
import sys

import geo

ROOT = pathlib.Path(__file__).parent
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())

MIN_M2 = 3_000        # smaller than this is a plot, a temple garden, a tagging slip
MAX_M2 = 400_000      # bigger than this is a neighbourhood, not a single society (about 100 acres)
NEIGHBOURHOOD_M2 = 400_000
NEIGHBOURHOOD_MAX_M2 = 25_000_000
ACRE = 4046.86
# names that are an area of town or a service block, not a housing society
NOT_A_SOCIETY = re.compile(r"\b(market|school|college|university|hospital|temple|mandir|masjid|church|gurudwara|"
                           r"campus|hostel|cantonment|cantt|barracks|quarters|stadium|mall|hotel|resort)\b", re.I)


def build(city):
    out = ROOT / "out" / city
    areas = json.loads((out / "osm_areas.geojson").read_text())["features"]
    south, west, north, east = CITIES[city]["bbox"]
    sized = []
    for a in areas:
        ring = a["geometry"]["coordinates"][0]
        if len(ring) < 4:
            continue
        sized.append((a, ring, geo.area_m2(ring), geo.centroid(ring)))

    hoods = [(a["properties"]["name"], ring, m2) for a, ring, m2, _ in sized if NEIGHBOURHOOD_M2 < m2 < NEIGHBOURHOOD_MAX_M2]
    hoods.sort(key=lambda h: h[2])  # smallest first, so the tightest containing area wins

    projects, seen_names = [], {}
    for a, ring, m2, c in sized:
        name = (a["properties"]["name"] or "").strip()
        if not name or not (MIN_M2 <= m2 <= MAX_M2) or NOT_A_SOCIETY.search(name):
            continue
        lng, lat = c
        if not (south < lat < north and west < lng < east):
            continue
        locality = next((h for h, r, _ in hoods if h != name and geo.point_in_ring(c, r)), None)
        osm = a["properties"]["osm"]
        seen_names[name.lower()] = seen_names.get(name.lower(), 0) + 1
        projects.append({"mb_id": "osm" + osm.replace("/", ""), "name": name, "developer": None, "locality": locality,
                         "lat": round(lat, 6), "lng": round(lng, 6), "acres": round(m2 / ACRE, 1),
                         "url": "https://www.openstreetmap.org/" + osm, "source": "openstreetmap"})
    out.mkdir(parents=True, exist_ok=True)
    target = out / "mb_projects.json"
    if target.exists():
        try:
            existing = json.loads(target.read_text())
        except ValueError:
            existing = []
        if any(p.get("source") != "openstreetmap" for p in existing):
            sys.exit(f"{target} holds a portal crawl; not overwriting it with an OpenStreetMap list")
    target.write_text(json.dumps(projects, indent=0))
    dup = sum(1 for n in seen_names.values() if n > 1)
    print(f"areas read {len(sized)}, societies written {len(projects)}, neighbourhoods used for locality {len(hoods)}, "
          f"names that appear more than once {dup}")
    return projects


if __name__ == "__main__":
    build(next((a for a in sys.argv[1:] if a in CITIES), "gurgaon"))
