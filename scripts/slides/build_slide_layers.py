"""Слои для слайдов 01–03 (задача 07): границы МО, магистрали, соседние регионы и страны.

Источники:
- границы 11 МО — OSM, отношения admin_level=6 (полигоны через Nominatim /lookup по osm_id);
- магистрали trunk/primary в РА с буфером — OSM через Overpass (зеркало из OVERPASS_URL);
- соседние регионы России и страны — Natural Earth 10m admin_1 (public domain).
Пишет data/slides/layers/*.geojson (EPSG:4326, геометрия упрощена до ~100 м).
Запуск из корня репозитория: python scripts/slides/build_slide_layers.py
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, shape

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "slides" / "layers"
OUT.mkdir(parents=True, exist_ok=True)
OVERPASS = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
      "ne_10m_admin_1_states_provinces.geojson")
SIMPLIFY = 0.001  # градусы, ≈ 100 м

# osm_id отношений МО (admin_level=6 в границах РА, OSM на 28.10.2026) → ОКТМО из AGENTS.md
MO_REL = {
    192547: ("84610000", "Кош-Агачский район"), 192563: ("84615000", "Майминский район"),
    192546: ("84620000", "Онгудайский район"), 192560: ("84625000", "Турочакский район"),
    192559: ("84630000", "Улаганский район"), 192544: ("84635000", "Усть-Канский район"),
    192543: ("84640000", "Усть-Коксинский район"), 192564: ("84643000", "Чемальский район"),
    953581: ("84645000", "Чойский район"), 192545: ("84650000", "Шебалинский район"),
    1875749: ("84701000", "г. Горно-Алтайск"),
}


def overpass(query, tries=5, pause=20):
    """Зеркало отвечает с перебоями (504), поэтому несколько попыток с паузой."""
    data = urllib.parse.urlencode({"data": query}).encode()
    for i in range(tries):
        try:
            with urllib.request.urlopen(OVERPASS, data=data, timeout=300) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — 504 и обрывы одинаково повторяем
            print(f"Overpass, попытка {i + 1}: {e}")
            time.sleep(pause)
    raise RuntimeError("Overpass не ответил")


# 1. границы МО (Nominatim требует User-Agent с названием приложения)
url = ("https://nominatim.openstreetmap.org/lookup?format=geojson&polygon_geojson=1&osm_ids="
       + ",".join(f"R{i}" for i in MO_REL))
req = urllib.request.Request(url, headers={"User-Agent": "altai-spatial-planning (ITMO course project)"})
with urllib.request.urlopen(req, timeout=120) as r:
    feats = json.load(r)["features"]
mo = gpd.GeoDataFrame([dict(osm_id=f["properties"]["osm_id"], oktmo=MO_REL[f["properties"]["osm_id"]][0],
                            mo=MO_REL[f["properties"]["osm_id"]][1], geometry=shape(f["geometry"]))
                       for f in feats], crs=4326)
assert len(mo) == len(MO_REL), f"Nominatim вернул {len(mo)} МО из {len(MO_REL)}"
mo["geometry"] = mo.geometry.simplify(SIMPLIFY)
mo.to_file(OUT / "mo_boundaries.geojson", driver="GeoJSON")
print("МО:", len(mo))

# 2. магистрали (trunk/primary) в рамке РА + 30 км
w, s, e, n = gpd.read_file(ROOT / "data" / "access_inputs" / "altai_boundary.geojson").total_bounds
bbox = f"{s - 0.3},{w - 0.4},{n + 0.3},{e + 0.4}"
roads = overpass(f'[out:json][timeout:240];way["highway"~"^(trunk|primary)$"]({bbox});out tags geom;')
lines = [dict(highway=el["tags"]["highway"], ref=el["tags"].get("ref", ""), name=el["tags"].get("name", ""),
              geometry=LineString([(p["lon"], p["lat"]) for p in el["geometry"]]))
         for el in roads["elements"] if len(el.get("geometry", [])) > 1]
roads = gpd.GeoDataFrame(lines, crs=4326)
roads["geometry"] = roads.geometry.simplify(SIMPLIFY / 2)
roads.to_file(OUT / "roads_main.geojson", driver="GeoJSON")
print("магистрали:", len(roads), "отрезков, из них Р-256:", roads.ref.str.contains("Р-256").sum())

# 3. соседи: регионы России и страны вокруг РА
ne = gpd.read_file(NE)
ne = ne.cx[78:96, 45:57][["name", "name_ru", "admin", "iso_a2", "geometry"]]  # name_ru у Алтайского края ошибочно «Республика Алтай»
ne["geometry"] = ne.geometry.simplify(SIMPLIFY * 3)
ne.to_file(OUT / "neighbors_admin1.geojson", driver="GeoJSON")
print("регионы Natural Earth в рамке:", len(ne))

# 4. опорные точки за пределами датасета НП (Nominatim, первый результат)
POINTS = {
    "Бийск (ж/д)": "Бийск, Алтайский край",  # конечная станция ветки; «станция Бийск» находит лодочную станцию
    "МАПП Ташанта": "Ташанта, Кош-Агачский район",
    "Карагай": "Карагай, Усть-Коксинский район",
    "Кокоря": "Кокоря, Кош-Агачский район",
    "плато Укок": "Укок",
    "Барнаул": "Барнаул",
    "Новосибирск": "Новосибирск",
}
pts = []
for label, q in POINTS.items():
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(q),
                                 headers={"User-Agent": "altai-spatial-planning (ITMO course project)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        hit = json.load(r)[0]
    pts.append(dict(label=label, query=q, osm_type=hit["osm_type"], osm_id=hit["osm_id"], display_name=hit["display_name"],
                    geometry=shape({"type": "Point", "coordinates": [float(hit["lon"]), float(hit["lat"])]})))
    time.sleep(1.1)  # правило Nominatim: не чаще 1 запроса в секунду
pts = gpd.GeoDataFrame(pts, crs=4326)
pts.to_file(OUT / "key_points.geojson", driver="GeoJSON")
print(pts[["label", "display_name"]].to_string())
