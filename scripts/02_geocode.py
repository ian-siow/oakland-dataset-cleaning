"""
geocoding oakland encampements using overpass API

"X between A and B" -> finds X∩A and X∩B intersection nodes via
OSM road topology and returns their midpoint

"X and Y" -> finds shared nodes between direct intersections 

for addresses and named places use Nominatim 

"""

import re
import time
import requests
import pandas as pd
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from typing import Optional

INPUT_CSV  = Path("data/intermediate/encampment_to_geocode.csv")
OUTPUT_CSV = Path("data/intermediate/encampment_geocoded_coords.csv")
Path("data/intermediate").mkdir(exist_ok=True)

OVERPASS_URL  = "https://overpass-api.de/api/interpreter"
OVERPASS_BBOX = "37.68,-122.55,37.90,-122.10"   
OVERPASS_SLEEP = 1.1                              
NOMINATIM_SLEEP = 1.1
CHECKPOINT_EVERY = 50
NOMINATIM_UA = "oakland_emt_encampment_research"
VIEWBOX = [(37.90, -122.55), (37.68, -122.10)]
HTTP_HEADERS = {
    "User-Agent": "oakland_emt_encampment_research/1.0",
    "Content-Type": "application/x-www-form-urlencoded",
}

# bounding used to ensure coordinates are in the oakland area
LAT_MIN, LAT_MAX = 37.60, 38.00
LON_MIN, LON_MAX = -122.60, -121.90


def _mlk_variants() -> list[str]:
    """ defines the variants of Martin Luther King Junior Way/Drive that exists in Oakland"""
    return [
        "Martin Luther King Junior Way",
        "Martin Luther King Junior Drive",
    ]

_ABBR_TO_FULL = {
    "st": "Street", "ave": "Avenue", "blvd": "Boulevard",
    "rd": "Road", "dr": "Drive", "pl": "Place",
    "ct": "Court", "ln": "Lane", "pkwy": "Parkway", "hwy": "Highway",
}

_KNOWN_SUFFIXES_LC = frozenset({
    "street", "avenue", "boulevard", "road", "drive", "place",
    "court", "lane", "parkway", "highway", "way", "circle",
    "terrace", "trail", "path", "alley",
})


_SPECIFIC_CORRECTIONS = {
    "San Pablo Street":       "San Pablo Avenue",
    "Bancroft Boulevard":     "Bancroft Avenue",
    "West Macarthur":         "West MacArthur",   
}

def _normalize_name(name: str) -> str:
    """
    fixes common abbreviation and formatting issues before OSM lookup:
    1. strip trailing punctuation ("39th Street." → "39th Street")
    2. split CamelCase run-ons ("2ndSt" → "2nd St", "E18th" → "E 18th")
    3. expand abbreviations ("Clay st" → "Clay Street")
    4. title-case lowercase known suffix ("Dover street" → "Dover Street")
    """
    name = name.rstrip(".,")
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = re.sub(r"\b([A-Z])(\d)", r"\1 \2", name)

    tokens = name.split()
    if not tokens:
        return name

    last = tokens[-1].rstrip(".,")
    last_lower = last.lower()

    if last_lower in _ABBR_TO_FULL and not re.search(r"\d", last):
        tokens[-1] = _ABBR_TO_FULL[last_lower]
    elif last_lower in _KNOWN_SUFFIXES_LC and last[0].islower():
        tokens[-1] = last.title()

    return " ".join(tokens)

