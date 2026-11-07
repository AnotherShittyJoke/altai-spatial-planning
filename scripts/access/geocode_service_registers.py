"""Сверка рабочих реестров с региональным каталогом, ФРМО и адресами OSM."""
import argparse
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
INP = DATA / "access_inputs"
CRS = 32645
SITE = re.compile(r'"(?:website|contact:website)"=>"([^"]+)"')
TAG = re.compile(r'"([^"]+)"=>"([^"]*)"')
LOCALITY_ALIASES = {
    ("устьканский", "белоануй"): "белыйануй",
    ("устьканский", "турота"): "турата",
    ("устькоксинский", "верхнийуймон"): "верхуймон",
    ("шебалинский", "дьектиек"): "дъектиек",
    ("шебалинский", "шыргайта"): "шыргайту",
    ("онгудайский", "туэкта"): "туекта",
    ("онгудайский", "кара-коба"): "кара-кобы",
}


def norm(value):
    return re.sub(r"[^a-zа-я0-9]+", "", str(value or "").lower().replace("ё", "е"))


def locality(value):
    return norm(re.sub(r"^(?:село|город|поселок|с\.|г\.|п\.)\s*", "", value, flags=re.I))


def district(value):
    return norm(re.sub(r"\s+(район|округ)$", "", value, flags=re.I).removeprefix("г. "))


def street(value):
    value = re.sub(r"\b(пр-кт|улица|ул|проспект|пр|просп|переулок|пер|тракт|шоссе|ш|площадь|пл)\b\.?\s*",
                   "", value, flags=re.I)
    return norm(value)


def house(value):
    value = re.sub(r"^(?:д|дом|здание|зд)\b\.?\s*", "", value.strip(), flags=re.I)
    return re.sub(r"[^a-zа-я0-9/]", "", value.lower())


def address_key(value):
    value = re.sub(r'(\d)\s*[,"]?\s*[«"]?([а-яa-z])[»"]?\s*$', r"\1\2", value.strip(), flags=re.I)
    chunks = [p.strip().rstrip(".;") for p in value.split(",") if p.strip()]
    if len(chunks) < 2:
        return "", ""
    number = re.search(r"(?:^|\b(?:д|дом|зд|здание)\.?\s*)(\d+[а-яa-z]?(?:/\d+[а-яa-z]?)?)$",
                       chunks[-1], re.I)
    if number:
        street_part = re.split(r"\b(?=ул\.|улица\b|пер\.|переулок\b|пр\.|проспект\b)",
                               chunks[-2], flags=re.I)[-1]
        return street(street_part), house(number.group(1))
    combined = re.fullmatch(r"(.+?)\s+(?:(?:д|дом|зд|здание)\.?\s*)?(\d+[а-яa-z]?(?:/\d+[а-яa-z]?)?)",
                            chunks[-1], re.I)
    if not combined:
        return "", ""
    street_part = re.split(r"\b(?=ул\.|улица\b|пер\.|переулок\b|пр\.|проспект\b)",
                           combined[1], flags=re.I)[-1]
    return street(street_part), house(combined[2])


