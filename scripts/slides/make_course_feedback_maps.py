"""Опорный план, дорожная сеть, межрегиональные связи и сеть команды."""

from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from maptools import HALO, INK, finish, map_figure, save_map

DATA = ROOT / 'data'
OUT = DATA / 'slides'
CRS = 32645
FEDERAL = '#ad401f'
REGIONAL = '#33637d'
TOURISM = '#853483'
ECONOMY = '#096953'
PROTECTED = '#4e9464'


def geo(path):
    return gpd.read_file(DATA / path).to_crs(CRS)


def points(table):
    return gpd.GeoDataFrame(
        table, geometry=gpd.points_from_xy(table.longitude, table.latitude), crs=4326
    ).to_crs(CRS)


def symbol(marker, color, label, fill=None):
    return Line2D([], [], marker=marker, ls='', ms=6, mec=color, mfc=fill or color, label=label)


def mark(ax, geometry, label, color=INK, marker='o', offset=(4, 4), size=23):
    ax.scatter(geometry.x, geometry.y, marker=marker, s=size, color=color,
               edgecolors='white', linewidths=.65, zorder=8)
    if label:
        ax.annotate(label, (geometry.x, geometry.y), xytext=offset, textcoords='offset points',
                    color=color, fontsize=7.3, path_effects=HALO,
                    ha='right' if offset[0] < 0 else 'left', zorder=10)


