import re
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

INPUT_FILE = Path("data/raw_oakland_data.csv")
OUTPUT_DIR = Path("data/intermediate")
OUTPUT_DIR.mkdir(parents=True, exist_ok = True)

CLEANED_CSV = OUTPUT_DIR / "encampment_cleaned.csv"
GEOCODE_CSV = OUTPUT_DIR / "encampment_to_geocode.csv"
REPORT_FILE = OUTPUT_DIR / "cleaning_report.txt"

#timestamps of grants pass/newsom order
GRANTS_PASS_DATE  = pd.Timestamp("2024-06-28")
NEWSOM_ORDER_DATE = pd.Timestamp("2024-08-02")


# street abbreviations obsererved within the dataset for cleaning
STREET_ABBREV = [
    # Street types
    (r"\bBlvd\.?\b",     "Boulevard"),
    (r"\bAve\.?\b",      "Avenue"),
    (r"\bSt\.?\b",       "Street"),
    (r"\bDr\.?\b",       "Drive"),
    (r"\bPkwy\.?\b",     "Parkway"),
    (r"\bPl\.?\b",       "Place"),
    (r"\bRd\.?\b",       "Road"),
    (r"\bCt\.?\b",       "Court"),
    (r"\bLn\.?\b",       "Lane"),
    (r"\bHwy\.?\b",      "Highway"),
    (r"\bFwy\.?\b",      "Freeway"),
    (r"\bMLK\b",         "Martin Luther King Jr Boulevard"),
    (r"\bMLk\b",         "Martin Luther King Jr Boulevard"),  
    (r"\bInternational\b(?! Boulevard)", "International Boulevard"),  
    (r"\bMandela\b(?! Parkway)",         "Mandela Parkway"),
    (r"\bW\s+(?=[A-Z])", "West "),
    (r"\bE\s+(?=[A-Z])", "East "),
    (r"\bN\s+(?=[A-Z])", "North "),
    (r"\bS\s+(?=[A-Z])", "South "),
    (r"\bE\.\s+",        "East "),
    (r"\bW\.\s+",        "West "),
    ]


# strip the noise as it describes the type of operation and not the location of the operation 
GEOCODE_NOISE = [
    r"\(large structure and additional \d+ tents\)",
    r"\(behind [^)]+\)",
    r"\(cul-de-sac[^)]*\)",
    r"\(VA lot to [^)]+\)",
    r"\(half block\)",
    r"\s*[-–]\s*(DMV|Pathway|Frog Park)[^,]*",
    r"\s*/[^,]*$",        
    r"\s*:\s*[^:,]+$",      
]

# directional quantifiers to extract
DIRECTION_PATTERNS = [
    r"north\s*(?:side)?",
    r"south\s*(?:side)?",
    r"east\s*(?:side)?",
    r"west\s*(?:side)?",
    r"northside",
    r"southside",
    r"eastside",
    r"westside",
    r"both\s+sides",
    r"entire\s+(?:park|encampment|block|street)",
    r"half\s+block",
    r"cul[\s-]de[\s-]sac",
    r"dog\s+park",
    r"play\s+structure",
    r"building\s+only",
    r"pathway",
    r"amphith?e?a?ter",
]


