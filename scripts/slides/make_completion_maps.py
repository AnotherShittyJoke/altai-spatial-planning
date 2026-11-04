"""Карты расселения, формальной экономики и ОКН для завершения презентации.

Запуск из корня: .venv/bin/python scripts/slides/make_completion_maps.py
Население точек — перепись-2020, ОНП — оценка-2025. Координаты ОКН
уровня B показывают центр населенного пункта, а не положение памятника.
"""
from pathlib import Path
import sys
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from maptools import HALO, INK, finish, map_figure, save_map

CRS = 32645
OUT = ROOT / 'data/slides'


def read_csv(path):
    with (ROOT / path).open(encoding='utf-8-sig') as source:
        sep = ';' if ';' in source.readline() else ','
    return pd.read_csv(ROOT / path, sep=sep, encoding='utf-8-sig')


def points(df):
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=4326).to_crs(CRS)


def main():
    mo = gpd.read_file(ROOT / 'data/slides/layers/mo_boundaries.geojson').to_crs(CRS)
    border = gpd.read_file(ROOT / 'data/access_inputs/altai_boundary.geojson').to_crs(CRS)
    roads = gpd.read_file(ROOT / 'data/slides/layers/roads_main.geojson').to_crs(CRS)
    st = points(read_csv('data/dataset_v3/settlements.csv'))
    onp = points(read_csv('data/onp_candidates.csv'))
    x0, y0, x1, y1 = border.total_bounds
    extent = (x0-35000, y0-25000, x1+35000, y1+35000)

    def base():
        fig, ax = map_figure()
        mo.boundary.plot(ax=ax, color='#777777', lw=.5, zorder=2)
        roads.plot(ax=ax, color='#888888', lw=.6, zorder=3)
        border.boundary.plot(ax=ax, color=INK, lw=1, zorder=5)
        return fig, ax

    fig, ax = base()
    bins = [(0, 500, 8), (500, 1500, 23), (1500, 10000, 65), (10000, float('inf'), 170)]
    handles = []
    for lo, hi, size in bins:
        q = st[(st.population >= lo) & (st.population < hi)]
        q.plot(ax=ax, color='#789b92', markersize=size, edgecolor='white', linewidth=.3, zorder=4)
        label = f'{lo:,}–{hi-1:,.0f}' if hi != float('inf') else '10 000 и больше'
        if lo == 0:
            label = 'меньше 500'
        handles.append(Line2D([], [], marker='o', ls='', ms=size**.5, color='#789b92', label=f'Жителей (перепись-2020): {label}'.replace(',', ' ')))
    onp.plot(ax=ax, facecolor='none', edgecolor='#b9472a', markersize=85, linewidth=.9, zorder=6)
    for name, dx, dy in [('Горно-Алтайск', -70000, 15000), ('Майма', 20000, 10000), ('Кош-Агач', 12000, -10000), ('Усть-Кан', -60000, 8000)]:
        p = onp[onp['name'].str.endswith(name)].geometry.iloc[0]
        ax.annotate(name, (p.x, p.y), (p.x+dx, p.y+dy), fontsize=8, path_effects=HALO,
                    arrowprops={'arrowstyle':'-', 'color':INK, 'lw':.5}, zorder=8)
    handles.append(Line2D([], [], marker='o', ls='', ms=8, mfc='none', mec='#b9472a', label='37 опорных населенных пунктов (решение 03.11.2026)'))
    finish(fig, ax, extent, handles, basemap_alpha=.5)
    save_map(fig, OUT / 'map_04_settlement.png')

    inc = read_csv('data/dataset_v4/ndfl_mo_summary.csv')
    m = mo.merge(inc, on='mo', validate='one_to_one')
    col = 'То же на жителя в месяц, 2025, руб.'
    colors = ['#f5e1d4', '#e9b497', '#cc7854', '#993e27']
    bounds = [0, 15000, 25000, 35000, float('inf')]
    fig, ax = base()
    handles = []
    for i, color in enumerate(colors):
        q = m[(m[col] >= bounds[i]) & (m[col] < bounds[i+1])]
        if len(q):
            q.plot(ax=ax, color=color, alpha=.75, edgecolor='white', lw=.5, zorder=1)
        label = ['меньше 15', '15–25', '25–35', '35 и больше'][i]
        handles.append(Patch(facecolor=color, label=f'{label} тыс. руб./жителя в месяц'))
    for _, row in m.iterrows():
        p = row.geometry.representative_point()
        name = row['mo'].replace(' район', '').replace('г. ', '')
        if row['mo'] in ['г. Горно-Алтайск', 'Майминский район']:
            continue
        ax.text(p.x, p.y, name+'\n'+f'{row[col]/1000:.1f}'.replace('.', ','), ha='center', fontsize=7, path_effects=HALO, zorder=8)
    handles.append(Line2D([], [], color='#888888', label='Основные дороги (OSM)'))
    finish(fig, ax, extent, handles, title='Доходы по месту учета налогового агента, 2025', basemap_alpha=.5)
    save_map(fig, OUT / 'map_05_economy.png')

    okn = read_csv('data/okn/okn_by_mo_egrokn.csv')
    m = mo.merge(okn, left_on='mo', right_on='район2', validate='one_to_one')
    assert int(m['итого'].sum()) == 285  # еще 3 объекта без установленного района
    geo = gpd.read_file(ROOT / 'data/okn/egrokn_altai_points_all.geojson').to_crs(CRS)
    fig, ax = base()
    handles = []
    for lo, hi, color in [(0,20,'#e8dff0'), (20,40,'#c6afd5'), (40,100,'#926baa')]:
        q=m[(m['итого']>=lo)&(m['итого']<hi)]
        q.plot(ax=ax, color=color, alpha=.65, edgecolor='white', lw=.5, zorder=1)
        handles.append(Patch(facecolor=color,label=f'ОКН по району: {lo}–{hi-1}'))
    quality = geo['качество'].astype(str)
    a, b = geo[quality.str.startswith('A')], geo[quality.str.startswith('B')]
    assert (len(a),len(b)) == (76,91)
    a.plot(ax=ax,color='#612e78',markersize=14,marker='o',edgecolor='white',linewidth=.3,zorder=7)
    b.plot(ax=ax,color='#612e78',alpha=.3,markersize=32,marker='s',zorder=6)
    for _, row in m.iterrows():
        if row['mo'] in ['г. Горно-Алтайск','Майминский район']:
            continue
        p=row.geometry.representative_point()
        ax.text(p.x,p.y,row['mo'].replace(' район','')+'\n'+str(int(row['итого'])),ha='center',fontsize=7,path_effects=HALO,zorder=9)
    handles += [Line2D([],[],marker='o',ls='',color='#612e78',label='76 объектов: координаты ЕГРОКН (A)'),
                Line2D([],[],marker='s',ls='',color='#612e78',alpha=.4,label='91 объект: только центр НП (B)'),
                Patch(facecolor='white',edgecolor='white',label='Всего 288 ОКН; 3 без района. 121 без точки. Точки B могут совпадать.')]
    finish(fig,ax,extent,handles,basemap_alpha=.5)
    save_map(fig,OUT/'map_09_heritage.png')


if __name__ == '__main__':
    main()