def osm_name_variants(name: str) -> list[str]:
    """
    return a prioritised list of OSM name candidates for a given street name.
    the first hit wins in overpass_intersection().
    """
    name = name.strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

    normalized = _normalize_name(name)
    variants: list[str] = [normalized]
    if name != normalized and name not in variants:
        variants.append(name)

    for wrong, right in _SPECIFIC_CORRECTIONS.items():
        if wrong.lower() in normalized.lower():
            corrected = re.sub(re.escape(wrong), right, normalized, flags=re.I)
            if corrected not in variants:
                variants.insert(0, corrected)   


    if re.search(r"Martin Luther King", normalized, re.I):
        for v in _mlk_variants():
            if v not in variants:
                variants.append(v)
        return variants

    if re.match(r"^E\s+\d", normalized):
        alt = "East " + normalized[2:]
        if alt not in variants:
            variants.append(alt)
    elif normalized.startswith("East "):
        alt = "E " + normalized[5:]
        if alt not in variants:
            variants.append(alt)

    if re.match(r"^W\s+", normalized) and not normalized.startswith("West"):
        alt = "West " + normalized[2:]
        if alt not in variants:
            variants.append(alt)
    elif normalized.startswith("West ") and not re.match(r"^West\s+\d", normalized):
        alt = "W " + normalized[5:]
        if alt not in variants:
            variants.append(alt)

    if re.match(r"^\d+(?:st|nd|rd|th)$", normalized, re.I):
        variants.append(normalized + " Avenue")
        variants.append(normalized + " Street")
        return variants

    norm_tokens = normalized.split()
    if norm_tokens and norm_tokens[-1].lower() not in _KNOWN_SUFFIXES_LC:
        for suffix in ("Avenue", "Street", "Boulevard", "Way"):
            candidate = normalized + " " + suffix
            if candidate not in variants:
                variants.append(candidate)

    return variants

def _overpass_query(q: str) -> list[dict]:
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


def _nodes_in_bbox(elements: list[dict]) -> list[dict]:
    return [
        e for e in elements
        if e.get("type") == "node"
        and LAT_MIN < e["lat"] < LAT_MAX
        and LON_MIN < e["lon"] < LON_MAX
    ]

def _avg_coords(nodes: list[dict]) -> tuple[Optional[float], Optional[float]]:
    if not nodes:
        return None, None
    return (
        sum(n["lat"] for n in nodes) / len(nodes),
        sum(n["lon"] for n in nodes) / len(nodes),
    )


def overpass_intersection(
    street1: str, street2: str
) -> tuple[Optional[float], Optional[float]]:
    """
    returns the averaged lat/lon of all shared nodes between street1 and
    street2 within Oakland.  tries name variants for both streets.
    """
    for s1 in osm_name_variants(street1):
        for s2 in osm_name_variants(street2):
            s1e = s1.replace('"', '\\"')
            s2e = s2.replace('"', '\\"')
            q = (
                f'[out:json][timeout:30][bbox:{OVERPASS_BBOX}];'
                f'way["name"="{s1e}"]->.a;'
                f'way["name"="{s2e}"]->.b;'
                f'node(w.a)(w.b);out body;'
            )
            nodes = _nodes_in_bbox(_overpass_query(q))
            if nodes:
                return _avg_coords(nodes)
            time.sleep(OVERPASS_SLEEP)
    return None, None

_CITY_SUFFIX = re.compile(r",\s*Oakland,\s*CA\s*$", re.I)
_NOISE_PREFIX = re.compile(
    r"^(?:median\s+at|cul[\s-]de[\s-]sac\s+at|along|near)\s+", re.I
)
_PAREN = re.compile(r"\s*\([^)]*\)")


def _clean_base(query: str) -> str:
    base = _CITY_SUFFIX.sub("", query).strip()
    base = _NOISE_PREFIX.sub("", base).strip()
    base = _PAREN.sub("", base).strip()
    base = base.rstrip(".,")
    return base

