"""
merges LocationData_cleaned.csv + Rootsdeidentify7_9.dta,
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
import warnings
warnings.filterwarnings('ignore')


GRANTS_PASS_DATE = pd.Timestamp('2024-06-28')
NEWSOM_ORDER_DATE = pd.Timestamp('2024-08-02')

OUTDIR = 'analysis/'



print("Loading data...")
loc = pd.read_csv('data/final/LocationData_cleaned.csv')
dta = pd.read_stata('data/Rootsdeidentify7_9.dta')
enc = pd.read_csv('data/final/encampment_final.csv')

# Parse encampment dates
enc['start_date'] = pd.to_datetime(enc['start_date'])
enc['end_date']   = pd.to_datetime(enc['end_date'])

print(f"  LocationData_cleaned: {loc.shape}")
print(f"  Survey (dta):         {dta.shape}")
print(f"  Encampments:          {enc.shape}")



print("\nMerging LocationData_cleaned with survey data...")


dta['new_id'] = range(1, len(dta) + 1)


merged = dta.merge(
    loc[['new_id', 'input_location', 'input_category',
         'input_lat', 'input_lon', 'distance_m']],
    on='new_id',
    how='left'
)

# Coerce GPS columns to numeric
for col in ['Location_Latitude', 'Location_Longitude', 'input_lat', 'input_lon']:
    merged[col] = pd.to_numeric(merged[col], errors='coerce')

# Choose best available coordinates for each respondent:
# 1. Use device GPS (Location_Latitude/Longitude) when available
# 2. Fall back to parsed input coordinates
merged['best_lat'] = np.where(
    merged['Location_Latitude'].notna(),
    merged['Location_Latitude'],
    merged['input_lat']
)
merged['best_lon'] = np.where(
    merged['Location_Longitude'].notna(),
    merged['Location_Longitude'],
    merged['input_lon']
)

# Verify: rows where both device GPS and input coords exist should be close
valid_both = merged[
    merged['Location_Latitude'].notna() & merged['input_lat'].notna()
].copy()

def haversine_m(lat1, lon1, lat2, lon2):
    """Return great-circle distance in meters."""
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

if len(valid_both) > 0:
    valid_both['coord_check_m'] = haversine_m(
        valid_both['Location_Latitude'], valid_both['Location_Longitude'],
        valid_both['input_lat'],         valid_both['input_lon']
    )
    print(f"  Coordinate cross-check (device GPS vs input coords):")
    print(f"    N with both coords: {len(valid_both)}")
    print(f"    Median distance: {valid_both['coord_check_m'].median():.1f} m")
    print(f"    >500m discrepancy: {(valid_both['coord_check_m'] > 500).sum()} rows")

n_located = merged['best_lat'].notna().sum()
print(f"  Respondents with usable coordinates: {n_located} / {len(merged)}")

# Save merged CSV
out_cols_base = [
    'new_id', 'Response_ID', 'Recorded_Date',
    'Location_Latitude', 'Location_Longitude',
    'input_location', 'input_category', 'input_lat', 'input_lon', 'distance_m',
    'best_lat', 'best_lon'
]
# Add sweep self-report, demographic, and shelter pref columns
extra_cols = [
    'sweep', 'gender', 'age', 'race_White', 'race_Hispanic', 'race_Black',
    'race_Asian', 'race_American_Indian',
    'last_30_noshelter', '_3year_noshelter',
]
extra_cols += [c for c in merged.columns if c.startswith('Rank___')]
extra_cols += [c for c in merged.columns if c.startswith('Preferred_')]
extra_cols += [c for c in merged.columns if c.startswith('Outside_Option')]
extra_cols += [c for c in merged.columns if c.startswith('trigger___')]
extra_cols = [c for c in extra_cols if c in merged.columns]

save_cols = [c for c in out_cols_base + extra_cols if c in merged.columns]
merged[save_cols].to_csv(f'{OUTDIR}survey_with_location.csv', index=False)
print(f"  Saved: survey_with_location.csv ({len(save_cols)} columns)")


# ─── 3. Monthly Sweep Line Chart ──────────────────────────────────────────────
print("\nBuilding monthly sweep chart...")

# Only actual closures/sweeps (exclude deep cleanings for primary sweep line,
# but plot both series for comparison)
closures = enc[enc['intervention_primary'].isin(
    ['Closure', 'Partial Closure', 'Micro Closure']
)].copy()

monthly_all = (
    enc.groupby('start_date').size()
       .resample('ME').sum()
       .reset_index(name='all_interventions')
)
monthly_closures = (
    closures.groupby('start_date').size()
            .resample('ME').sum()
            .reset_index(name='closures')
)
monthly = monthly_all.merge(monthly_closures, on='start_date', how='outer').fillna(0)
monthly = monthly[monthly['start_date'] >= '2021-01-01'].copy()

fig, ax = plt.subplots(figsize=(14, 6))

ax.plot(monthly['start_date'], monthly['all_interventions'],
        color='steelblue', linewidth=1.8, label='All interventions', zorder=3)
ax.plot(monthly['start_date'], monthly['closures'],
        color='#d73027', linewidth=1.8, linestyle='--', label='Closures only', zorder=3)

ax.fill_between(monthly['start_date'], monthly['closures'],
                alpha=0.12, color='#d73027')

# Policy event vertical lines
ax.axvline(GRANTS_PASS_DATE, color='#984ea3', linewidth=2, linestyle=':', zorder=4)
ax.axvline(NEWSOM_ORDER_DATE, color='#ff7f00', linewidth=2, linestyle=':', zorder=4)

ax.text(GRANTS_PASS_DATE + pd.Timedelta(days=6), ax.get_ylim()[1] * 0.85,
        "Grants Pass\n(Jun 28, 2024)", color='#984ea3', fontsize=8.5,
        verticalalignment='top')
ax.text(NEWSOM_ORDER_DATE + pd.Timedelta(days=6), ax.get_ylim()[1] * 0.70,
        "Newsom Order\n(Aug 2, 2024)", color='#ff7f00', fontsize=8.5,
        verticalalignment='top')

ax.set_xlabel('Month', fontsize=11)
ax.set_ylabel('Number of operations', fontsize=11)
ax.set_title('Oakland Encampment Operations by Month (2021–2025)', fontsize=13, fontweight='bold')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.xticks(rotation=45, ha='right')
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig(f'{OUTDIR}fig1_monthly_sweeps.png', dpi=150)
plt.close()
print("  Saved: fig1_monthly_sweeps.png")


# ─── 4. Pre/Post Policy Comparison ───────────────────────────────────────────
print("Building pre/post policy comparison chart...")

# Only closures; compute monthly average in each era
era_order = ['pre_grants_pass', 'post_grants_pass', 'post_newsom_order']
era_labels = {
    'pre_grants_pass':    'Pre-Grants Pass\n(before Jun 2024)',
    'post_grants_pass':   'Post-Grants Pass\n(Jun–Aug 2024)',
    'post_newsom_order':  'Post-Newsom Order\n(Aug 2024–)'
}

# Monthly counts per era
era_monthly = (
    closures.groupby(['policy_era', pd.Grouper(key='start_date', freq='ME')])
            .size()
            .reset_index(name='count')
)
era_summary = (
    era_monthly.groupby('policy_era')['count']
               .agg(['mean', 'median', 'std', 'count'])
               .reindex(era_order)
               .reset_index()
)
era_summary['label'] = era_summary['policy_era'].map(era_labels)

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

colors = ['#4393c3', '#74add1', '#d73027']

# Bar chart – mean monthly closures per era
bars = axes[0].bar(
    era_summary['label'], era_summary['mean'],
    color=colors, edgecolor='white', linewidth=0.5, width=0.55
)
for bar, (_, row) in zip(bars, era_summary.iterrows()):
    axes[0].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1.5,
                 f"{row['mean']:.1f}", ha='center', va='bottom', fontsize=10, fontweight='bold')
axes[0].set_ylabel('Avg monthly closures', fontsize=11)
axes[0].set_title('Mean Monthly Closures by Policy Era', fontsize=12, fontweight='bold')
axes[0].set_ylim(0, era_summary['mean'].max() * 1.3)
axes[0].grid(axis='y', alpha=0.3)

# Rolling 3-month average overlaid on the line chart
monthly_closures2 = (
    closures.groupby('start_date').size()
            .resample('ME').sum()
)
monthly_closures2 = monthly_closures2[monthly_closures2.index >= '2021-01-01']
rolling = monthly_closures2.rolling(3, center=True).mean()

axes[1].plot(monthly_closures2.index, monthly_closures2.values,
             color='lightgray', linewidth=1.2, alpha=0.8, label='Monthly')
axes[1].plot(rolling.index, rolling.values,
             color='#d73027', linewidth=2.2, label='3-month rolling avg')

for dt, label, color in [
    (GRANTS_PASS_DATE,   'Grants Pass', '#984ea3'),
    (NEWSOM_ORDER_DATE,  'Newsom Order', '#ff7f00')
]:
    axes[1].axvline(dt, color=color, linewidth=2, linestyle=':')
    axes[1].text(dt + pd.Timedelta(days=5),
                 monthly_closures2.max() * 0.92,
                 label, color=color, fontsize=8, rotation=90, va='top')

axes[1].set_xlabel('Month', fontsize=11)
axes[1].set_ylabel('Monthly closures', fontsize=11)
axes[1].set_title('Closure Trend with 3-Month Rolling Average', fontsize=12, fontweight='bold')
axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=4))
plt.setp(axes[1].xaxis.get_majorticklabels(), rotation=45, ha='right')
axes[1].legend(fontsize=10)
axes[1].grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(f'{OUTDIR}fig2_policy_comparison.png', dpi=150)
plt.close()
print("  Saved: fig2_policy_comparison.png")


# ─── 5. Sweeps Within 100m / 200m of Each Respondent ────────────────────────
print("\nComputing sweeps proximity to respondents...")

# Use only encampments with valid coordinates and closures
enc_geo = enc[
    enc['latitude'].notna() & enc['longitude'].notna()
].copy()
enc_geo['lat_r'] = np.radians(enc_geo['latitude'])
enc_geo['lon_r'] = np.radians(enc_geo['longitude'])

# Survey respondents with valid best coordinates
resp = merged[merged['best_lat'].notna() & merged['best_lon'].notna()].copy()

RADII = [100, 200]  # metres

# Vectorised Haversine using broadcasting (respondents × encampments)
resp_lat = np.radians(resp['best_lat'].values)
resp_lon = np.radians(resp['best_lon'].values)
enc_lat  = np.radians(enc_geo['latitude'].values)
enc_lon  = np.radians(enc_geo['longitude'].values)

# Shape: (n_resp, n_enc)
dphi    = resp_lat[:, None] - enc_lat[None, :]
dlambda = resp_lon[:, None] - enc_lon[None, :]
a       = (np.sin(dphi/2)**2
           + np.cos(resp_lat[:, None]) * np.cos(enc_lat[None, :]) * np.sin(dlambda/2)**2)
dist_m  = 2 * 6_371_000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))   # (n_resp, n_enc)

for r in RADII:
    within = dist_m <= r                         # boolean mask (n_resp, n_enc)
    merged.loc[resp.index, f'sweeps_{r}m']    = within.sum(axis=1)
    merged.loc[resp.index, f'closures_{r}m']  = within[:, enc_geo['intervention_primary'].isin(
        ['Closure','Partial Closure','Micro Closure']).values].sum(axis=1)

for r in RADII:
    merged[f'sweeps_{r}m']   = merged[f'sweeps_{r}m'].fillna(0).astype(int)
    merged[f'closures_{r}m'] = merged[f'closures_{r}m'].fillna(0).astype(int)

print(f"  sweeps_100m — mean: {merged['sweeps_100m'].mean():.1f}, "
      f"max: {merged['sweeps_100m'].max()}, "
      f">0: {(merged['sweeps_100m']>0).sum()}")
print(f"  sweeps_200m — mean: {merged['sweeps_200m'].mean():.1f}, "
      f"max: {merged['sweeps_200m'].max()}, "
      f">0: {(merged['sweeps_200m']>0).sum()}")

# Distribution chart
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for ax, r, col in zip(axes, RADII, ['sweeps_100m', 'sweeps_200m']):
    vals = merged[col][merged[col] <= merged[col].quantile(0.98)]
    ax.hist(vals, bins=30, color='steelblue', edgecolor='white', alpha=0.85)
    ax.axvline(vals.mean(), color='#d73027', linewidth=2,
               label=f'Mean = {vals.mean():.1f}')
    ax.set_xlabel(f'Number of sweeps within {r} m', fontsize=11)
    ax.set_ylabel('Respondents', fontsize=11)
    ax.set_title(f'Sweeps within {r} m of Respondent', fontsize=12, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(f'{OUTDIR}fig3_proximity_sweeps.png', dpi=150)
plt.close()
print("  Saved: fig3_proximity_sweeps.png")


# ─── 6. Person-Level Dataset ──────────────────────────────────────────────────
print("\nBuilding person-level dataset...")

# Shelter preference columns: rank attributes, DCE choices, outside options
rank_cols     = [c for c in merged.columns if c.startswith('Rank___')]
preferred_cols = [c for c in merged.columns if c.startswith('Preferred_')]
outside_cols  = [c for c in merged.columns if c.startswith('Outside_Option')]
trigger_cols  = [c for c in merged.columns if c.startswith('trigger___')]

# Compute a summary shelter acceptance score:
# outside_option = "Yes" means respondent would rather stay outside → shelter aversion
for c in outside_cols:
    merged[c + '_num'] = (merged[c] == 'Yes').astype(float)
outside_num_cols = [c + '_num' for c in outside_cols]
merged['shelter_aversion_score'] = merged[outside_num_cols].mean(axis=1)

# Top-ranked shelter attribute (rank=1 most important)
if rank_cols:
    # pd.read_stata loads these as string-labeled categories ('1'..'12'),
    # not numeric, so eq(1) below needs actual ints to match against
    merged[rank_cols] = merged[rank_cols].apply(
        lambda col: pd.to_numeric(col.astype(str), errors='coerce')
    )
    merged['top_shelter_attribute'] = (
        merged[rank_cols]
        .apply(lambda row: row.index[row.eq(1).values.argmax()]
               if row.eq(1).any() else np.nan, axis=1)
    )
    merged['top_shelter_attribute'] = (
        merged['top_shelter_attribute']
        .astype(str)
        .str.replace('Rank___', '')
        .str.replace('_', ' ')
        .replace('nan', np.nan)
    )

person_cols = (
    ['new_id', 'Response_ID', 'Recorded_Date',
     'best_lat', 'best_lon',
     'input_category', 'distance_m',
     'sweep', 'gender', 'age',
     'race_White', 'race_Hispanic', 'race_Black',
     'last_30_noshelter', '_3year_noshelter',
     'sweeps_100m', 'closures_100m',
     'sweeps_200m', 'closures_200m',
     'shelter_aversion_score']
    + (['top_shelter_attribute'] if 'top_shelter_attribute' in merged.columns else [])
    + rank_cols
    + preferred_cols
    + outside_cols
    + trigger_cols
)
person_cols = [c for c in person_cols if c in merged.columns]

person_df = merged[person_cols].copy()
person_df.to_csv(f'{OUTDIR}person_level_dataset.csv', index=False)
print(f"  Saved: person_level_dataset.csv ({person_df.shape})")


# ─── 7. Summary Statistics ───────────────────────────────────────────────────
print("\n" + "═"*62)
print("  SUMMARY FINDINGS")
print("═"*62)

# Encampment sweep trends
print("\n[Encampment Operations – City of Oakland]")
print(f"  Total operations in dataset: {len(enc):,}")
print(f"  Date range: {enc['start_date'].min().date()} to {enc['start_date'].max().date()}")
era_n = enc.groupby('policy_era').size()
for era in era_order:
    print(f"  {era_labels[era].replace(chr(10),' ')}: {era_n.get(era, 0):,} operations")

# Monthly averages by era
for era, lbl in era_labels.items():
    sub = enc[enc['policy_era'] == era]
    monthly_ct = sub.groupby(pd.Grouper(key='start_date', freq='ME')).size()
    print(f"  → {lbl.replace(chr(10),' ')}: avg {monthly_ct.mean():.1f} ops/month")

print()
print("[Policy Event Impact]")
pre  = enc[enc['policy_era'] == 'pre_grants_pass']
post = enc[enc['policy_era'] == 'post_newsom_order']
pre_m  = pre.groupby(pd.Grouper(key='start_date', freq='ME')).size().mean()
post_m = post.groupby(pd.Grouper(key='start_date', freq='ME')).size().mean()
print(f"  Pre-Grants Pass monthly avg:       {pre_m:.1f}")
print(f"  Post-Newsom Order monthly avg:     {post_m:.1f}")
print(f"  Change: {((post_m - pre_m)/pre_m)*100:+.1f}%")

print()
print("[Survey Sample]")
print(f"  Total respondents: {len(merged):,}")
print(f"  With GPS / usable coordinates: {n_located:,} ({n_located/len(merged)*100:.0f}%)")
sweep_num = pd.to_numeric(merged['sweep'], errors='coerce')
print(f"  Self-reported sweep experience (sweep=1): "
      f"{int(sweep_num.sum())} ({sweep_num.mean()*100:.0f}%)")

print()
print("[Proximity Exposure to Sweeps]")
for r in RADII:
    col = f'sweeps_{r}m'
    any_sweep = (merged[col] > 0).sum()
    print(f"  Within {r}m — respondents with ≥1 sweep: "
          f"{any_sweep} ({any_sweep/len(merged)*100:.0f}%), "
          f"mean {merged[col].mean():.1f}, median {merged[col].median():.0f}")

print()
print("[Shelter Response Preferences]")
print(f"  Mean shelter aversion score (0=accepts shelter, 1=prefers outside): "
      f"{merged['shelter_aversion_score'].mean():.2f}")
if 'top_shelter_attribute' in merged.columns:
    top_attr = merged['top_shelter_attribute'].value_counts()
    print("  Top-ranked shelter attributes:")
    for attr, n in top_attr.head(5).items():
        print(f"    {attr}: {n} respondents")

# Self-reported sweeps vs objective proximity
merged['sweep_num'] = pd.to_numeric(merged['sweep'], errors='coerce')
if 'sweep_num' in merged.columns:
    s1 = merged[merged['sweep_num'] == 1]['sweeps_100m'].mean()
    s0 = merged[merged['sweep_num'] == 0]['sweeps_100m'].mean()
    print()
    print("[Self-reported sweep vs objective proximity (100m)]")
    print(f"  Swept respondents — avg sweeps within 100m: {s1:.1f}")
    print(f"  Not swept respondents — avg sweeps within 100m: {s0:.1f}")

print("\n" + "═"*62)
print("Output files saved to:", OUTDIR)
print("  survey_with_location.csv   — merged survey + GPS data")
print("  person_level_dataset.csv   — exposure + preferences per respondent")
print("  fig1_monthly_sweeps.png    — monthly operations chart")
print("  fig2_policy_comparison.png — pre/post policy comparison")
print("  fig3_proximity_sweeps.png  — sweep proximity distributions")
print("═"*62)