def classify_intervention(raw: str) -> dict:
    """
    takes in the raw strong and returns a dict with the following keys
      intervention_primary    — dominant action
      intervention_secondary  — secondary action (mixed ops only)
      is_mixed_intervention   — bool
      not_executed            — bool
      is_self_closure         — bool
      with_outreach           — bool (AA = Abandoned Auto or Assertive Outreach)
      spatial_notes           — directional/site qualifiers
      intervention_raw        — original string preserved
    """
    result = {
        "intervention_raw":        raw,
        "intervention_primary":    None,
        "intervention_secondary":  None,
        "is_mixed_intervention":   False,
        "not_executed":            False,
        "is_self_closure":         False,
        "with_outreach":           False,
        "spatial_notes":           None,
    }

    if pd.isna(raw):
        result["intervention_primary"] = "Unknown"
        return result

    s = str(raw).strip()

    if re.search(r"unable\s+to\s+be\s+executed", s, re.I):
        result["not_executed"] = True

    if re.search(r"self[\s-](?:clos|abat)", s, re.I):
        result["is_self_closure"] = True

    if re.search(r"\bAA\b|outreach", s, re.I):
        result["with_outreach"] = True

    found_dirs = []
    for pat in DIRECTION_PATTERNS:
        m = re.search(pat, s, re.I)
        if m:
            found_dirs.append(m.group(0).strip().lower())
    if found_dirs:
        seen = set()
        unique_dirs = []
        for d in found_dirs:
            if d not in seen:
                seen.add(d)
                unique_dirs.append(d)
        result["spatial_notes"] = "; ".join(unique_dirs)


    has_micro   = bool(re.search(r"micro\s*clos", s, re.I))
    has_partial = bool(re.search(r"partial\s*clos", s, re.I))
    has_deep    = bool(re.search(r"deep\s*cl(?:ean)?", s, re.I))
    has_closure = bool(re.search(r"\bclos", s, re.I))

    if re.search(r"encampment\s+fire|KOCB", s, re.I):
        result["intervention_primary"] = "Other"
        result["spatial_notes"] = ((result["spatial_notes"] or "") + "; fire debris").strip("; ")
        return result

    if re.search(r"abandoned\s+auto\s+posting\s+only", s, re.I):
        result["intervention_primary"] = "Other"
        return result

    if re.search(r"fire\s+lane\s+enforcement|k-rail", s, re.I) and not has_closure and not has_deep:
        result["intervention_primary"] = "Other"
        return result

    # when assigning closure as primary/secondary the more aggressive one becomes primary
    # micro Closure > partial Closure > closure > deep cleaning

    if has_micro:
        result["intervention_primary"] = "Micro Closure"
        if has_deep:
            result["intervention_secondary"] = "Deep Cleaning"
            result["is_mixed_intervention"] = True
        return result

    # to distinguish partial closure from a mixed partial + closure, chekcs for standalone closure term
    has_standalone_closure = bool(re.search(r"(?<!partial[\s\-])(?<!partial)\bclos", s, re.I))

    if has_partial and has_standalone_closure and has_deep:
        result["intervention_primary"]   = "Closure"
        result["intervention_secondary"] = "Deep Cleaning"
        result["is_mixed_intervention"]  = True
        result["spatial_notes"] = ((result["spatial_notes"] or "") + "; includes partial closure").strip("; ")
        return result

    if has_partial and has_standalone_closure:
        result["intervention_primary"]   = "Closure"
        result["intervention_secondary"] = "Partial Closure"
        result["is_mixed_intervention"]  = True
        return result

    if has_closure and has_deep:
        result["intervention_primary"]   = "Closure"
        result["intervention_secondary"] = "Deep Cleaning"
        result["is_mixed_intervention"]  = True
        return result

    if has_partial:
        result["intervention_primary"] = "Partial Closure"
        if has_deep:
            result["intervention_secondary"] = "Deep Cleaning"
            result["is_mixed_intervention"]  = True
        return result

    if has_closure:
        result["intervention_primary"] = "Closure"
        return result

    if has_deep:
        result["intervention_primary"] = "Deep Cleaning"
        return result

    result["intervention_primary"] = "Other"
    return result


#known locations to save geocodeing tokens
KNOWN_PLACES: dict[str, tuple[float, float]] = {
    "mosswood park":                    (37.8236, -122.2617),
    "mosswood dog park":                (37.8236, -122.2617),
    "lake merritt":                     (37.7982, -122.2587),
    "clinton park":                     (37.8082, -122.2544),
    "cesar chavez park":                (37.7968, -122.2394),
    "union point park":                 (37.7742, -122.2316),
    "lafayette square park":            (37.8077, -122.2693),
    "jefferson square park":            (37.8042, -122.2710),
    "raimondi park":                    (37.8359, -122.2950),
    "peralta park":                     (37.8175, -122.2779),
    "elmhurst park":                    (37.7713, -122.1889),
    "courtland creek park":             (37.7760, -122.1926),
    "vantage point park":               (37.8010, -122.2359),
    "chinese garden park":              (37.7958, -122.2302),
    "estuary park":                     (37.7907, -122.2490),
    "robert mason fields":              (37.8469, -122.2960),
    "golden gate playground":           (37.8469, -122.2960),
    "helen mc gregor plaza":            (37.8040, -122.2680),
    "cypress freeway memorial park":    (37.8199, -122.2891),
    "marston campbell park":            (37.7999, -122.2257),
    "wilma chan park":                  (37.8039, -122.2362),
    "toll plaza beach":                 (37.8280, -122.3760),
}



