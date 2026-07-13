import os
import pandas as pd

cleaned = pd.read_csv("data/intermediate/encampment_cleaned.csv")
coords  = pd.read_csv("data/intermediate/encampment_geocoded_coords.csv",
                      usecols=["location_raw", "latitude", "longitude",
                               "geocode_source", "geocode_notes"])

known = cleaned[cleaned["geocode_source"] == "known_place_lookup"].copy()
rest  = cleaned[cleaned["geocode_source"] != "known_place_lookup"].copy()
rest = rest.drop(columns=["latitude", "longitude", "geocode_source", "geocode_notes"],
                 errors="ignore")


rest_merged = rest.merge(coords, on="location_raw", how="left")

final = pd.concat([known, rest_merged], ignore_index=True)

col_order = [
    "location_raw", "district", "sensitivity_zone",
    "OPERATION START DATE", "OPERATION END DATE",
    "start_date", "end_date", "duration_days",
    "year", "month", "year_month", "policy_era",
    "intervention_primary", "intervention_secondary",
    "is_mixed_intervention", "not_executed", "is_self_closure", "with_outreach",
    "spatial_notes", "location_type", "location_for_geocoding",
    "latitude", "longitude", "geocode_source", "geocode_notes",
    "intervention_raw",
]
final = final[[c for c in col_order if c in final.columns]]

os.makedirs("data/final", exist_ok=True)

final.to_csv("data/final/encampment_final.csv", index=False)

total        = len(final)
with_coords  = final["latitude"].notna().sum()
without      = total - with_coords
by_source    = final["geocode_source"].value_counts()

print(f"Total rows:          {total}")
print(f"Rows with coords:    {with_coords}  ({with_coords/total*100:.1f}%)")
print(f"Rows without coords: {without}")
print()
print("Geocode source breakdown:")
print(by_source.to_string())
print()
print("Saved → data/final/encampment_final.csv")