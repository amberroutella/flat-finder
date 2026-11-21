import json
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import osm_projects  # noqa: E402


def square(lng, lat, half_m):
    d = half_m / 111_000  # degrees, good enough for a test
    return [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]


def feat(osm, name, ring):
    return {"type": "Feature", "properties": {"osm": osm, "name": name}, "geometry": {"type": "Polygon", "coordinates": [ring]}}


@pytest.fixture
def city(tmp_path, monkeypatch):
    monkeypatch.setattr(osm_projects, "ROOT", tmp_path)
    monkeypatch.setitem(osm_projects.CITIES, "testville", {"bbox": [30.0, 78.0, 30.5, 78.5]})
    (tmp_path / "out" / "testville").mkdir(parents=True)
    return tmp_path / "out" / "testville"


def write_areas(city, feats):
    (city / "osm_areas.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def test_keeps_societies_and_sets_locality(city):
    write_areas(city, [
        feat("way/1", "Rajpur Road", square(78.2, 30.2, 1500)),      # neighbourhood, ~9 km2: locality, not a society
        feat("way/2", "Green Valley Apartments", square(78.2, 30.2, 100)),  # 4 ha: society
        feat("way/3", "Tiny garden", square(78.21, 30.21, 20)),       # 1,600 m2: too small
        feat("way/4", "DAV School", square(78.22, 30.22, 100)),       # service block by name
        feat("way/5", "Far Away Homes", square(79.0, 31.0, 100)),     # outside the city box
    ])
    projects = osm_projects.build("testville")
    assert [p["name"] for p in projects] == ["Green Valley Apartments"]
    p = projects[0]
    assert p["locality"] == "Rajpur Road" and p["mb_id"] == "osmway2" and p["url"].endswith("way/2")
    assert p["acres"] > 5 and "price_min" not in p


def test_refuses_to_overwrite_a_portal_crawl(city):
    write_areas(city, [feat("way/2", "Green Valley Apartments", square(78.2, 30.2, 100))])
    (city / "mb_projects.json").write_text(json.dumps([{"mb_id": "1", "name": "Real Magicbricks project"}]))
    with pytest.raises(SystemExit):
        osm_projects.build("testville")
    assert "Real Magicbricks project" in (city / "mb_projects.json").read_text()


def test_can_rerun_over_its_own_output(city):
    write_areas(city, [feat("way/2", "Green Valley Apartments", square(78.2, 30.2, 100))])
    osm_projects.build("testville")
    assert len(osm_projects.build("testville")) == 1


def write_named(city, items):
    (city / "osm_named.json").write_text(json.dumps(items))


def named(osm, name, lng, lat, kind="society"):
    return {"osm": osm, "name": name, "lng": lng, "lat": lat, "kind": kind}


def test_named_buildings_become_societies_with_place_locality(city):
    write_areas(city, [feat("way/2", "Green Valley Apartments", square(78.2, 30.2, 100))])
    write_named(city, [
        named("node/10", "Rajpur", 78.3, 30.3, "place"),
        named("way/11", "Sunrise Residency", 78.301, 30.301),          # new society, ~140 m from the place node
        named("way/12", "Green Valley Apartments", 78.2002, 30.2002),   # same name next to the area society: skipped
        named("way/13", "Tower B", 78.31, 30.31),                       # a part of a complex: skipped
        named("way/14", "City Hospital Staff Quarters", 78.32, 30.32),  # not a society by name
        named("way/15", "Nowhere Heights", 79.5, 31.5),                 # outside the box
    ])
    names = [p["name"] for p in osm_projects.build("testville")]
    assert names == ["Green Valley Apartments", "Sunrise Residency"]
    sunrise = json.loads((city / "mb_projects.json").read_text())[1]
    assert sunrise["locality"] == "Rajpur" and sunrise["mb_id"] == "osmway11"


def test_named_building_inside_an_area_society_is_not_a_second_society(city):
    write_areas(city, [feat("way/2", "Green Valley Apartments", square(78.2, 30.2, 100))])
    write_named(city, [named("way/16", "Block Aurora", 78.2003, 30.2003)])  # ~40 m from the area's centre
    assert len(osm_projects.build("testville")) == 1