def host(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


def feature_kind(name, tags, amenity):
    amenity = amenity or tags.get("amenity", "")
    if amenity == "school":
        return "school"
    if amenity in {"clinic", "hospital", "doctors"} or tags.get("healthcare") in {
        "clinic", "hospital", "doctor", "doctors"
    } or re.search(r"\bфап\b|фельдшер|амбулатор", name, re.I):
        return "medical"
    return ""


def osm_features(pbf):
    frames = []
    for layer in ("points", "multipolygons"):
        where = ("other_tags LIKE '%addr:housenumber%' OR other_tags LIKE '%healthcare%' "
                 "OR other_tags LIKE '%amenity%school%'")
        if layer == "multipolygons":
            where += " OR amenity IN ('school','clinic','hospital','doctors')"
        d = pyogrio.read_dataframe(pbf, layer=layer, where=where)
        if layer == "multipolygons":
            d["osm_ref"] = d.osm_way_id.map(lambda x: "w" + str(x) if pd.notna(x) else "")
            d.loc[d.osm_ref.eq(""), "osm_ref"] = "r" + d.loc[d.osm_ref.eq(""), "osm_id"]
            d.geometry = d.to_crs(CRS).representative_point().to_crs(4326)
        else:
            d["osm_ref"] = "n" + d.osm_id
            d["amenity"] = ""
        frames.append(d[["osm_ref", "name", "amenity", "other_tags", "geometry"]])
    osm = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326).dropna(subset=["geometry"])
    for c in ("name", "amenity", "other_tags"):
        osm[c] = osm[c].fillna("")
    tags = [dict(TAG.findall(t)) for t in osm.other_tags]
    osm["key"] = [(street(t.get("addr:street", t.get("addr:place", ""))),
                   house(t.get("addr:housenumber", ""))) for t in tags]
    osm["place_key"] = [locality(t.get("addr:city", t.get("addr:village", ""))) for t in tags]
    osm["host"] = [host(m[1]) if (m := SITE.search(t)) else "" for t in osm.other_tags]
    osm["kind"] = [feature_kind(name, t, amenity) for name, t, amenity in zip(osm.name, tags, osm.amenity)]
    osm["name_key"] = osm.name.map(norm)
    osm["obsolete"] = [any(k.startswith(("disused:", "abandoned:", "demolished:", "was:"))
                           for k in t) or t.get("disused") == "yes" for t in tags]
    return osm[~osm.obsolete].reset_index(drop=True)


def locate(row, centers, osm, projected, tree):
    center = centers.get((row.mo_key, row.place_key))
    if center is None:
        return pd.Series(dict(precision="unresolved"))
    radius = 11500 if row.place_key == "горноалтайск" else 3800
    nearby = osm.iloc[tree.query_ball_point([center.mx, center.my], radius)]
    valid_locality = nearby.place_key.isin(["", row.place_key, center.place_key])
    nearby = nearby[valid_locality]
    addr = nearby.loc[nearby.key.map(lambda key: key == row.addr_key).astype(bool)] if all(row.addr_key) else nearby.iloc[:0]
    active = nearby[nearby.kind.eq(row.service)]
    candidates = addr[addr.kind.eq(row.service)]
    method = "osm_facility_address"
    if candidates.empty:
        candidates = addr
        method = "osm_address"
    if candidates.empty:
        method = "osm_facility_name"
        name_key = norm(re.split(r"[(,]", row["name"], maxsplit=1)[0])
        candidates = active[active.name_key.eq(name_key)]
    if candidates.empty and row.service == "school" and row.role == "Основная организация / корпус":
        method = "osm_facility_website"
        candidates = active[active.host.eq(host(row.site))] if host(row.site) else active.iloc[:0]
    if not candidates.empty:
        pts = projected.loc[candidates.index]
        if len(pts) == 1 or pts.distance(pts.iloc[0]).max() <= 85:
            hit = candidates.sort_values("osm_ref").iloc[0]
            return pd.Series(dict(precision=method, longitude=hit.geometry.x, latitude=hit.geometry.y,
                                  osm_ref=hit.osm_ref, osm_name=hit["name"]))
    return pd.Series(dict(precision="settlement_center", longitude=center.longitude,
                          latitude=center.latitude))


def medical_status(row, frmo):
    if row.role == "План СТП":
        return "plan_stp"
    if not all(row.addr_key):
        return "tfoms_only"
    pool = frmo[frmo.mo_key.eq(row.mo_key) & frmo.addr_key.map(lambda key: key == row.addr_key)]
    place = norm(row.place)
    pool = pool[pool.address_normalized.str.contains(place, regex=False)] if place else pool.iloc[:0]
    family = "ФАП" if row.role in {"ФАП", "ФП"} else (
        "амбулатория" if row.role == "Врачебная амбулатория" else "больница/центр"
    )
    pool = pool[pool["тип"].eq(family)]
    if pool.empty:
        return "tfoms_only"
    if pool.действует.all():
        return "tfoms_frmo_active"
    return "tfoms_frmo_conflict"


