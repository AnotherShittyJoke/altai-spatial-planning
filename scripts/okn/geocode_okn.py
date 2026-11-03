"""Геокодирование ОКН РА из вырезки ЕГРОКН без координат.

Уровни качества:
  A — точка из ЕГРОКН (поле «На карте», 76 объектов);
  B — центр населённого пункта, восстановленного из адреса (офлайн-сопоставление
      с 247 НП из data/dataset_v3/settlements.csv);
  X — без точки: адреса нет (федеральная археология), объект остаётся на уровне района.
Оверпас из этой среды недоступен (overpass-api.de — 406, зеркало mail.ru — обрыв TLS),
поэтому уровень C (сопоставление с OSM) не выполняется.

Запуск:  python scripts/okn/geocode_okn.py
Выход:   data/okn/egrokn_altai_geocoded.csv (все 288),
         data/okn/egrokn_altai_points_all.geojson (A + B, со столбцом «качество»).
"""
import json
import re
from pathlib import Path

import pandas as pd
from shapely.geometry import Point

R = Path(__file__).resolve().parents[2]
SRC = R / "data/okn/egrokn_altai.csv"
SETTS = R / "data/dataset_v3/settlements.csv"
OUT_CSV = R / "data/okn/egrokn_altai_geocoded.csv"
OUT_GEO = R / "data/okn/egrokn_altai_points_all.geojson"

NP_WORDS = r"(?:село|сел[оa]|с\.|город|г\.|поселок|пос\.|п\.|населённ\w+|населенн\w+|деревня|д\.)"
NP_WORD_RE = re.compile(NP_WORDS + r"\s+([A-Za-zА-Яа-яЁё][\w\-]+)", re.I)


def norm(s: str) -> str:
    return str(s).lower().replace("ё", "е").replace(" - ", "-").strip()


def main() -> None:
    rows = pd.read_csv(SRC, encoding="utf-8-sig", dtype=str).fillna("")
    setts = pd.read_csv(SETTS, sep=";")
    # короткое имя НП -> (полное, район, lat, lon); сортировка по убыванию длины —
    # чтобы «Верх-Бийск» побеждал «Бийск»-подобные совпадения
    sett_list = []
    for _, s in setts.iterrows():
        short = re.sub(r"^(село|с\s|с\.\s*|город|г\s|г\.\s*|поселок|п\s|п\.\s*)\s*", "", str(s["settlement"]), flags=re.I)
        sett_list.append((norm(short), str(s["settlement"]), str(s["mo"]), s["latitude"], s["longitude"]))
    sett_list.sort(key=lambda x: -len(x[0]))

    def find_in(text: str):
        """НП в тексте адреса: сначала явные «село/г./п. X», затем вхождение имени.
        Фрагменты «X сельское поселение» вырезаются — это названия поселений, а не НП."""
        n = norm(text)
        n = re.sub(r"[а-яё\-]+ сельское поселение", " ", n)
        for m in NP_WORD_RE.finditer(text):
            cand = norm(m.group(1))
            for short, full, mo, lat, lon in sett_list:
                if len(cand) >= 4 and (cand == short or (len(short) >= 4 and short.startswith(cand))):
                    return full, mo, lat, lon
        for short, full, mo, lat, lon in sett_list:
            if len(short) >= 4 and short in n:
                return full, mo, lat, lon
        return None

    quality, np_name, lat_out, lon_out = [], [], [], []
    for _, r in rows.iterrows():
        if r["lat"] and r["lon"]:                       # A: точка из ЕГРОКН
            quality.append("A: точка из ЕГРОКН")
            np_name.append("")
            lat_out.append(r["lat"]); lon_out.append(r["lon"])
            continue
        hit = find_in(r["адрес"]) if r["адрес"].strip() else None
        if hit and str(hit[2]) not in ("", "nan"):
            quality.append("B: центр НП по адресу")
            np_name.append(hit[0])
            lat_out.append(hit[2]); lon_out.append(hit[3])
        else:
            quality.append("X: без точки (уровень района)")
            np_name.append("")
            lat_out.append(""); lon_out.append("")

    out = rows.copy()
    out["качество_гео"], out["НП_гео"] = quality, np_name
    out["lat"], out["lon"] = lat_out, lon_out
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    pts = out[out["качество_гео"] != "X: без точки (уровень района)"]
    feats = [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
         "properties": {"название": r["название"], "категория": r["категория"],
                        "район": r["район"], "качество": r["качество_гео"], "НП": r["НП_гео"]}}
        for _, r in pts.iterrows()
    ]
    OUT_GEO.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    print(f"A (точка ЕГРОКН): {sum(q.startswith('A') for q in quality)}")
    print(f"B (центр НП по адресу): {sum(q.startswith('B') for q in quality)}")
    print(f"X (без точки): {sum(q.startswith('X') for q in quality)}")
    print(f"итого с точкой: {len(feats)} из {len(out)}")
    print("\nпримеры сопоставлений уровня B:")
    for _, r in out[out["качество_гео"].str.startswith("B")].head(10).iterrows():
        print(f"  {r['название'][:45]:47} -> {r['НП_гео']} ({r['район']})")
    print("\nсохранили:", OUT_CSV.name, OUT_GEO.name)


if __name__ == "__main__":
    main()
