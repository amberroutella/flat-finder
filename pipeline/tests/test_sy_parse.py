import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import sy_crawl  # noqa: E402
import sy_parse  # noqa: E402

URL = "https://www.squareyards.com/dehradun-residential-property/bayleaf-heights/328099/project"


def node(url=URL, name="Bayleaf Heights", **extra):
    n = {"@type": "ApartmentComplex", "@id": url + "#project", "name": name, "url": url,
         "identifier": [{"@type": "PropertyValue", "propertyID": "projectId", "value": 328099},
                        {"@type": "PropertyValue", "propertyID": "RERA", "name": "RERA registration number", "value": "UKREP04240000552"}],
         "address": {"@type": "PostalAddress", "streetAddress": "Canal Road, Dehradun North", "addressLocality": "Dehradun"},
         "geo": {"@type": "GeoCoordinates", "latitude": 30.359934, "longitude": 78.083648},
         "additionalProperty": [{"@type": "PropertyValue", "name": "Project Status", "value": "New Launch"},
                                {"@type": "PropertyValue", "name": "Property Type", "value": "Apartment"},
                                {"@type": "PropertyValue", "name": "Unit Configuration", "value": "3, 4 BHK Flats"},
                                {"@type": "PropertyValue", "name": "Total Land Area", "value": 0.39, "unitCode": "ACR", "unitText": "Acres"}],
         "accommodationFloorPlan": [{"@type": "FloorPlan", "name": "3 BHK Apartment - 2306 sq. ft. (Saleable)"},
                                    {"@type": "FloorPlan", "name": "3 BHK Apartment - 2344 sq. ft. (Saleable)"}]}
    n.update(extra)
    return n


def page(*nodes, body="", title="Bayleaf Heights"):
    ld = json.dumps({"@context": "https://schema.org", "@graph": list(nodes)})
    return f"<html><head><title>{title}</title><script type='application/ld+json'>{ld}</script></head><body>{body}{'x' * 25_000}</body></html>"


def test_parses_a_project_page():
    p = sy_parse.parse_project_page(page(node()), URL)
    assert p["mb_id"] == "sy328099" and p["name"] == "Bayleaf Heights" and p["source"] == "squareyards"
    assert (p["lat"], p["lng"]) == (30.359934, 78.083648)
    assert p["rera_id"] == "UKREP04240000552" and p["locality"] == "Canal Road"
    assert p["status"] == "New Launch" and p["acres"] == 0.39 and p["config_text"] == "3, 4 BHK Flats Apartment"
    assert p["card_units"] == [{"bhk": 3, "sqft": 2306.0, "kind": "10002"}, {"bhk": 3, "sqft": 2344.0, "kind": "10002"}]
    assert p["price_min"] is None  # "price on request": no price is made up


def test_reads_a_builder_price_when_given():
    p = sy_parse.parse_project_page(page(node(offers={"@type": "AggregateOffer", "lowPrice": "12500000", "highPrice": 21000000})), URL)
    assert p["price_min"] == 12_500_000 and p["price_max"] == 21_000_000


def test_picks_the_node_for_this_page_and_falls_back_to_page_text_for_units():
    other = node(url=URL.replace("328099", "328100").replace("bayleaf-heights", "other"), name="Other")
    bare = node(accommodationFloorPlan=[])
    html = page(other, bare, body="<li>4 BHK Apartment - 2,672 sq. ft. (Saleable)</li>")
    p = sy_parse.parse_project_page(html, URL)
    assert p["name"] == "Bayleaf Heights" and p["card_units"] == [{"bhk": 4, "sqft": 2672.0, "kind": "10002"}]


def test_page_without_a_project_node_is_none():
    assert sy_parse.parse_project_page(page({"@type": "Organization", "name": "Square Yards"}), URL) is None


def test_detects_block_pages():
    assert sy_parse.is_blocked("<title>Security Alert</title>" + "x" * 30_000)
    assert sy_parse.is_blocked("<title>We'll be back soon!</title>")
    assert not sy_parse.is_blocked(page(node()))


def test_finds_project_urls_for_this_city_only():
    html = f'<a href="{URL}">a</a> <a href="{URL}">dup</a> <a href="https://www.squareyards.com/gurgaon-residential-property/x/1/project">g</a>'
    assert sy_parse.project_urls(html, "dehradun") == [URL]


def test_crawl_list_follows_same_city_list_pages_and_stops_on_block(tmp_path, monkeypatch):
    monkeypatch.setattr(sy_crawl, "ROOT", tmp_path)
    monkeypatch.setitem(sy_crawl.CITIES, "doon", {"squareyards": {"slug": "dehradun"}})
    pages = {
        "https://www.squareyards.com/new-launch-projects-in-dehradun":
            f'<a href="https://www.squareyards.com/projects-in-malsi-dehradun">m</a> <a href="https://www.squareyards.com/projects-in-malsi-gurgaon">no</a> <a href="{URL}">p</a>',
        "https://www.squareyards.com/projects-in-malsi-dehradun":
            '<a href="https://www.squareyards.com/dehradun-residential-property/second/328200/project">p</a>',
    }
    monkeypatch.setattr(sy_crawl, "fetch", lambda u: pages.get(u))
    sy_crawl.crawl_list("doon")
    urls = json.loads((tmp_path / "out" / "doon" / "sy_urls.json").read_text())
    assert urls == [URL, "https://www.squareyards.com/dehradun-residential-property/second/328200/project"]
