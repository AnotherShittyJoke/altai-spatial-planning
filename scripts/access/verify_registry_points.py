"""Сверка точек реестра медорганизаций (ФРМО) с соседними годами и слоем больниц.

Проверки (реестры — исходные выгрузки ФРМО, других источников ФРМО нет):
  1. Межгодовая стабильность: НП действующей точки 2026 г. также присутствует
     среди действующих точек 2025 и 2027 гг. (совпадение по НП + МО).
  2. Слой больниц hospitals_services.geojson (OSM, 11 больниц) — есть ли в реестре
     2026 г. действующая точка «больница/центр» в том же НП.

Запуск:  python scripts/access/verify_registry_points.py
Парсер — упрощённая копия логики scripts/access/medical_registries.ipynb (по названиям
колонок шапки); результаты печатаются и используются в docs/access_inputs.md.
"""
import json
import re
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parents[2]
WS = Path("/home/mfthesun/Workspace/Пространственное планирование")
REG = {2025: "Reestr-MO-v-2025-g.xlsx", 2026: "Reestr-MO-2026.xlsx", 2027: "Reestr-MO-2027.xlsx"}
MO_STEMS = ["Кош-Агачский", "Майминский", "Онгудайский", "Турочакский", "Улаганский",
            "Усть-Канский", "Усть-Коксинский", "Чемальский", "Чойский", "Шебалинский"]


def load_registry(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None, dtype=str)
    data = raw[raw[0].astype(str).str.fullmatch(r"\d+")].copy()
    data.columns = range(data.shape[1])
    return data


def col_map(path: Path) -> dict:
    hdr = pd.read_excel(path, header=None, nrows=3, dtype=str)
    m = {}
    for _, row in hdr.iterrows():
        for j, v in row.items():
            s = str(v)
            if "наименование медицинской" in s.lower(): m.setdefault("МО", j)
            if "адресах оказания медицинской" in s: m.setdefault("адрес_подр", j)
            if s.lower().startswith("адрес") and "адрес_МО" not in m and j < 20: m["адрес_МО"] = j
            if "Дата исключения" in s: m.setdefault("исключено", j)
    return m


def active_points(year: int) -> pd.DataFrame:
    """Уникальные действующие точки года: МО, адрес, НП (из адреса), район."""
    path = WS / REG[year]
    cm = col_map(path)
    dd = load_registry(path)
    addr_col = cm.get("адрес_подр", cm.get("адрес_МО"))
    u = pd.DataFrame({
        "МО": dd[cm["МО"]],
        "адрес": dd[addr_col] if addr_col is not None else "",
        "исключено": dd[cm["исключено"]] if "исключено" in cm else "",
    })
    u["адрес"] = u["адрес"].fillna("")
    u["точка"] = u["МО"].fillna("") + " @ " + u["адрес"]
    u = u.drop_duplicates("точка")
    in_ra = u["адрес"].str.contains("Респ", case=False)
    # «Действует в году N»: в форме на год N «исключено» пусто (действует сейчас),
    # либо закрыто ровно 31.12.N (перенос в форму N+1 — действовала весь год N).
    # Прочие даты исключения и артефакты — не действуют в году N.
    excl = u["исключено"]
    acted_in_year = excl.isna() | (excl.astype(str).str.strip() == "") | \
                    (excl.astype(str).str.strip() == f"31.12.{year}")
    u["действует"] = acted_in_year & in_ra
    u = u[u["действует"]].copy()
    u["район"] = u["адрес"].apply(district)
    u["НП"] = u["адрес"].apply(settlement)
    return u


def district(addr: str):
    if not isinstance(addr, str) or "Алтай" not in addr:
        return None
    seg = re.split(r"(?:Респ(?:ублика)? ?Алтай),", addr, maxsplit=1)
    if len(seg) < 2:
        return None
    d = seg[1].strip()
    if "Горно-Алтайск" in d:
        return "г. Горно-Алтайск"
    for stem in MO_STEMS:
        if stem in d:
            return stem + " район"
    return d.split(",")[0].strip() or None


def settlement(addr: str):
    """НП из адреса: «село/с./п./город/г. X» или кусок после района до запятой."""
    if not isinstance(addr, str):
        return None
    m = re.search(r"(?:село|с\.|поселок|п\.|город|г\.)\s+([A-Za-zА-Яа-яЁё][\w\-]+)", addr)
    if m:
        return m.group(1).lower().replace("ё", "е")
    seg = re.split(r"(?:Респ(?:ублика)? ?Алтай),", addr, maxsplit=1)
    if len(seg) == 2 and "Горно-Алтайск" in seg[1]:
        return "горно-алтайск"
    return None


def main() -> None:
    pts = {y: active_points(y) for y in REG}
    for y, df in pts.items():
        print(f"{y}: действующих точек {len(df)}")

    a26 = pts[2026]
    key = lambda df: set(zip(df["НП"], df["район"]))
    k25, k26, k27 = key(pts[2025]), key(a26), key(pts[2027])
    stable25 = sum(1 for k in k26 if k in k25)
    stable27 = sum(1 for k in k26 if k in k27)
    print(f"\nНП-ключей в 2026: {len(k26)}")
    print(f"из них есть в 2025: {stable25} ({100 * stable25 / len(k26):.1f}%)")
    print(f"из них есть в 2027: {stable27} ({100 * stable27 / len(k26):.1f}%)")
    only26 = sorted((str(k[0]), str(k[1])) for k in k26 if k not in k25 and k not in k27)
    print("только в 2026:", only26[:10] or "—")

    hj = json.loads((R / "data/access_inputs/hospitals_services.geojson").read_text())
    print("\nСлой больниц (OSM) vs реестр 2026:")
    matched = 0
    for f in hj["features"]:
        p = f["properties"]
        st = settlement(p.get("address", "")) or ""
        sub = a26[a26["НП"] == st]
        has_hosp = bool(sub["МО"].str.contains("больниц", case=False).any())
        matched += bool(len(sub) > 0)
        print(f"  {p['name']:30} НП={st or '—':22} точек в НП: {len(sub):2}  больница в МО: {'да' if has_hosp else '—'}")
    print(f"больниц с действующей точкой в своём НП по реестру: {matched} из {len(hj['features'])}")


if __name__ == "__main__":
    main()
