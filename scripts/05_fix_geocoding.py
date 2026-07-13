import re
import time
import requests
import pandas as pd
import importlib.util
from pathlib import Path
from typing import Optional

# "02_geocode" isn't a valid module name for a plain import (leading digit),
# so load it from its file path instead.
_spec = importlib.util.spec_from_file_location(
    "geocode_overpass", str(Path(__file__).parent / "02_geocode.py")
)
_geocode_overpass = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geocode_overpass)

parse_between = _geocode_overpass.parse_between
parse_direct = _geocode_overpass.parse_direct
osm_name_variants = _geocode_overpass.osm_name_variants
_nodes_in_bbox = _geocode_overpass._nodes_in_bbox
_avg_coords = _geocode_overpass._avg_coords
OVERPASS_SLEEP = _geocode_overpass.OVERPASS_SLEEP
OVERPASS_URL = _geocode_overpass.OVERPASS_URL
HTTP_HEADERS = _geocode_overpass.HTTP_HEADERS

CSV_PATH = Path("data/final/encampment_final.csv")
BACKUP_PATH = Path("data/final/encampment_final_prefix.csv")


OAK_LAT_MIN, OAK_LAT_MAX = 37.63, 37.90
OAK_LON_MIN, OAK_LON_MAX = -122.38, -122.11
TIGHT_BBOX = f"{OAK_LAT_MIN},{OAK_LON_MIN},{OAK_LAT_MAX},{OAK_LON_MAX}"

OUTLIER_THRESHOLD = 0.01  # degrees, same threshold used in 04_validate.py


def extract_street(loc: str) -> Optional[str]:
    if pd.isna(loc):
        return None
    loc = str(loc).strip()
    m = re.match(r'^([^&@\n]+?)\s+(?:between|@|&|\bat\b)', loc, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return loc.strip().upper()


def find_flagged_rows(df: pd.DataFrame) -> set[int]:
    out_of_bbox = (
        df["latitude"].notna() & df["longitude"].notna() & (
            (df["latitude"] < OAK_LAT_MIN) | (df["latitude"] > OAK_LAT_MAX) |
            (df["longitude"] < OAK_LON_MIN) | (df["longitude"] > OAK_LON_MAX)
        )
    )
    flagged = set(df[out_of_bbox].index)

    primary_street = df["location_for_geocoding"].apply(extract_street)
    for street, grp in df[df["longitude"].notna()].groupby(primary_street):
        if len(grp) < 3:
            continue
        med_lat = grp["latitude"].median()
        med_lon = grp["longitude"].median()
        for idx, row in grp.iterrows():
            if (abs(row["longitude"] - med_lon) > OUTLIER_THRESHOLD
                    or abs(row["latitude"] - med_lat) > OUTLIER_THRESHOLD):
                flagged.add(idx)

    return flagged


def _overpass_query_bbox(q: str) -> list[dict]:
    for attempt in range(3):
        try:
            r = requests.post(
                OVERPASS_URL,
                data={"data": q},
                headers=HTTP_HEADERS,
                timeout=35,
            )
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception:
            if attempt < 2:
                time.sleep(2)
    return []


def overpass_intersection_tight(
    street1: str, street2: str, bbox: str
) -> tuple[Optional[float], Optional[float]]:
    for s1 in osm_name_variants(street1):
        for s2 in osm_name_variants(street2):
            s1e = s1.replace('"', '\\"')
            s2e = s2.replace('"', '\\"')
            q = (
                f'[out:json][timeout:30][bbox:{bbox}];'
                f'way["name"="{s1e}"]->.a;'
                f'way["name"="{s2e}"]->.b;'
                f'node(w.a)(w.b);out body;'
            )
            nodes = _nodes_in_bbox(_overpass_query_bbox(q))
            if nodes:
                return _avg_coords(nodes)
            time.sleep(OVERPASS_SLEEP)
    return None, None


def geocode_one(query: str, bbox: str) -> tuple[Optional[float], Optional[float], str]:
    """re-geocode a single location string with a tight bbox."""
    main, cross1, cross2 = parse_between(query)

    if main and cross1 and cross2:
        lat1, lon1 = overpass_intersection_tight(main, cross1, bbox)
        time.sleep(OVERPASS_SLEEP)
        lat2, lon2 = overpass_intersection_tight(main, cross2, bbox)
        time.sleep(OVERPASS_SLEEP)

        if lat1 is not None and lat2 is not None:
            return (lat1 + lat2) / 2, (lon1 + lon2) / 2, "overpass_midpoint"
        if lat1 is not None:
            return lat1, lon1, "overpass_endpoint_cross1"
        if lat2 is not None:
            return lat2, lon2, "overpass_endpoint_cross2"

    s1, s2 = parse_direct(query)
    if s1 and s2:
        lat, lon = overpass_intersection_tight(s1, s2, bbox)
        time.sleep(OVERPASS_SLEEP)
        if lat is not None:
            return lat, lon, "overpass_direct"

    return None, None, "no_result"


def run():
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows from {CSV_PATH}")

    df.to_csv(BACKUP_PATH, index=False)
    print(f"Backup saved → {BACKUP_PATH}")

    flagged_idx = find_flagged_rows(df)
    print(f"Flagged {len(flagged_idx)} rows for re-geocoding")

    # multiple rows can share the same location_for_geocoding (repeat sweeps
    # at the same site) — geocode each distinct location once and apply the
    # result to every flagged row that shares it
    flagged_df = df.loc[sorted(flagged_idx)]
    unique_queries = flagged_df["location_for_geocoding"].dropna().unique()
    total = len(unique_queries)

    results: dict[str, tuple[float, float, str]] = {}
    fixed = 0
    failed = []

    for n, query in enumerate(unique_queries):
        print(f"\n[{n+1}/{total}] {query}")
        lat, lon, source = geocode_one(query, TIGHT_BBOX)

        if lat is not None:
            results[query] = (lat, lon, source)
            print(f"  after : lat={lat:.6f}  lon={lon:.6f}  [{source}]")
            fixed += 1
        else:
            print(f"  FAILED — keeping original coords, flagging for manual review")
            failed.append(query)

    for idx in flagged_idx:
        query = df.at[idx, "location_for_geocoding"]
        if query in results:
            lat, lon, source = results[query]
            df.at[idx, "latitude"] = lat
            df.at[idx, "longitude"] = lon
            df.at[idx, "geocode_source"] = source
            df.at[idx, "geocode_notes"] = f"regeocoded_tight_bbox:{TIGHT_BBOX}"
        else:
            df.at[idx, "geocode_notes"] = "NEEDS_MANUAL_REVIEW:regeocoding_failed"

    df.to_csv(CSV_PATH, index=False)
    print(f"\n{'='*70}")
    print(f"Done. Fixed: {fixed}/{total} unique locations ({len(flagged_idx)} rows)")
    print(f"Saved → {CSV_PATH.resolve()}")

    if failed:
        print(f"\nFailed re-geocodes ({len(failed)}) — require manual fix:")
        for query in failed:
            print(f"  {query}")


if __name__ == "__main__":
    run()
