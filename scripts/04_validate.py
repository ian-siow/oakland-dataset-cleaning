import pandas as pd
import numpy as np
import re

df = pd.read_csv('data/final/encampment_final.csv')


OAK_LAT_MIN, OAK_LAT_MAX = 37.63, 37.90
OAK_LON_MIN, OAK_LON_MAX = -122.38, -122.11

print(f"Total rows: {len(df)}")
print(f"Rows with lat/lon: {df['latitude'].notna().sum()}")
print()


df['out_of_bbox'] = (
    df['latitude'].notna() & df['longitude'].notna() & (
        (df['latitude'] < OAK_LAT_MIN) | (df['latitude'] > OAK_LAT_MAX) |
        (df['longitude'] < OAK_LON_MIN) | (df['longitude'] > OAK_LON_MAX)
    )
)

bbox_issues = df[df['out_of_bbox']][['location_raw', 'location_for_geocoding', 'latitude', 'longitude', 'geocode_source', 'geocode_notes']]
print(f"=== OUT OF BBOX ({len(bbox_issues)} rows) ===")
print(bbox_issues.to_string())
print()


def extract_street(loc):
    if pd.isna(loc):
        return None
    loc = str(loc).strip()
    m = re.match(r'^([^&@\n]+?)\s+(?:between|@|&|\bat\b)', loc, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return loc.strip().upper()

df['primary_street'] = df['location_for_geocoding'].apply(extract_street)


THRESHOLD = 0.01  

flagged_rows = []
for street, grp in df[df['longitude'].notna()].groupby('primary_street'):
    if len(grp) < 3:
        continue
    med_lon = grp['longitude'].median()
    med_lat = grp['latitude'].median()
    for idx, row in grp.iterrows():
        lon_diff = abs(row['longitude'] - med_lon)
        lat_diff = abs(row['latitude'] - med_lat)
        if lon_diff > THRESHOLD or lat_diff > THRESHOLD:
            flagged_rows.append({
                'idx': idx,
                'location_raw': row['location_raw'],
                'location_for_geocoding': row['location_for_geocoding'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'geocode_source': row['geocode_source'],
                'geocode_notes': row.get('geocode_notes', ''),
                'street_group': street,
                'group_median_lat': round(med_lat, 6),
                'group_median_lon': round(med_lon, 6),
                'lat_diff': round(lat_diff, 6),
                'lon_diff': round(lon_diff, 6),
            })

flagged_df = pd.DataFrame(flagged_rows).sort_values(['street_group', 'lon_diff'], ascending=[True, False])

print(f"=== WITHIN-STREET OUTLIERS (lon or lat diff > {THRESHOLD} deg from group median) ===")
print(f"Total flagged: {len(flagged_df)}")
print()

for street, grp in flagged_df.groupby('street_group'):
    print(f"--- {street} (group median lat={grp.iloc[0]['group_median_lat']}, lon={grp.iloc[0]['group_median_lon']}) ---")
    for _, r in grp.iterrows():
        print(f"  [{r['idx']}] {r['location_for_geocoding']}")
        print(f"       lat={r['latitude']}, lon={r['longitude']}  (diff: lat={r['lat_diff']}, lon={r['lon_diff']})")
        print(f"       source={r['geocode_source']}  notes={r['geocode_notes']}")
    print()


far_west = df[df['longitude'].notna() & (df['longitude'] < -122.35)][
    ['location_raw', 'location_for_geocoding', 'latitude', 'longitude', 'geocode_source', 'geocode_notes']
]
print(f"=== LONGITUDE < -122.35 (suspiciously far west, {len(far_west)} rows) ===")
print(far_west.to_string())
