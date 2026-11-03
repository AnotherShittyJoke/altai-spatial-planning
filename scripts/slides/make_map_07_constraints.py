"""Карта «Природный каркас и ограничения развития» для слайда 07 (задача 04).

Слои: ООПТ по официальным контурам (карта ООПТ России, 28.10.2026; федеральные и
крупные региональные — штриховкой, мелкие региональные — значками), НП в зоне
подтопления (СТП, табл. 1.5) и НП с риском разрыва связи в паводок (табл. 1.6).
Лавиноопасные участки дорог геометрии не имеют (табличные данные СТП) — на карте
не показаны, упоминаются в тезисах слайда.

Запуск:  python scripts/slides/make_map_07_constraints.py
Выход:   data/slides/map_07_constraints.png (2000x1400, макет scripts/maptools.py)
"""
import csv
import re
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import box

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "scripts"))
from maptools import INK, MUTED, finish, map_figure, save_map  # noqa: E402

GREEN_D, GREEN_L, RED, ORANGE = "#3f7f6a", "#a3c6b2", "#b9472a", "#e46a2e"
OUT = R / "data/slides"

ra = gpd.read_file(R / "data/access_inputs/altai_boundary.geojson").to_crs(32645)
oopt = gpd.read_file(R / "data/oopt/oopt_oczk_2026-10-28.geojson").to_crs(32645)
big = oopt[oopt["area_ha"] >= 1000]
small = oopt[oopt["area_ha"] < 1000]

setts = pd.read_csv(R / "data/dataset_v3/settlements.csv", sep=";")
setts["short"] = setts["settlement"].str.replace(
    r"^(село|с\s|с\.\s*|город|г\s|г\.\s*|поселок|п\s|п\.\s*)\s*", "", regex=True, case=False
).str.strip().str.lower().str.replace("ё", "е")


def _squash(s: str) -> str:
    """без пробелов и дефисов — чтобы «Большой-Яломан» = «Большой Яломан», «НижняяТалда» = «Нижняя Талда»."""
    return s.replace(" ", "").replace("-", "").replace(".", "")


def flood_pts(path: str) -> gpd.GeoDataFrame:
    rows = list(csv.DictReader(open(R / path, encoding="utf-8-sig")))
    seen, miss = {}, []
    for r in rows:
        np_, mo = r.get("Населенный пункт", "").strip(), r.get("Муниципальное образование", "").strip()
        if not np_ or np_.startswith("№") or np_ == "Населенный пункт" or "Итого" in np_:
            continue
        if np_ in {v[0] for v in seen.values()}:
            continue
        stem = mo.replace("муниципальное образование", "").replace("район", "").strip()
        # строка может перечислять несколько НП: «Карасук, п.Куташ»; скобки — «Шебалино (часть села)»
        tokens = [t.strip() for t in np_.split("(")[0].split(",") if t.strip()]
        for token in tokens:
            token = re.sub(r"^(село|с\.|поселок|п\.)\s*", "", token.strip(), flags=re.I).strip()
            ntok, nshort = _squash(token.lower()), setts["short"].map(_squash)
            hit = setts[(nshort == ntok) & setts["mo"].str.contains(stem)]
            if not len(hit):  # имя уникально в РА — берём без привязки к району
                cand = setts[nshort == ntok]
                if len(cand) == 1:
                    hit = cand
            if not len(hit) and len(ntok) >= 6:  # префикс: «Сайдыс» → «Средний Сайдыс» не берём, но «НижняяТалда» найдём
                cand = setts[nshort.str.startswith(ntok)]
                if len(cand) == 1:
                    hit = cand
            if len(hit):
                seen[token] = (token, hit.iloc[0]["latitude"], hit.iloc[0]["longitude"])
            else:
                miss.append((stem, token))
    print(f"{Path(path).name}: НП в списке {len(seen) + len(miss)}, привязано {len(seen)}, без координат {len(miss)}")
    for m in miss:
        print("  нет в перечне НП:", m)
    gdf = gpd.GeoDataFrame(
        {"НП": [v[0] for v in seen.values()]},
        geometry=gpd.points_from_xy([v[2] for v in seen.values()], [v[1] for v in seen.values()]),
        crs=4326,
    ).to_crs(32645)
    return gdf


flood = flood_pts("data/stp_extracted/chs/flood_zone_settlements_1.csv")
cut = flood_pts("data/stp_extracted/chs/flood_zone_settlements_2.csv")

def veil_outside(ax, alpha=0.55):
    x0, y0, x1, y1 = EXTENT
    outside = box(x0 - 1e6, y0 - 1e6, x1 + 1e6, y1 + 1e6).difference(ra.union_all())
    gpd.GeoSeries([outside], crs=32645).plot(ax=ax, color="#f3f1ec", alpha=alpha, zorder=8)


fig, ax = map_figure()
ax.set_facecolor("#ffffff")

fed = big[big["level"] == "Федеральное"]
reg_big = big[big["level"] == "Региональное"]
fed.plot(ax=ax, facecolor="none", edgecolor=GREEN_D, linewidth=1.0, hatch="////", zorder=3)
reg_big.plot(ax=ax, facecolor="none", edgecolor=GREEN_D, linewidth=0.7, hatch="\\\\\\", zorder=3)
small.plot(ax=ax, color=GREEN_D, marker="o", markersize=12, zorder=4)
cut.plot(ax=ax, color=ORANGE, marker="s", markersize=26, edgecolor=INK, linewidth=0.5, zorder=5)
flood.plot(ax=ax, color=RED, marker="^", markersize=34, edgecolor=INK, linewidth=0.5, zorder=6)
ra.boundary.plot(ax=ax, color=INK, linewidth=1.2, zorder=7)

bx = ra.total_bounds
EXTENT = (bx[0] - 150000, bx[1] - 70000, bx[2] + 90000, bx[3] + 180000)


def veil_outside(ax, alpha=0.55):
    x0, y0, x1, y1 = EXTENT
    outside = box(x0 - 1e6, y0 - 1e6, x1 + 1e6, y1 + 1e6).difference(ra.union_all())
    gpd.GeoSeries([outside], crs=32645).plot(ax=ax, color="#f3f1ec", alpha=alpha, zorder=8)


veil_outside(ax)

handles = [
    Patch(facecolor="none", edgecolor=GREEN_D, hatch="///", label="ООПТ федерального значения (заповедники, нацпарк, ботсад)"),
    Patch(facecolor="none", edgecolor=GREEN_D, hatch="\\\\\\", label="ООПТ региональные от 1 000 га (парки, заказники)"),
    Line2D([], [], marker="o", ls="", ms=5, color=GREEN_D, label="ООПТ региональные мельче 1 000 га"),
    Line2D([], [], marker="^", ls="", ms=8, mfc=RED, mec=INK, label="НП в зоне подтопления: 41 НП, 13,5 тыс. жителей"),
    Line2D([], [], marker="s", ls="", ms=7, mfc=ORANGE, mec=INK, label="риск разрыва связи в паводок: 36 НП, 12,1 тыс. жителей"),
]
finish(fig, ax, extent=EXTENT, handles=handles, title="Условные обозначения", basemap_style="relief")
save_map(fig, OUT / "map_07_constraints.png")
plt.close(fig)
print("сохранено:", OUT / "map_07_constraints.png")
