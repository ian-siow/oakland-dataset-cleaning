import re
import time
import math
import pandas as pd
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from typing import Optional

INPUT_CSV  = Path("data/LocationData.csv")
OUTPUT_CSV = Path("data/final/LocationData_cleaned.csv")
Path("data/final").mkdir(parents=True, exist_ok=True)

NOMINATIM_UA = "roots_survey_location_cleaning"
NOMINATIM_SLEEP = 1.1

# Bay Area bounding box (SF, Oakland, Berkeley, Richmond, El Sobrante, San Leandro...)
BAY_LAT_MIN, BAY_LAT_MAX = 36.8, 38.5
BAY_LON_MIN, BAY_LON_MAX = -123.3, -121.0
VIEWBOX = [(BAY_LAT_MAX, BAY_LON_MIN), (BAY_LAT_MIN, BAY_LON_MAX)]

COARSE_TYPES = {
    "city", "town", "village", "hamlet", "county", "state",
    "administrative", "suburb", "city_district", "neighbourhood", "region",
}

JUNK_STOPWORDS = {"no", "na", "n/a", "none", "yes", "idk", "unknown", "yea"}


def _decimal_pair(s: str) -> Optional[tuple[float, float]]:
    m = re.fullmatch(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _dms_pair(s: str) -> Optional[tuple[float, float]]:
    m = re.fullmatch(
        r"(\d{1,3})\.(\d{1,2}),(\d{1,2}(?:\.\d+)?),*\s*([NSns])\s+"
        r"(\d{1,3})\.(\d{1,2}),(\d{1,2}(?:\.\d+)?)\s*([EWew])",
        s,
    )
    if not m:
        return None
    lat_d, lat_m, lat_s, lat_h, lon_d, lon_m, lon_s, lon_h = m.groups()
    lat = int(lat_d) + int(lat_m) / 60 + float(lat_s) / 3600
    if lat_h.upper() == "S":
        lat = -lat
    lon = int(lon_d) + int(lon_m) / 60 + float(lon_s) / 3600
    if lon_h.upper() == "W":
        lon = -lon
    return lat, lon


def _embedded_pair(s: str) -> Optional[tuple[float, float]]:
    m = re.search(r"(-?\d{1,3}\.\d{4,})\s*,\s*(-?\d{1,3}\.\d{4,})", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def classify_and_parse(
    raw: object, geolocator
) -> tuple[str, Optional[float], Optional[float]]:
    if pd.isna(raw):
        return "missing", None, None

    s = str(raw).strip()
    if not s:
        return "missing", None, None

    pair = _decimal_pair(s)
    if pair:
        return "coord_decimal", pair[0], pair[1]

    pair = _dms_pair(s)
    if pair:
        return "coord_dms", pair[0], pair[1]

    pair = _embedded_pair(s)
    if pair:
        return "coord_embedded", pair[0], pair[1]

    query = s if ("CA" in s or "California" in s) else f"{s}, CA"
    try:
        result = geolocator.geocode(
            query, viewbox=VIEWBOX, bounded=True, addressdetails=True, timeout=10
        )
    except (GeocoderTimedOut, GeocoderServiceError):
        result = None
    time.sleep(NOMINATIM_SLEEP)

    if result is not None:
        addr_type = result.raw.get("addresstype") or result.raw.get("type")
        if addr_type in COARSE_TYPES:
            return "area_vague", None, None
        return "address", result.latitude, result.longitude

    letters = re.sub(r"[^a-zA-Z]", "", s)
    if s.lower() in JUNK_STOPWORDS or len(letters) < 3:
        return "junk", None, None
    return "area_vague", None, None


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def run():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} rows from {INPUT_CSV}")

    geolocator = Nominatim(user_agent=NOMINATIM_UA)

    categories, lats, lons = [], [], []
    for n, raw in enumerate(df["input_location"]):
        category, lat, lon = classify_and_parse(raw, geolocator)
        categories.append(category)
        lats.append(lat)
        lons.append(lon)
        print(f"[{n+1}/{len(df)}] {category:<15s} {str(raw)[:50]}")

    df["input_category"] = categories
    df["input_lat"] = lats
    df["input_lon"] = lons

    df["distance_m"] = None
    both = (
        df["Location_Latitude"].notna()
        & df["Location_Longitude"].notna()
        & df["input_lat"].notna()
        & df["input_lon"].notna()
    )
    df.loc[both, "distance_m"] = df[both].apply(
        lambda r: round(
            haversine_m(
                r["Location_Latitude"], r["Location_Longitude"],
                r["input_lat"], r["input_lon"],
            ),
            1,
        ),
        axis=1,
    )

    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\n{'='*70}")
    print(f"Category counts:\n{df['input_category'].value_counts()}")
    print(f"Saved -> {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    run()