def school_check(row, pages):
    """Проверка конкретного адреса на сайте. Наличие ссылки на лицензию не доказывает ее статус."""
    if pages is None:
        return "school_parent_in_obr04", ""
    from bs4 import BeautifulSoup

    file = pages / (hashlib.sha256(row.source.encode()).hexdigest()[:16] + ".html")
    if not file.exists():
        return "school_page_unavailable", ""
    page = BeautifulSoup(file.read_text(), "html.parser")
    base = page.find("base", href=True)
    if base is None or host(base["href"]) != host(row.source):
        return "school_page_unavailable", ""
    if row.role == "Филиал":
        addresses = [
            cell.get_text(" ", strip=True)
            for branch in page.select('[itemprop="filInfo"]')
            if (name := branch.select_one('[itemprop="nameFil"]')) is not None
            and re.search(r"школ|лице|гимнази|\bНОШ\b|\bООШ\b|\bСОШ\b", name.get_text(" "), re.I)
            for cell in branch.select('[itemprop="addressFil"]')
        ]
    elif row.role == "Дополнительный корпус":
        addresses = [n.get_text(" ", strip=True) for n in page.select('[itemprop="addressStr"]')]
    else:
        addresses = [n.get_text(" ", strip=True) for n in page.select('[itemprop="address"]')]
    place = norm(row.place.removeprefix("с. ").removeprefix("г. ").removeprefix("п. "))
    local = list(dict.fromkeys(a for a in addresses if place and place in norm(a)))
    if not local and len(set(addresses)) == 1 and row.role == "Основная организация / корпус":
        local = list(set(addresses))
    for address in local:
        if all(row.addr_key):
            street_id, house_id = row.addr_key
            raw_house = re.search(r"(\d+\s*(?:[а-яa-z]|/\s*\d+)?)[.\s]*$", row.address.lower())
            number = raw_house[1] if raw_house else house_id
            number = re.escape(number.strip()).replace(r"\ ", r"\s*")
            number = re.sub(r"(?<=\d)(?=[а-яa-z])",
                            lambda _: r'[\s,.«"»]*(?:д[,.\s]+ст[,.\s]+)?', number)
            stem = r"[^а-яa-z0-9]*".join(map(re.escape, street_id))
            marker = r"[\s,.№]*(?:(?:ул(?:ица)?|пр(?:-кт|оспект)?|пер(?:еулок)?|д(?:ом)?|зд(?:ание)?)\b[\s,.№]*)*"
            matches = re.search(r"(?<![а-яa-z])" + stem + marker + number + r"(?![а-яa-z0-9/])",
                                address.lower().replace("ё", "е"))
            if address_key(address) == row.addr_key or matches:
                return "school_address_confirmed", " / ".join(row.addr_key).strip(" /")
        corpus = re.search(r"(\d+)\s*(?:к[.]?|корпус)\s*(\d+)\s*$", row.address, re.I)
        if corpus:
            n, k = corpus.groups()
            details = rf"{n}\s*(?:к[.]?|корпус)\s*{k}\b"
            if re.search(details, address, re.I):
                return "school_address_confirmed", " / ".join(row.addr_key).strip(" /")
        if not all(row.addr_key) and place in norm(address):
            return "school_site_locality_confirmed", row.place
    if local:
        return "school_address_review", ""
    return "school_parent_in_obr04", ""


