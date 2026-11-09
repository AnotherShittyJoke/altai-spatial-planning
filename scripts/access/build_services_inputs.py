"""Слои школ и пунктов первичной медико-санитарной помощи (ПМСП) по OSM для расчёта доступности.

Источник — OSM через Overpass (зеркало из OVERPASS_URL): amenity=school; amenity=clinic|doctors|hospital
и любые healthcare=* в границах Республики Алтай. Класс объекта определяется по тегам и названию.
Официальные реестры (Рособрнадзор, ФРМО Минздрава) из облака недоступны, поэтому полнота OSM
оценивается отдельно (docs/access_services.md).
Пишет data/access_inputs/schools_osm.geojson и data/access_inputs/primary_care_osm.geojson (EPSG:4326).
Запуск из корня репозитория: OVERPASS_URL=<зеркало> python scripts/access/build_services_inputs.py
(SERVICES_JSON=<файл> — взять готовый ответ Overpass вместо запроса)
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "access_inputs"
OVERPASS = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
QUERY = ('[out:json][timeout:240];area(3600145194)->.ra;(nwr(area.ra)["amenity"="school"];'
         'nwr(area.ra)["amenity"~"^(clinic|doctors|hospital)$"];nwr(area.ra)["healthcare"];);out center tags;')

NOT_SCHOOL = re.compile(r"искусств|музык|художеств|спортив|ДЮСШ|автошкол", re.I)
FAP = re.compile(r"ФАП|фельдшер", re.I)
AMB = re.compile(r"амбулатор|общей врачебной|ВОП", re.I)
HOSP = re.compile(r"больниц|поликлин|поликоин|ЦРБ|\bРБ\b|больничный", re.I)
NOT_PMSP = re.compile(r"Инвитро|Евромед|МРТ|Шаман|Relax|Эмчи|Алорто|диспансер|противочум|интернат|дом ребенка|"
                      r"перинатальн|инфекционн|скорой", re.I)


def overpass(query, tries=5, pause=30):
    data = urllib.parse.urlencode({"data": query}).encode()
    for i in range(tries):
        try:
            with urllib.request.urlopen(OVERPASS, data=data, timeout=300) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — зеркало отвечает 504 с перебоями
            print(f"Overpass, попытка {i + 1}: {e}")
            time.sleep(pause)
    raise RuntimeError("Overpass не ответил")


src = os.getenv("SERVICES_JSON")
els = json.load(open(src))["elements"] if src else overpass(QUERY)["elements"]


def point(e):
    c = e.get("center", e)
    return Point(c["lon"], c["lat"])


schools, pmsp = [], []
for e in els:
    t = e["tags"]
    name = t.get("name", "")
    row = dict(osm_id=f"{e['type'][0]}{e['id']}", name=name, amenity=t.get("amenity"), healthcare=t.get("healthcare"),
               geometry=point(e))
    if t.get("amenity") == "school":
        if not NOT_SCHOOL.search(name):
            schools.append(row)
        continue
    if t.get("amenity") in ("pharmacy", "dentist") or t.get("healthcare") in ("pharmacy", "dentist", "laboratory",
                                                                                 "birthing_centre"):
        continue
    if NOT_PMSP.search(name):
        continue
    kind = ("ФАП" if FAP.search(name) else "врачебная амбулатория" if AMB.search(name)
            else "больница, поликлиника" if HOSP.search(name) or t.get("amenity") == "hospital"
            else "медпункт без названия" if not name else None)
    if kind:
        pmsp.append(dict(row, kind=kind))

# 11 больниц из слоя доступности — всегда в составе ПМСП (координаты сверены с адресами СТП)
hosp = gpd.read_parquet(OUT / "hospitals_services.parquet").to_crs(4326)
pmsp += [dict(osm_id=str(h.osm_id), name=h["name"], amenity="hospital", healthcare="hospital",
              kind="больница, поликлиника", geometry=h.geometry) for _, h in hosp.iterrows()]

# участковые больницы и врачебные амбулатории по СТП (табл. III.7.5), координаты — точка НП.
# Балыктуюль, Кокоря, Барагаш есть и в перечне планируемых амбулаторий СТП (прил. 4) — существование не подтверждено,
# поэтому в базовый расчёт не входят (kind с пометкой «план»)
STP_PLANNED = {"село Балыктуюль", "село Кокоря", "село Барагаш"}
stp = pd.read_csv(OUT / "stp_primary_care_settlements.csv", encoding="utf-8-sig")
pmsp += [dict(osm_id=f"stp:{r.id}", name=f"участковая больница / врачебная амбулатория, {r['name']}", amenity="", healthcare="",
              kind="амбулатория по СТП (план)" if r["name"] in STP_PLANNED else "участковая больница / амбулатория (СТП)",
              geometry=Point(r.longitude, r.latitude)) for _, r in stp.iterrows()]

s = gpd.GeoDataFrame(schools, crs=4326)
p = gpd.GeoDataFrame(pmsp, crs=4326)
# одна и та же больница может быть и в OSM, и в слое больниц: точки ближе 300 м одного класса считаем дублями
pu = p.to_crs(32645)
keep = []
for i, r in pu.iterrows():
    if not any(pu.loc[j, "kind"] == r.kind and r.geometry.distance(pu.loc[j, "geometry"]) < 300 for j in keep):
        keep.append(i)
p = p.loc[keep]
s.to_file(OUT / "schools_osm.geojson", driver="GeoJSON")
p.to_file(OUT / "primary_care_osm.geojson", driver="GeoJSON")
print("школ:", len(s)); print(p["kind"].value_counts().to_string())
