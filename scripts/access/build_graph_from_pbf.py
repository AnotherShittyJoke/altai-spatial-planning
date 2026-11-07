"""Построить горный граф из локальной выгрузки OSM, когда Overpass недоступен."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def extract(pbf, output):
    import osmium

    excluded = {
        "abandoned", "bridleway", "bus_guideway", "construction", "corridor", "cycleway",
        "elevator", "escalator", "footway", "no", "path", "pedestrian", "planned", "platform",
        "proposed", "raceway", "razed", "service", "steps",
    }

    class Roads(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways = []
            self.count = Counter()

        def way(self, way):
            tags = dict(way.tags)
            road = tags.get("highway")
            if not road or road in excluded or tags.get("area") == "yes":
                return
            if (tags.get("access") == "private" or tags.get("tracktype") == "grade5"
                    or tags.get("motor_vehicle") == "no" or tags.get("motorcar") == "no"):
                return
            try:
                seq = [(node.ref, node.lon, node.lat) for node in way.nodes]
            except osmium.InvalidLocationError:
                return
            if len(seq) < 2:
                return
            self.count.update(node[0] for node in seq)
            keep = ("highway", "surface", "tracktype", "smoothness", "name", "ref",
                    "oneway", "junction", "maxspeed")
            self.ways.append((way.id, {k: tags[k] for k in keep if k in tags}, seq))

    roads = Roads()
    roads.apply_file(str(pbf), locations=True, idx="flex_mem")
    with output.open("w", encoding="utf-8") as dest:
        for osm_id, tags, seq in roads.ways:
            start = 0
            for j in range(1, len(seq)):
                if j == len(seq) - 1 or roads.count[seq[j][0]] > 1:
                    print(json.dumps([osm_id, tags, seq[start:j+1]], ensure_ascii=False), file=dest)
                    start = j


def build(roads, folder):
    import geopandas as gpd
    import iduedu as ie
    from shapely.geometry import LineString, Point

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "relief"))
    from mountain_speed import HIGHWAY_KMH, adjust_graph

    nodes, edges = {}, []
    with roads.open(encoding="utf-8") as source:
        for line in source:
            _, tags, seq = json.loads(line)
            direction = tags.get("oneway")
            if direction == "-1":
                seq.reverse()
            u, v = seq[0][0], seq[-1][0]
            if u == v:
                continue
            nodes[u], nodes[v] = Point(seq[0][1:]), Point(seq[-1][1:])
            oneway = direction in {"yes", "1", "true", "-1"} or (
                tags.get("junction") == "roundabout" and direction != "no"
            )
            edges.append(dict(u=u, v=v, highway=tags["highway"], surface=tags.get("surface"),
                              tracktype=tags.get("tracktype"), oneway=oneway,
                              geometry=LineString([node[1:] for node in seq])))
    nodes = gpd.GeoDataFrame(geometry=gpd.GeoSeries(nodes, crs=4326), crs=4326).to_crs(32645)
    nodes.index.name = "id"
    edges = gpd.GeoDataFrame(edges, crs=4326).to_crs(32645)
    edges = edges[edges.length.gt(0)].copy()
    edges["k"] = edges.groupby(["u", "v"]).cumcount()
    edges["length_meter"] = edges.length
    edges["time_min"] = edges.length_meter / (edges.highway.map(HIGHWAY_KMH).fillna(40) * 1000 / 60)
    graph = ie.UrbanGraph(nodes, edges, is_multigraph=True, is_directed=True,
                          edge_direction_column="oneway", crs=32645, graph_type="drive")
    folder.mkdir(parents=True, exist_ok=True)
    mountain, report = adjust_graph(graph, dem_dir=folder / "dem")
    mountain.write(folder / "offline_mountain.urbangraph")
    print(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)
    extraction = steps.add_parser("extract")
    extraction.add_argument("pbf", type=Path)
    extraction.add_argument("roads", type=Path)
    building = steps.add_parser("build")
    building.add_argument("roads", type=Path)
    building.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.step == "extract":
        extract(args.pbf, args.roads)
    else:
        build(args.roads, args.folder)


if __name__ == "__main__":
    main()