def detect_location_type(loc: str) -> str:
    """classify a location as 'intersection', 'named_place', or 'address'."""
    if pd.isna(loc):
        return "unknown"
    s = str(loc).lower()

    if re.search(r"\b(park|plaza|center|centre|field|playground|school|"
                 r"freeway|lake|beach|lot|loop|ramp)\b", s):
        return "named_place"
   
    if re.match(r"^\d+\s+\w", s.strip()):
        return "address"

    if re.search(r"\bbetween\b|\b&\b|\band\b|\bfrom\b", s):
        return "intersection"
    return "named_place"   


def clean_location_for_geocoding(loc: str) -> str:
    """
    produce a clean string ready for the geocoding API.
    strips operational notes, expands abbreviations, appends city/state.
    """
    if pd.isna(loc):
        return ""
    s = str(loc).strip()

    for pat in GEOCODE_NOISE:
        s = re.sub(pat, "", s, flags=re.I).strip()

    s = re.sub(r"[,;.\-]+$", "", s).strip()

    for pat, replacement in STREET_ABBREV:
        s = re.sub(pat, replacement, s)

    s = re.sub(r"\s{2,}", " ", s).strip()

    if "Oakland" not in s and "CA" not in s:
        s += ", Oakland, CA"

    return s

def lookup_known_place(loc: str) -> Optional[tuple[float, float]]:
    """check if location matches a hard-coded known place. returns (lat, lon) or None."""
    if pd.isna(loc):
        return None
    s = str(loc).lower()
    for key, coords in KNOWN_PLACES.items():
        if key in s:
            return coords
    return None

def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col, new_col in [
        ("OPERATION START DATE", "start_date"),
        ("OPERATION END DATE",   "end_date"),
    ]:
        df[new_col] = pd.to_datetime(df[col], format="%B %d, %Y", errors="coerce")

    df["duration_days"] = (df["end_date"] - df["start_date"]).dt.days
    df["year"]  = df["start_date"].dt.year
    df["month"] = df["start_date"].dt.month
    df["year_month"] = df["start_date"].dt.to_period("M").astype(str)

    df["policy_era"] = "pre_grants_pass"
    df.loc[df["start_date"] >= GRANTS_PASS_DATE,  "policy_era"] = "post_grants_pass"
    df.loc[df["start_date"] >= NEWSOM_ORDER_DATE,  "policy_era"] = "post_newsom_order"

    return df

