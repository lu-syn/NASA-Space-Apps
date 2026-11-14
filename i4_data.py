"""Real Inspiration4 crew blood data from NASA OSDR OSD-575.

Source: NASA Open Science Data Repository, OSD-575 (Inspiration4 crew blood:
CBC / CMP / cytokine panels). Files are downloaded BY HAND into data/raw/
(not committed); we never call the OSDR API, so the demo works offline.

Caveats (keep in mind when comparing to our simulated mission):
- Only 4 crew members (C001-C004), so averages are very noisy.
- Blood was drawn before flight (L-) and after flight (R+), never DURING flight.
- Inspiration4 was a 3-day mission, shorter than our 7-day scenario.
- Individual differences between crew are large.

Step 1 (this file for now): inspect the raw files so we can map columns and
units correctly before writing data/i4_blood.csv.
"""

from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent / "data" / "raw"

# Words we are hunting for in analyte / column names.
TARGETS = ["glucose", "crp", "c-reactive", "cortisol"]


def _read_raw(path):
    # Hook: read one raw CSV; "utf-8-sig" drops the hidden BOM some files start with.
    return pd.read_csv(path, encoding="utf-8-sig")


def _is_long_format(df):
    # Hook: "long" files have one row per measurement with an Analyte column.
    return any(col.lower() == "analyte" for col in df.columns)


def _print_long_file(df):
    # Hook: long files -> list each analyte once with its unit.
    analyte_col = next(c for c in df.columns if c.lower() == "analyte")
    unit_col = next(c for c in df.columns if c.lower() in ("unit", "units"))
    units = df.groupby(analyte_col)[unit_col].first()
    print(f"Columns: {list(df.columns)}")
    print(f"{len(units)} analytes (name -> unit):")
    for name, unit in units.items():
        print(f"    {name} -> {unit}")


def _print_wide_file(df):
    # Hook: wide files -> one column per measurement, unit is in the column name.
    print(f"{len(df.columns)} columns (unit is part of each name):")
    for col in df.columns:
        print(f"    {col}")


def _find_targets(df):
    # Hook: where do glucose / CRP / cortisol appear in this file?
    hits = []
    if _is_long_format(df):
        analyte_col = next(c for c in df.columns if c.lower() == "analyte")
        names = df[analyte_col].astype(str).unique()
    else:
        names = df.columns
    for name in names:
        if any(word in str(name).lower() for word in TARGETS):
            hits.append(str(name))
    return hits


def inspect_raw():
    # Hook: print columns, units, sample rows and target hits for every raw CSV.
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        print(f"No CSV files found in {RAW_DIR}")
        return
    found = {}
    for path in files:
        df = _read_raw(path)
        print("=" * 78)
        print(f"{path.name}  ({len(df)} rows x {len(df.columns)} columns)")
        print("=" * 78)
        if _is_long_format(df):
            _print_long_file(df)
        else:
            _print_wide_file(df)
        print("First 3 rows:")
        print(df.head(3).to_string(max_cols=8))
        print()
        found[path.name] = _find_targets(df)

    print("=" * 78)
    print("WHERE ARE GLUCOSE / CRP / CORTISOL?")
    for name, hits in found.items():
        print(f"  {name}: {hits if hits else '-'}")


# ---------------------------------------------------------------------------
# Build the small clean file data/i4_blood.csv from the raw downloads.
# ---------------------------------------------------------------------------

CLEAN_PATH = Path(__file__).parent / "data" / "i4_blood.csv"

# Long-format raw files (one row per measurement).
GLUCOSE_FILE = "LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv"
CRP_FILE = "LSDS-8_Multiplex_serum.cardiovascular.EvePanel_SUBMITTED.csv"

# Inspiration4 flew 3 days. "R+n" counts days after RETURN, so from launch
# it is 3 + n. "L-n" is n days before launch.
MISSION_LENGTH_DAYS = 3

# CRP in the raw file is pg/mL (Unit column + "picogram_per_milliliter" in the
# transformed file). Our app uses mg/L: 1 mg/L = 1,000,000 pg/mL.
PG_PER_ML_IN_MG_PER_L = 1_000_000

# Three of four crew read 36-44 mg/dL at R+45, far below the others and the
# lab range (65-99): likely a sample-handling issue, not real hypoglycemia.
# Flag by value, not timepoint, so normal readings (C001 R+45 = 84) stay clean.
SUSPECT_LOW_GLUCOSE = 50  # mg/dL

CLEAN_COLUMNS = ["crew_id", "timepoint", "days_from_launch",
                 "glucose", "crp", "crp_fold_change", "flag"]


def _days_from_launch(timepoint):
    # Hook: "L-92" -> -92, "R+1" -> 3 + 1 = 4.
    if timepoint.startswith("L-"):
        return -int(timepoint[2:])
    if timepoint.startswith("R+"):
        return MISSION_LENGTH_DAYS + int(timepoint[2:])
    raise ValueError(f"Unknown timepoint label: {timepoint}")


def _load_glucose():
    # Hook: glucose rows from the metabolic panel (already mg/dL).
    df = _read_raw(RAW_DIR / GLUCOSE_FILE)
    df = df[df["ANALYTE"] == "GLUCOSE"]
    return df.rename(columns={"SUBJECT_ID": "crew_id", "VALUE": "glucose"})[
        ["crew_id", "timepoint", "glucose"]]


def _load_crp():
    # Hook: CRP rows from the cardiovascular panel, converted pg/mL -> mg/L.
    df = _read_raw(RAW_DIR / CRP_FILE)
    df = df[df["Analyte"] == "CRP"]
    assert set(df["Unit"].str.lower()) == {"pg/ml"}, "CRP unit changed - recheck!"
    df = df.rename(columns={"ID": "crew_id", "Timepoint": "timepoint"})
    df["crp"] = df["Concentration"] / PG_PER_ML_IN_MG_PER_L
    return df[["crew_id", "timepoint", "crp"]]


def _add_crp_fold_change(df):
    # Hook: each person's CRP divided by their OWN L-3 value (pre-flight = 1.0).
    # Crew differ hugely in absolute CRP, so the pattern over time is the
    # useful part; we use it as a reference shape, not as real baselines.
    l3 = df[df["timepoint"] == "L-3"].set_index("crew_id")["crp"]
    df["crp_fold_change"] = df["crp"] / df["crew_id"].map(l3)
    return df


def build_i4_blood():
    # Hook: raw OSD-575 files -> one tidy row per crew member per blood draw.
    df = _load_glucose().merge(_load_crp(), on=["crew_id", "timepoint"], how="outer")
    df["days_from_launch"] = df["timepoint"].map(_days_from_launch)
    df = _add_crp_fold_change(df)
    df["flag"] = ""
    df.loc[df["glucose"] < SUSPECT_LOW_GLUCOSE, "flag"] = "suspect_low"
    df["glucose"] = df["glucose"].astype("Int64")  # merge made it 83.0; keep 83
    df["crp"] = df["crp"].round(2)
    df["crp_fold_change"] = df["crp_fold_change"].round(2)
    df = df.sort_values(["crew_id", "days_from_launch"])[CLEAN_COLUMNS]
    df.to_csv(CLEAN_PATH, index=False)
    return df


if __name__ == "__main__":
    # `python i4_data.py`          -> write data/i4_blood.csv
    # `python i4_data.py inspect`  -> print what is inside every raw file
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "inspect":
        inspect_raw()
    else:
        clean = build_i4_blood()
        print(f"Wrote {len(clean)} rows to {CLEAN_PATH.relative_to(Path(__file__).parent)}\n")
        print(clean.to_string(index=False))
