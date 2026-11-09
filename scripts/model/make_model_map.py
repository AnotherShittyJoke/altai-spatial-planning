"""Схема пространственной модели (задача 08, черновик к командной сессии).

Зоны ТЭЗ (гипотеза из docs/altai_context.md, разд. 6, по границам МО), узлы четырёх уровней,
опорные оси, внешние выходы и природный каркас (55 ООПТ по официальным контурам, объект ЮНЕСКО).
Историко-культурный каркас: точные координаты 76 ОКН из ЕГРОКН.
Читает data/slides/layers/, data/oopt/oopt_oczk_2026-10-28.geojson, data/model/layers/, data/onp_candidates.csv,
data/dataset_v3/settlements.csv. Пишет data/model/map_model_draft.png.
Запуск из корня репозитория: python scripts/model/make_model_map.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from maptools import HALO, INK, MUTED, SURFACE, finish, map_figure, save_map  # noqa: E402

OUT = ROOT / "data" / "model"
LAY = ROOT / "data" / "slides" / "layers"
CRS = 32645
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "figure.facecolor": SURFACE})

# ТЭЗ — гипотеза команды (docs/altai_context.md, разд. 6); зона → МО по ОКТМО
TEZ = {
    "1. Северная агломерационная": (["84701000", "84615000", "84643000"], "#b9472a"),
    "2. Северо-восточная таёжная": (["84625000", "84645000"], "#3f7f6a"),
    "3. Центральная долинная": (["84650000", "84620000", "84635000"], "#c99a3b"),
    "4. Западная высокогорная": (["84640000"], "#6c7fa8"),
    "5. Южная пограничная": (["84610000", "84630000"], "#8a6a9a"),
}
CORE = ["г. Горно-Алтайск", "село Майма"]
INTER = ["село Кош-Агач", "село Усть-Кан"]               # межрайонные центры: сценарий здравоохранения, 81,1 % в 120 мин
NEW_POINTS = ["село Акташ", "село Кебезень", "село Каракокша"]  # новые точки стационарной помощи, 95,3 % в 60 мин


def csv(p):
    for sep in (";", ","):
        d = pd.read_csv(ROOT / p, sep=sep, encoding="utf-8-sig")
        if d.shape[1] > 1:
            return d
    raise ValueError(p)


mo = gpd.read_file(LAY / "mo_boundaries.geojson").to_crs(CRS)
border = gpd.read_file(ROOT / "data" / "access_inputs" / "altai_boundary.geojson").to_crs(CRS)
roads = gpd.read_file(LAY / "roads_main.geojson").to_crs(CRS)
kp = gpd.read_file(LAY / "key_points.geojson").to_crs(CRS).set_index("label")
oopt = gpd.read_file(ROOT / "data" / "oopt" / "oopt_oczk_2026-10-28.geojson").to_crs(CRS)
unesco = gpd.read_file(ROOT / "data" / "model" / "layers" / "unesco_golden_mountains.geojson").to_crs(CRS)
SMALL_HA = 1000  # ООПТ меньше 1 000 га на масштабе республики не видны — рисуем значком
st = csv("data/dataset_v3/settlements.csv")
st = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.longitude, st.latitude), crs=4326).to_crs(CRS)
pt = lambda name: st[st.settlement.eq(name) | st.object_name.eq(name)].geometry.iloc[0]
onp = csv("data/onp_candidates.csv")
onp = gpd.GeoDataFrame(onp, geometry=gpd.points_from_xy(onp.longitude, onp.latitude), crs=4326).to_crs(CRS)
summ = csv("data/dataset_v4/mo_summary.csv")
centers = [f"село {c}" for c in summ.center if c != "Горно-Алтайск"]

fig, ax = map_figure()
# вуаль вне РА
outside = gpd.GeoSeries([box(*border.buffer(600000).total_bounds).difference(border.union_all())], crs=CRS)
outside.plot(ax=ax, color=SURFACE, alpha=0.55, lw=0, zorder=1)
# ТЭЗ
mo["oktmo"] = mo["oktmo"].astype(str)
for name, (codes, col) in TEZ.items():
    mo[mo.oktmo.isin(codes)].plot(ax=ax, color=col, alpha=0.28, lw=0, zorder=1.2)
    mo[mo.oktmo.isin(codes)].dissolve().boundary.plot(ax=ax, color=col, lw=1.6, zorder=2.5)
mo.boundary.plot(ax=ax, color=MUTED, lw=0.4, zorder=2)
# природный каркас
big, small = oopt[oopt.area_ha >= SMALL_HA], oopt[oopt.area_ha < SMALL_HA]
big.plot(ax=ax, facecolor="none", edgecolor="#2f6b3a", hatch="////", lw=0.8, zorder=2.2)
sp = small.geometry.representative_point()
ax.scatter(sp.x, sp.y, s=22, marker="^", color="#2f6b3a", edgecolor=SURFACE, lw=0.5, zorder=4.5)
unesco.boundary.plot(ax=ax, color="#2f6b3a", lw=1.2, ls="--", zorder=2.3)
border.boundary.plot(ax=ax, color=INK, lw=1.4, zorder=3)
# Только точные точки: привязки уровня B к центру НП не обозначают место ОКН.
heritage = gpd.read_file(ROOT / 'data/okn/egrokn_altai_points_all.geojson').to_crs(CRS)
heritage = heritage[heritage['качество'].str.startswith('A')]
assert len(heritage) == 76
heritage.plot(ax=ax, marker='D', color='#612e78', markersize=10, alpha=.8, zorder=4.8)
# опорный каркас: главная ось — Р-256 (Чуйский тракт), вторые оси
r256 = roads[roads.ref.str.contains("Р-256", na=False)]
tel = r256[r256.name.str.contains("Телецкий", na=False)]
chuy = r256.drop(tel.index)
chuy.plot(ax=ax, color=INK, lw=3.0, zorder=4)
tel.plot(ax=ax, color=INK, lw=1.8, zorder=4)
# вторые оси — по реальным дорогам: кратчайший путь на горном графе (scripts/model/build_axes.py)
axes = gpd.read_file(ROOT / "data" / "model" / "layers" / "axes_secondary.geojson").to_crs(CRS)
axes.plot(ax=ax, color=INK, lw=1.8, ls="--", zorder=4)
# узлы
official = csv("data/slides/onp_decree_222.csv").oktmo.astype(str)
is_official = onp.oktmo.astype(str).isin(official)
assert (is_official.sum(), (~is_official).sum()) == (9, 6)
ax.scatter(onp[is_official].geometry.x, onp[is_official].geometry.y, s=14, color=SURFACE, edgecolor=INK, lw=0.8, zorder=5)
ax.scatter(onp[~is_official].geometry.x, onp[~is_official].geometry.y, s=20, marker="D", color=SURFACE, edgecolor=INK, lw=0.8, zorder=5)
c = gpd.GeoSeries([pt(n) for n in centers if n not in INTER], crs=CRS)
ax.scatter(c.x, c.y, s=45, color=INK, edgecolor=SURFACE, lw=0.8, zorder=6)
for n in INTER:
    p = pt(n)
    ax.scatter([p.x], [p.y], s=150, marker="s", color="#b9472a", edgecolor=INK, lw=1.2, zorder=7)
    ax.text(p.x, p.y + 14000, n.replace("село ", ""), fontsize=8.5, fontweight="bold", color=INK, ha="center",
            path_effects=HALO, zorder=8)
for n in NEW_POINTS:
    p = pt(n)
    ax.scatter([p.x], [p.y], s=60, marker="P", color="#b9472a", edgecolor=SURFACE, lw=0.6, zorder=7)
    ax.text(p.x - 7000, p.y - 4000, n.replace("село ", ""), fontsize=7.5, color=INK, ha="right", path_effects=HALO, zorder=8)
core = gpd.GeoSeries([pt(n) for n in CORE], crs=CRS)
ax.scatter(core.x, core.y, s=260, color="#b9472a", edgecolor=INK, lw=1.4, zorder=7)
ax.text(core.x.iloc[0] - 14000, core.y.iloc[0] - 3000, "Горно-Алтайск — Майма", fontsize=9, fontweight="bold",
        color=INK, ha="right", path_effects=HALO, zorder=8)  # справа — Кебезень и Каракокша
# внешние выходы
for name, text, (dx, dy) in [("МАПП Ташанта", "Ташанта → Монголия", (-40000, -40000)),
                             ("Карагай", "→ Казахстан", (-45000, -22000)),
                             ("Кокоря", "→ Тыва", (14000, -4000)),
                             ("Бийск (ж/д)", "→ Бийск, Барнаул, Новосибирск", (-60000, 12000))]:
    p = kp.loc[name].geometry
    ax.scatter([p.x], [p.y], s=55, marker="D", color=SURFACE, edgecolor=INK, lw=1.4, zorder=7)
    ax.text(p.x + dx, p.y + dy, text, fontsize=7.5, color=INK, path_effects=HALO, zorder=8)
# подписи зон
for name, (codes, col) in TEZ.items():
    g = mo[mo.oktmo.isin(codes)].dissolve().representative_point().iloc[0]
    off = {"1": (15000, -20000), "2": (10000, 60000), "3": (20000, -45000), "4": (-30000, -35000)}.get(name[0], (0, 0))
    ax.text(g.x + off[0], g.y + off[1], name.split(". ")[0], fontsize=16, fontweight="bold", color=col, ha="center",
            va="center", alpha=0.9, path_effects=HALO, zorder=3.5)

x0, y0, x1, y1 = border.total_bounds
finish(fig, ax, extent=(x0 - 30000, y0 - 20000, x1 + 20000, y1 + 40000), basemap_style="relief",
       title="Условные обозначения\nпространственная модель (черновик)",
       handles=[Patch(facecolor=col, alpha=0.45, edgecolor=col, label=f"ТЭЗ {name}") for name, (_, col) in TEZ.items()] +
               [Line2D([], [], marker="o", ls="", ms=12, mfc="#b9472a", mec=INK, label="ядро: Горно-Алтайск — Майма"),
                Line2D([], [], marker="s", ls="", ms=9, mfc="#b9472a", mec=INK, label="межрайонный центр (предложение)"),
                Line2D([], [], marker="o", ls="", ms=6, mfc=INK, mec=SURFACE, label="районный центр"),
                Line2D([], [], marker="o", ls="", ms=4.5, mfc=SURFACE, mec=INK, label="официальный сельский ОНП (9)"),
                Line2D([], [], marker="D", ls="", ms=4.5, mfc=SURFACE, mec=INK, label="перспективный опорный центр команды (6)"),
                Line2D([], [], marker="P", ls="", ms=7, color="#b9472a", label="новая точка стационарной помощи (предложение)"),
                Line2D([], [], color=INK, lw=3.0, label="главная ось: Р-256 «Чуйский тракт»"),
                Line2D([], [], color=INK, lw=1.8, label="вторая ось: Р-256, подъезд к Телецкому озеру (Майма — Артыбаш)"),
                Line2D([], [], color=INK, lw=1.8, ls="--", label="вторые оси по дорогам: Черга — Усть-Кан — Усть-Кокса — Карагай, Акташ — Улаган"),
                Line2D([], [], marker="D", ls="", mfc=SURFACE, mec=INK, label="внешний выход"),
                Patch(facecolor="none", edgecolor="#2f6b3a", hatch="////", label=f"ООПТ от 1 000 га ({len(big)})"),
                Line2D([], [], marker="^", ls="", ms=6, color="#2f6b3a", mec=SURFACE, label=f"ООПТ меньше 1 000 га ({len(small)})"),
                Line2D([], [], color="#2f6b3a", lw=1.2, ls="--", label="объект ЮНЕСКО «Золотые горы Алтая»"),
                Line2D([], [], marker='D', ls='', ms=4, color='#612e78', label='76 ОКН с точными координатами (ЕГРОКН)')])
save_map(fig, OUT / "map_model_draft.png")
print("ok")
