"""Оценка доступности школ и ПМСП на одном графе для разных наборов точек."""
import argparse
from pathlib import Path

import geopandas as gpd
import iduedu as ie
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
INP = ROOT / "data" / "access_inputs"
ADDRESS_PRECISION = {"osm_facility_address", "osm_address", "osm_facility_name", "osm_facility_website"}
MAX_SNAP_M = 2000


def points(rows):
    rows = rows.dropna(subset=["longitude", "latitude"]).drop_duplicates(["longitude", "latitude"])
    return gpd.GeoDataFrame(geometry=gpd.points_from_xy(rows.longitude, rows.latitude), crs=4326)


def od_min(graph, origins, destinations, weight):
    distances = graph.od_matrix(gdf_origins=origins, gdf_destinations=destinations, weight=weight)
    if any(isinstance(dtype, pd.SparseDtype) for dtype in distances.dtypes):
        distances = distances.sparse.to_dense()
    return distances.min(axis=1).reindex(origins.index)


def aggregate(t):
    rows = []
    for mo, d in [("Республика Алтай", t), *t.groupby("mo")]:
        for scenario, z in d.groupby("scenario"):
            pop = z.pop_2025_est
            rows.append(dict(mo=mo, scenario=scenario, population=int(pop.sum()),
                             school_15km_pct=round(100*pop[z.school_km.le(15)].sum()/pop.sum(), 2),
                             school_30km_pct=round(100*pop[z.school_km.le(30)].sum()/pop.sum(), 2),
                             pmsp_30min_pct=round(100*pop[z.pmsp_min.le(30)].sum()/pop.sum(), 2),
                             school_no_route_pop=int(pop[z.school_km.isna()].sum()),
                             pmsp_no_route_pop=int(pop[z.pmsp_min.isna()].sum())))
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("graph", type=Path)
    p.add_argument("register", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()

    graph = ie.UrbanGraph.read(args.graph)
    st = gpd.read_file(INP / "settlements_demand.geojson").set_index("id")
    reg = pd.read_csv(args.register)
    school = reg[reg.service.eq("school") & ~reg.level.eq("Вечерняя школа")
                 & ~reg.status_check.eq("school_address_review")]
    pmsp = reg[reg.status_check.isin(["tfoms_frmo_active", "tfoms_only", "tfoms_opening_confirmed"])]
    hosp = gpd.read_file(INP / "hospitals_services.geojson")[["geometry"]]

    def primary_care(rows):
        return gpd.GeoDataFrame(pd.concat([points(rows), hosp], ignore_index=True), crs=4326)

    osm_schools = gpd.read_file(INP / "schools_osm.geojson")[["geometry"]]
    osm_pmsp = gpd.read_file(INP / "primary_care_osm.geojson")
    osm_pmsp = osm_pmsp[~osm_pmsp.kind.str.endswith("(план)")][["geometry"]]

    address_school = school[school.status_check.eq("school_address_confirmed")
                            & school.precision.isin(ADDRESS_PRECISION)]
    checked_pmsp = pmsp[pmsp.status_check.isin(["tfoms_frmo_active", "tfoms_opening_confirmed"]) & pmsp.precision.isin(ADDRESS_PRECISION)]
    scenarios = {
        "osm_baseline": (osm_schools, osm_pmsp),
        "registry_address_subset": (points(address_school), primary_care(checked_pmsp)),
        "registry_with_settlement_centers": (points(school), primary_care(pmsp)),
    }
    nodes = graph.nodes_gdf.geometry
    tree = cKDTree(np.c_[nodes.x, nodes.y])

    def snap_distance(d):
        xy = d.to_crs(graph.crs).geometry
        return tree.query(np.c_[xy.x, xy.y])[0]

    st["snap_m"] = snap_distance(st)
    origins = st[st.snap_m.le(MAX_SNAP_M)]
    parts = []
    for scenario, (schools, medicine) in scenarios.items():
        schools = schools.loc[snap_distance(schools) <= MAX_SNAP_M].reset_index(drop=True)
        medicine = medicine.loc[snap_distance(medicine) <= MAX_SNAP_M].reset_index(drop=True)
        t = st[["name", "mo", "pop_2025_est", "snap_m"]].copy()
        t["school_km"] = od_min(graph, origins, schools, "length_meter") / 1000
        t["pmsp_min"] = od_min(graph, origins, medicine, "time_min")
        t["scenario"] = scenario
        parts.append(t.reset_index())
        print(scenario, "school", len(schools), "pmsp", len(medicine), flush=True)

    out = pd.concat(parts, ignore_index=True)
    out.loc[~np.isfinite(out.school_km), "school_km"] = np.nan
    out.loc[~np.isfinite(out.pmsp_min), "pmsp_min"] = np.nan
    summary = aggregate(out)
    args.output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output / "register_services_by_mo.csv", index=False)
    out.round({"school_km": 3, "pmsp_min": 3, "snap_m": 1}).to_csv(
        args.output / "register_services_by_settlement.csv", index=False
    )
    print(summary.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