def read_registers(folder):
    school = pd.read_excel(folder / "Республика_Алтай_школы_филиалы.xlsx", dtype=str, engine="openpyxl")
    school = school.rename(columns={"Наименование":"name","Тип учреждения":"level","Статус объекта":"role",
                                    "Адрес":"address","Населённый пункт":"place","Район / город":"mo",
                                    "Источник адреса":"source","Сайт организации":"site"})
    school = school.assign(service="school", source_sheet="Школы_и_филиалы", source_row=school.index+2)
    medical = pd.read_excel(folder / "Республика_Алтай_реестр_ФАП_больниц.xlsx", sheet_name=None,
                            dtype=str, engine="openpyxl")
    frames = [school]
    for sheet, d in medical.items():
        if sheet == "План_СТП_54":
            d = d.rename(columns={"Село/место":"place","Вид объекта":"name","Район":"mo","Адрес":"address"})
            d = d.assign(role="План СТП", source="СТП Республики Алтай, прил. 4, пункт " + d["Пункт СТП"])
        elif sheet == "ФАП_ФП_ТФОМС":
            d = d.rename(columns={"Наименование и адрес":"name","Населённый пункт":"place","Район":"mo",
                                  "Адрес (из наименования)":"address","Тип":"role","Источник":"source"})
        else:
            d = d.rename(columns={"Подразделение":"name","Населённый пункт":"place","Район":"mo",
                                  "Адрес":"address","Тип":"role","Источник":"source"})
        frames.append(d.assign(service="medical",source_sheet=sheet,source_row=d.index+2))
    fields = ["service","source_sheet","source_row","name","role","level","mo","place","address","source","site"]
    return pd.concat(frames, ignore_index=True)[fields].fillna("")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workbooks", type=Path)
    p.add_argument("osm_extract", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--school-pages", type=Path)
    args = p.parse_args()
    rows = read_registers(args.workbooks)
    demand = gpd.read_file(INP / "settlements_demand.geojson")
    xy = demand.to_crs(CRS).geometry
    demand = demand.assign(mo_key=demand.mo.map(district),place_key=demand.name.map(locality),
                           mx=xy.x,my=xy.y)
    centers = {(r.mo_key,r.place_key):r for r in demand.itertuples()}
    rows["mo_key"] = rows.mo.map(district)
    rows["place_key"] = rows.place.map(locality)
    fixes = {
        ("майминский", ""): "майма",
        ("шебалинский", "малая"): "малаячерга",
        ("онгудайский", "кара-коба"): "кара-кобы",
    }
    fixes.update(LOCALITY_ALIASES)
    fixes = {(mo, norm(old)): norm(new) for (mo, old), new in fixes.items()}
    rows["place_key"] = [fixes.get((m,p),p) for m,p in zip(rows.mo_key,rows.place_key)]
    rows["routing_address"] = rows.address
    elanda = rows.source_sheet.eq("ФАП_ФП_ТФОМС") & rows.place_key.eq("еланда") & rows.mo_key.eq("чемальский")
    rows.loc[elanda, "routing_address"] = "с. Еланда, ул. Катунская, 30"
    rows["addr_key"] = rows.routing_address.map(address_key)
    frmo = pd.read_csv(INP / "medical_registry_2026_units.csv").fillna("")
    frmo = frmo.assign(mo_key=frmo.район.map(district),
                       addr_key=frmo.адрес_подразделения.map(address_key),
                       address_normalized=frmo.адрес_подразделения.map(norm))
    catalog = pd.read_csv(DATA / "education/obr04_organizations.csv", dtype=str).fillna("")
    hosts = set(catalog.сайт.map(host)) - {""}
    checks = [
        school_check(r, args.school_pages) if r.service == "school" and host(r.site) in hosts
        else ("school_source_only", "") if r.service == "school"
        else (medical_status(r, frmo), "")
        for r in rows.itertuples()
    ]
    rows[["status_check", "school_evidence_key"]] = pd.DataFrame(checks, index=rows.index)
    rows["status_source"] = ""
    rows.loc[elanda, ["status_check", "status_source"]] = [
        "tfoms_opening_confirmed", "https://zn1.roszdravnadzor.gov.ru/news/48559"
    ]
    elanda_plan = rows.role.eq("План СТП") & rows.place_key.eq("еланда") & rows.mo_key.eq("чемальский")
    rows.loc[elanda_plan, ["status_check", "status_source"]] = [
        "plan_opening_confirmed", "https://zn1.roszdravnadzor.gov.ru/news/48559"
    ]
    osm = osm_features(args.osm_extract)
    projected = osm.to_crs(CRS).geometry
    tree = cKDTree(np.c_[projected.x,projected.y])
    found = rows.apply(locate,axis=1,args=(centers,osm,projected,tree))
    out = pd.concat([rows.drop(columns=["mo_key","place_key","addr_key"]),found],axis=1)
    out.to_csv(args.output,index=False)
    print(out.groupby(["service","role","status_check","precision"]).size().to_string())


if __name__ == "__main__":
    main()