def main():
    border = geo('access_inputs/altai_boundary.geojson')
    mo = geo('slides/layers/mo_boundaries.geojson')
    roads = geo('slides/layers/roads_main.geojson')
    federal = roads.ref.fillna('').str.contains('Р-256', regex=False)
    axes = geo('model/layers/axes_secondary.geojson')
    st = points(pd.read_csv(DATA / 'dataset_v3/settlements.csv', sep=';'))
    names = st.set_index('settlement').geometry
    onp = points(pd.read_csv(DATA / 'onp_candidates.csv'))
    x0, y0, x1, y1 = border.total_bounds
    interior = (x0 - 26000, y0 - 24000, x1 + 24000, y1 + 27000)
    road_keys = [
        Line2D([], [], color=FEDERAL, lw=1.8, label='Р-256 и федеральный подъезд к Телецкому озеру'),
        Line2D([], [], color=REGIONAL, lw=1.1, label='Основные региональные направления'),
        Line2D([], [], color='#9c9893', lw=.7, label='Другие магистральные дороги OSM'),
    ]

    def base(external=False):
        fig, ax = map_figure()
        if external:
            view = box(x0 - 180000, y0 - 90000, x1 + 120000, y1 + 155000)
            neighbors = geo('slides/layers/neighbors_admin1.geojson').clip(view)
            neighbors.boundary.plot(ax=ax, color='#898682', lw=.55, ls='--', zorder=1)
            geo('slides/layers/r256_barnaul.geojson').plot(ax=ax, color=FEDERAL, lw=1.65, zorder=4)
        else:
            mo.boundary.plot(ax=ax, color='#8b8a83', lw=.45, zorder=1)
        connector = roads.ref.fillna('').str.contains('84К-102|32[КР]-589')
        roads[~(federal | connector)].plot(ax=ax, color='#9c9893', lw=.65, zorder=2)
        roads[connector].plot(ax=ax, color=REGIONAL, lw=1.1, zorder=3)
        axes.plot(ax=ax, color=REGIONAL, lw=1.1, zorder=3)
        roads[federal].plot(ax=ax, color=FEDERAL, lw=1.65, zorder=4)
        border.boundary.plot(ax=ax, color=INK, lw=.95, zorder=2)
        return fig, ax

    def save(fig, ax, extent, handles, name):
        finish(fig, ax, extent, handles, basemap_alpha=.5)
        save_map(fig, OUT / f'map_{name}.png')

    def settlement(name):
        return names.loc['г. Горно-Алтайск' if name == 'Горно-Алтайск' else f'село {name}']

    fig, ax = base()
    for name, offset in {
        'Горно-Алтайск': (-5, 8), 'Чемал': (4, -10), 'Турочак': (-5, 6),
        'Артыбаш': (4, -8), 'Усть-Кан': (-4, 5), 'Онгудай': (4, 4),
        'Усть-Кокса': (-4, -10), 'Акташ': (-5, 8), 'Улаган': (4, 6),
        'Кош-Агач': (-6, 5), 'Чоя': (-4, 9),
    }.items():
        mark(ax, settlement(name), name, offset=offset)
    save(fig, ax, interior, road_keys + [symbol('o', INK, 'Населенный пункт / развилка')],
         'roads_course')

    fig, ax = base()
    st.plot(ax=ax, color='#77877f', markersize=st.population.clip(lower=1).pow(.48)*.36,
            alpha=.68, zorder=5)
    for name, label, offset in [
        ('Горно-Алтайск', 'Горно-Алтайск — Майма', (-4, 10)),
        ('Усть-Кан', 'Усть-Кан', (-5, 5)), ('Онгудай', 'Онгудай', (4, 5)),
        ('Усть-Кокса', 'Усть-Кокса', (-4, -10)), ('Кош-Агач', 'Кош-Агач', (-5, 6)),
    ]:
        mark(ax, settlement(name), label, ECONOMY, 's', offset, 38)
    for name, label, offset in [
        ('Манжерок', 'Курорт «Манжерок»', (-8, -5)), ('Чемал', 'Чемал', (6, -6)),
        ('Артыбаш', 'Артыбаш — Иогач', (4, 4)),
        ('Тюнгур', 'Тюнгур / Белуха', (4, 4)), ('Акташ', 'Акташ / Чуйский тракт', (-5, 5)),
    ]:
        mark(ax, settlement(name), label, TOURISM, '^', offset, 43)
    save(fig, ax, interior, road_keys + [
        symbol('o', '#77877f', 'Населенные пункты; размер по населению (перепись-2020)'),
        symbol('s', ECONOMY, 'Экономический и сервисный узел'),
        symbol('^', TOURISM, 'Курорт / туристический узел (привязка к НП)'),
    ], 'support_plan')

    fig, ax = base()
    st.plot(ax=ax, color='#8e948f', markersize=5, alpha=.55, zorder=5)
    official = pd.read_csv(OUT / 'onp_decree_222.csv', dtype={'oktmo': str})
    official = official.merge(st.assign(oktmo=st.oktmo.astype(str)), on='oktmo',
                                validate='one_to_one', how='left', indicator=True)
    assert (official._merge == 'both').all(), 'Не все ОНП сопоставлены по ОКТМО'
    official = gpd.GeoDataFrame(official, geometry='geometry', crs=CRS)
    additions = onp[~onp.oktmo.astype(str).isin(official.oktmo)]
    capital = additions[additions.oktmo.eq(84701000001)]
    rural = additions.drop(capital.index)
    official.plot(ax=ax, color=ECONOMY, markersize=32, edgecolor='white', lw=.5, zorder=7)
    onp_key = [symbol('o', ECONOMY, 'Сельский ОНП по постановлению № 222'),
               symbol('o', FEDERAL, 'Дополнительный сельский пункт команды', 'white'),
               symbol('s', REGIONAL, 'Горно-Алтайск, городское ядро')]
    export_comparison(official, onp, additions)
    rural.plot(ax=ax, facecolor='none', edgecolor=FEDERAL, markersize=46, lw=1.1, zorder=6)
    capital.plot(ax=ax, color=REGIONAL, marker='s', markersize=32, edgecolor='white', lw=.6, zorder=8)
    for name, offset in {
        'Горно-Алтайск': (8, -7), 'Майма': (-6, 8), 'Манжерок': (-6, -3),
        'Элекмонар': (5, 6), 'Беляши': (-6, 5), 'Балыкча': (5, 5),
    }.items():
        p = onp.loc[onp['name'].str.endswith(name), 'geometry'].iloc[0]
        ax.annotate(name, (p.x, p.y), xytext=offset, textcoords='offset points',
                    fontsize=7.3, ha='right' if offset[0] < 0 else 'left',
                    path_effects=HALO, zorder=10)
    save(fig, ax, interior, onp_key + [symbol('o', '#8e948f', 'Другие населенные пункты')]
         + road_keys, 'onp_course')

    fig, ax = base(external=True)
    for lon, lat, label in [
        (84.95, 53.17, 'АЛТАЙСКИЙ КРАЙ'), (87.20, 52.96, 'КУЗБАСС'),
        (89.52, 50.85, 'ТЫВА'), (90.05, 52.06, 'ХАКАСИЯ'),
        (83.96, 49.77, 'КАЗАХСТАН'), (88.64, 49.06, 'МОНГОЛИЯ'),
    ]:
        point = points(pd.DataFrame({'longitude': [lon], 'latitude': [lat]})).geometry.iloc[0]
        ax.text(point.x, point.y, label, color='#52514e', fontsize=7.4, ha='center',
                path_effects=HALO, clip_on=True, zorder=4)
    protected = geo('oopt/oopt_oczk_2026-10-28.geojson')
    katun = protected[protected['name'].eq('Катунский')]
    assert len(katun) == 1
    katun.plot(ax=ax, color=PROTECTED, edgecolor=ECONOMY, alpha=.76, lw=.7, zorder=3)
    outside = points(pd.read_csv(OUT / 'interregional_points.csv'))
    for row in outside.itertuples():
        style = {
            'airport': (REGIONAL, '^', 40), 'hub': (REGIONAL, 's', 30),
            'settlement': (INK, 'o', 15), 'protected': (ECONOMY, 'D', 30),
            'checkpoint': (FEDERAL, 'D', 30),
        }[row.kind]
        mark(ax, row.geometry, row.label.replace('|', '\n'), style[0], style[1],
             (row.dx, row.dy), style[2])
    save(fig, ax, (x0-140000, y0-65000, x1+105000, y1+162000), road_keys + [
        symbol('^', REGIONAL, 'Аэропорт'), symbol('s', REGIONAL, 'Транспортный узел'),
        symbol('o', INK, 'Населенный пункт'), symbol('D', FEDERAL, 'Пункт пропуска'),
        Patch(facecolor=PROTECTED, label='Катунский заповедник (контур)'),
        symbol('D', ECONOMY, 'Катон-Карагайский НП (точка); вместе — резерват «Большой Алтай»'),
        Line2D([], [], color='#898682', lw=.55, ls='--', label='Внешние административные границы'),
    ], 'interregional')


def export_comparison(official, onp, additions):
    both = official.oktmo.isin(onp.oktmo.astype(str))
    result = pd.concat([
        official[['oktmo', 'settlement', 'mo', 'pdf_page']].assign(
            status=both.map({True: 'оба перечня', False: 'только постановление № 222'})
        ),
        additions.rename(columns={'name': 'settlement'})[['oktmo', 'settlement', 'mo', 'основание']]
        .assign(status=additions.oktmo.eq(84701000001).map(
            {True: 'городское ядро команды', False: 'дополнительный сельский пункт команды'}
        )),
    ], ignore_index=True)
    result['pdf_page'] = result.pdf_page.astype('Int64')
    result.to_csv(OUT / 'onp_comparison.csv', index=False)


if __name__ == '__main__':
    main()