def run_pipeline() -> pd.DataFrame:
    df = pd.read_csv(INPUT_FILE)

    report_lines = [
        "Oakland EMT Data Cleaning Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
    ]

    report_lines.append(f"Input rows:    {len(df)}")
    report_lines.append(f"Input columns: {list(df.columns)}")
    report_lines.append("")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns={
        "location":             "location_raw",
        "district":             "district",
        "sensitivity_zone":     "sensitivity_zone",
        "intervention":         "intervention_raw",
        "operation_start_date": "OPERATION START DATE",
        "operation_end_date":   "OPERATION END DATE",
    })

    
    df["sensitivity_zone"] = df["sensitivity_zone"].str.strip().str.title()
    sz_counts = df["sensitivity_zone"].value_counts().to_dict()
    report_lines.append(f"Sensitivity zone distribution: {sz_counts}")

    
    df["district"] = df["district"].str.strip().str.upper()

    
    df = parse_dates(df)
    unparseable = df["start_date"].isna().sum()
    report_lines.append(f"Unparseable start dates: {unparseable}")
    report_lines.append(f"Date range: {df['start_date'].min().date()} → {df['start_date'].max().date()}")
    era_counts = df["policy_era"].value_counts().to_dict()
    report_lines.append(f"Policy era distribution: {era_counts}")
    report_lines.append("")


    classified = df["intervention_raw"].apply(classify_intervention)
    intervention_df = pd.DataFrame(classified.tolist())

    intervention_df = intervention_df.drop(columns=["intervention_raw"])
    df = pd.concat([df, intervention_df], axis=1)

    primary_counts = df["intervention_primary"].value_counts().to_dict()
    mixed_count    = df["is_mixed_intervention"].sum()
    not_exec_count = df["not_executed"].sum()
    self_clos_count = df["is_self_closure"].sum()
    outreach_count  = df["with_outreach"].sum()

    report_lines.append("── Intervention classification ──")
    report_lines.append(f"Primary categories:   {primary_counts}")
    report_lines.append(f"Mixed interventions:  {mixed_count}")
    report_lines.append(f"Not executed:         {not_exec_count}")
    report_lines.append(f"Self-closures:        {self_clos_count}")
    report_lines.append(f"With outreach (AA):   {outreach_count}")
    report_lines.append("")

    
    df["location_type"]          = df["location_raw"].apply(detect_location_type)
    df["location_for_geocoding"] = df["location_raw"].apply(clean_location_for_geocoding)


    df["latitude"]  = None
    df["longitude"] = None
    df["geocode_source"] = None

    known_hits = 0
    for idx, row in df.iterrows():
        coords = lookup_known_place(row["location_raw"])
        if coords:
            df.at[idx, "latitude"]       = coords[0]
            df.at[idx, "longitude"]      = coords[1]
            df.at[idx, "geocode_source"] = "known_place_lookup"
            known_hits += 1

    loc_type_counts = df["location_type"].value_counts().to_dict()
    report_lines.append("── Location classification ──")
    report_lines.append(f"Location types: {loc_type_counts}")
    report_lines.append(f"Pre-geocoded (known places): {known_hits} rows")
    report_lines.append(f"Unique locations total:      {df['location_raw'].nunique()}")
    report_lines.append(f"Still need geocoding:        {df['latitude'].isna().sum()} rows")
    report_lines.append("")

    
    col_order = [
        "location_raw", "district", "sensitivity_zone",
        "OPERATION START DATE", "OPERATION END DATE",
        "start_date", "end_date", "duration_days",
        "year", "month", "year_month",
        "policy_era",
        "intervention_primary", "intervention_secondary",
        "is_mixed_intervention", "not_executed",
        "is_self_closure", "with_outreach", "spatial_notes",
        "location_type", "location_for_geocoding",
        "latitude", "longitude", "geocode_source",
    ]
    remaining = [c for c in df.columns if c not in col_order]
    df = df[col_order + remaining]


    df.to_csv(CLEANED_CSV, index=False)
    report_lines.append(f"Saved cleaned dataset → {CLEANED_CSV}")
    report_lines.append(f"Output rows: {len(df)}")
    report_lines.append("")

    geocode_queue = (
        df[df["latitude"].isna()][["location_raw", "location_type", "location_for_geocoding"]]
        .drop_duplicates(subset=["location_raw"])
        .sort_values("location_type")
    )
    geocode_queue["latitude"]        = None
    geocode_queue["longitude"]       = None
    geocode_queue["geocode_source"]  = None
    geocode_queue["geocode_notes"]   = None
    geocode_queue.to_csv(GEOCODE_CSV, index=False)
    report_lines.append(f"Saved geocoding queue → {GEOCODE_CSV}")
    report_lines.append(f"Unique locations to geocode: {len(geocode_queue)}")
    report_lines.append("")


    report_lines.append("── Verification ──")
    unclassified = df[df["intervention_primary"].isna()]
    if len(unclassified) > 0:
        report_lines.append(f"WARNING: {len(unclassified)} rows have no primary intervention:")
        for v in unclassified["intervention_raw"].unique():
            report_lines.append(f"  {repr(v)}")
    else:
        report_lines.append("All rows classified. No nulls in intervention_primary.")

    null_dates = df["start_date"].isna().sum()
    if null_dates > 0:
        report_lines.append(f"WARNING: {null_dates} rows with unparseable start dates")
    else:
        report_lines.append("All start dates parsed successfully.")

    report_lines.append("")
    report_lines.append("── Rows by policy era and primary intervention ──")
    pivot = df.groupby(["policy_era", "intervention_primary"]).size().unstack(fill_value=0)
    report_lines.append(pivot.to_string())


    report_text = "\n".join(report_lines)
    REPORT_FILE.write_text(report_text)
    print(report_text)

    return df


if __name__ == "__main__":
    df_clean = run_pipeline()
    print(f"\nDone. Files written to: {OUTPUT_DIR.resolve()}/")