def parse_between(query: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'X between A and/&/to B' / 'X from A to B' → (X, A, B)"""
    base = _clean_base(query)
    m = re.match(r"^(.+?)\s+between\s+(.+?)\s+(?:and|&|to)\s+(.+)$", base, re.I)
    if m:
        return m.group(1).strip().rstrip(".,"), m.group(2).strip().rstrip(".,"), m.group(3).strip().rstrip(".,")
    m = re.match(r"^(.+?)\s+from\s+(.+?)\s+to\s+(.+)$", base, re.I)
    if m:
        return m.group(1).strip().rstrip(".,"), m.group(2).strip().rstrip(".,"), m.group(3).strip().rstrip(".,")
    return None, None, None


def parse_direct(query: str) -> tuple[Optional[str], Optional[str]]:
    """'X and Y' / 'X & Y' → (X, Y)"""
    base = _clean_base(query)
    m = re.match(r"^(.+?)\s+(?:and|&)\s+(.+)$", base, re.I)
    if m:
        return m.group(1).strip().rstrip(".,"), m.group(2).strip().rstrip(".,")

    return None, None

def geocode_intersection(
    query: str,
) -> tuple[Optional[float], Optional[float], str]:
    """
    geocodes an intersection-type location.

    1. "X between A and B" → find X∩A and X∩B, return midpoint
       - If only one endpoint found, return that endpoint
    2. "X and Y" / "X & Y" → find shared nodes directly
    """
    main, cross1, cross2 = parse_between(query)

    if main and cross1 and cross2:
        lat1, lon1 = overpass_intersection(main, cross1)
        time.sleep(OVERPASS_SLEEP)
        lat2, lon2 = overpass_intersection(main, cross2)
        time.sleep(OVERPASS_SLEEP)

        if lat1 is not None and lat2 is not None:
            return (lat1 + lat2) / 2, (lon1 + lon2) / 2, "overpass_midpoint"
        if lat1 is not None:
            return lat1, lon1, "overpass_endpoint_cross1"
        if lat2 is not None:
            return lat2, lon2, "overpass_endpoint_cross2"

    s1, s2 = parse_direct(query)
    if s1 and s2:
        lat, lon = overpass_intersection(s1, s2)
        time.sleep(OVERPASS_SLEEP)
        if lat is not None:
            return lat, lon, "overpass_direct"

    return None, None, "overpass_no_result"


def geocode_nominatim(
    geolocator, query: str
) -> tuple[Optional[float], Optional[float], str]:
    try:
        result = geolocator.geocode(query, timeout=10, viewbox=VIEWBOX, bounded=False)
        if (
            result
            and LAT_MIN < result.latitude < LAT_MAX
            and LON_MIN < result.longitude < LON_MAX
        ):
            return result.latitude, result.longitude, "nominatim"
    except (GeocoderTimedOut, GeocoderServiceError):
        return None, None, "nominatim_error"
    return None, None, "nominatim_no_result"

def run():
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"{INPUT_CSV} not found.\n"
            "Update INPUT_CSV at the top of this script."
        )

    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} locations from {INPUT_CSV}.")

    if OUTPUT_CSV.exists():
        prev = pd.read_csv(OUTPUT_CSV)[
            ["location_raw", "latitude", "longitude", "geocode_source"]
        ]
        df = df.drop(columns=["latitude", "longitude", "geocode_source"], errors="ignore")
        df = df.merge(prev, on="location_raw", how="left")
        done = df["latitude"].notna().sum()
        print(f"Resuming: {done} done, {df['latitude'].isna().sum()} remaining.")
    else:
        df["latitude"] = None
        df["longitude"] = None
        df["geocode_source"] = None
        df["geocode_notes"] = None

    geolocator = Nominatim(user_agent=NOMINATIM_UA)

    retry_sources = {"no_result", "overpass_no_result", "nominatim_no_result", "nominatim_error"}
    todo = df[
        df["latitude"].isna() | df["geocode_source"].isin(retry_sources)
    ].index.tolist()
    df.loc[df["geocode_source"].isin(retry_sources),
           ["latitude", "longitude", "geocode_source", "geocode_notes"]] = None

    print(f"Processing {len(todo)} rows...")

    for n, idx in enumerate(todo):
        row = df.loc[idx]
        query = row["location_for_geocoding"]
        loc_type = row.get("location_type", "intersection")

        if loc_type == "intersection":
            lat, lon, source = geocode_intersection(query)
            if lat is None:
                lat, lon, source = geocode_nominatim(geolocator, query)
                time.sleep(NOMINATIM_SLEEP)
        else:
            lat, lon, source = geocode_nominatim(geolocator, query)
            time.sleep(NOMINATIM_SLEEP)

        df.at[idx, "latitude"] = lat
        df.at[idx, "longitude"] = lon
        df.at[idx, "geocode_source"] = source
        df.at[idx, "geocode_notes"] = source if lat is None else None

        status = f"[{n+1}/{len(todo)}] {source:<35s} {query[:55]}"
        print(status)

        if (n + 1) % CHECKPOINT_EVERY == 0:
            df.to_csv(OUTPUT_CSV, index=False)
            print(f"  ✓ checkpoint saved → {OUTPUT_CSV}")

    df.to_csv(OUTPUT_CSV, index=False)
    coded = df["latitude"].notna().sum()
    no_result = df["geocode_source"].isin(retry_sources).sum()
    print(f"\nDone. {coded}/{len(df)} geocoded successfully.")
    print(f"No-result rows (manual review needed): {no_result}")
    print(f"Saved → {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    run()

