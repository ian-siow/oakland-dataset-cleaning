# Oakland Encampment Sweeps & Roots Survey Analysis

Pipeline cleaning the publicly available data (raw_oakland_data.csv) that details Oakland's Encempment Management Team sweeps
Producing visualization based on two 2024 policy events
- **Grants Pass v. Johnson** (SCOTUS, 2024-06-28) — permits criminalizing outdoor sleeping
- **Newsom Executive Order** (2024-08-02) — directed CA agencies to clear encampments


Linking sweep locations to a participant survey (Rootsdeidentify7_9.dta) to measure resident exposure to sweeps.



## Setup

```
pip install -r requirements.txt
```

## Pipeline overview

Two data tracks feed into a final analysis:

```
data/raw_oakland_data.csv                    data/LocationData.csv + Rootsdeidentify7_9.dta
        │                                                      │
        ▼                                                      ▼
  scripts/01_clean.py                                scripts/06_clean_location.py
        │                                                      │
        ▼                                                      │
  scripts/02_geocode.py                                        │
        │                                                      │
        ▼                                                      │
  scripts/03_merge.py                                          │
        │                                                      │
        ▼                                                      │
  scripts/04_validate.py  (validates geocode)                  │
        │                                                      │
        ▼                                                      │
  scripts/05_fix_geocoding.py                                  │
        │                                                      │
        ▼                                                      ▼
  data/final/encampment_final.csv  ───────────►  analysis/analysis.py  ◄── data/final/LocationData_cleaned.csv
                                                        │
                                                        ▼
                                    analysis/survey_with_location.csv
                                    analysis/person_level_dataset.csv
                                    analysis/fig1_monthly_sweeps.png
                                    analysis/fig2_policy_comparison.png
                                    analysis/fig3_proximity_sweeps.png
```



## Sweep pipeline (EMT operations)

**Source:** `data/raw_oakland_data.csv` — 2,201 sweep operations, Jan 2021–Nov 2025.
01_clean.py 
- Parses dates
- Classifies the `INTERVENTION` text into a regex hierarchy((Micro/Partial/Full Closure > Deep Cleaning > Other)
- Tags each row with `policy_era` based on the dates above
- Classifies location strings (`intersection`/`named_place`/`address`)
      - Resolves 133 rows using hardcoded known-place lookups
- CSV files are saved to `data/intermediate/encampment_cleaned.csv` (2,201 rows) + `encampment_to_geocode.csv` (794 unique locations) '


02_geocode.py 
- Parses "X between A and B" intersection strings using the Overpass API (that uses OSM road topology) to take a midpoint for geocoding
- Uses Nominatim for named places and addresses
- Code uses checkpointing to allow us to pause/continue the API calls 
- CSV files saved to`data/intermediate/encampment_geocoded_coords.csv` (706/794 resolved) 


03_merge.py 
- Joins geocoded coordinates back onto all 2,201 sweep rows by `location_raw`, 
- Preserves the Stage-1 known-place coordinates 
- CSV files saved to `data/final/encampment_final.csv` 
- Locations that were not able to be geocoded were manually imputed by me using google maps and the raw street names


04_validate.py 
- Form of sanity check on the geocoded locations. Flags location outside the Oakland bounding box.
- Rows that deviate more than 0.01° from their street group's median are flagged
- Produces a printed report with cross-city name collisions (Castro St is a street both in SF and Oakland, so rows were geocoded incorrectly)

05_fix_geocoding.py
- Re-derives the flagged rows fresh from the current data 
- Re-geocodes them with a tight Oakland-only bounding box 
- CSV is updated to `data/final/encampment_final.csv` 
- Pre-fix state is backed up to `encampment_final_prefix.csv` 

**Known gaps:** 
3 locations have no coordinates anywhere in the pipeline (`E 19th St and
29th Ave`, `High St Safe Parking along Alameda Ave`, `4th & MLK`) — even manual lookup
couldn't resolve them. 
.

## Survey location pipeline (Roots study)

**Source:** 
`data/LocationData.csv` (605 respondent) and `data/Rootsdeidentify7_9.dta` (605
respondents × 925 columns, de-identified survey responses).

06_clean_location.py
-classifies each `input_location` string and extracts coordinates where possible:
- `coord_decimal` / `coord_dms` / `coord_embedded` — a latitude/longitude pair typed or pasted directly (including one degrees-minutes-seconds entry and one embedded Google Maps URL)
- `address` — resolves to a specific place via Nominatim (bounded to the Bay Area)
- `area_vague` — resolves only to a city/neighborhood-level match (e.g. "Richmond", "Oakland, CA"), or fails to geocode but isn't obvious noise — coordinates intentionally dropped as too coarse to be useful
- `junk` — unparseable noise ("No", "Na", garbled fragments)
- `missing` — blank

Also computes `distance_m`, the haversine distance between device GPS and parsed input
coordinates, for rows where both exist (median ~74m; 88 rows disagree by >500m).


## Final analysis (`analysis/analysis.py`)

1. Merges `LocationData_cleaned.csv` onto the survey (joined by row position via `new_id`)
2. Computes `best_lat`/`best_lon` per respondent: device GPS if present, else the parsed `input_location` coordinate
3. **`fig1_monthly_sweeps.png`** — monthly sweep counts (all interventions vs. closures only) with policy-event markers
4. **`fig2_policy_comparison.png`** — mean monthly closures by policy era + 3-month rolling average
5. Computes `sweeps_100m`/`sweeps_200m` per respondent: count of sweep operations within 100m/200m of their best coordinate (based on the prior discssion of 1/2 block distance in Oakland), via vectorized haversine distance (respondents × encampments)
6. **`fig3_proximity_sweeps.png`** — distribution of sweep-proximity counts
7. Builds `person_level_dataset.csv` — one row per respondent with exposure metrics, demographics, and shelter preference rankings (including `top_shelter_attribute`, the #1-ranked shelter feature per respondent)



