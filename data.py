"""Simulated mission data for the Astronaut Radiation & Health Monitor.

Everything here is SIMULATED demo data, not clinical data. It stands in for
the real dosimeter, heart-rate sensor, SERS blood panel and daily check.
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Shared row format (other files depend on this exact order; don't rename).
COLUMNS = [
    "timestamp", "dose_rate", "total_dose", "heart_rate",
    "crp", "cortisol", "glucose", "reaction_ms", "mood",
]

# Mission timing
MISSION_START = pd.Timestamp("2026-11-16 00:00")  # day 1, 00:00
MISSION_DAYS = 7

# Baselines (units match the shared contract)
BASE_DOSE_RATE = 20.0   # µGy/h
BASE_HEART_RATE = 65.0  # bpm
BASE_REACTION = 300.0   # ms

# Solar flare on day 3. Multiplier of baseline dose for each flare hour:
# ramps up to ~28x at 13:00, then back down (spec: 10-30x baseline).
FLARE_DAY = 3
FLARE_DOSE_MULT = {10: 10, 11: 16, 12: 22, 13: 28, 14: 22, 15: 15, 16: 10}

# Heart rate boost as a fraction (+0.20 = +20%): during the flare and a few
# hours after, slowly easing off (spec: +15-25%).
FLARE_HR_BOOST = {10: 0.18, 11: 0.20, 12: 0.22, 13: 0.25, 14: 0.24, 15: 0.22,
                  16: 0.21, 17: 0.20, 18: 0.18, 19: 0.16, 20: 0.15}

# Blood baselines. Glucose is replaced by the real Inspiration4 pre-flight
# mean when data/i4_blood.csv exists (see _glucose_baseline below).
BASE_CRP = 1.0              # mg/L (kept simulated: real crew CRP varies 1-76 mg/L)
BASE_CORTISOL = 12.0        # µg/dL (not in OSD-575, so always simulated)
DEFAULT_BASE_GLUCOSE = 90.0  # mg/dL, fallback if the real file is missing
I4_PATH = Path(__file__).parent / "data" / "i4_blood.csv"

# Blood draws at 08:00, as multiples of each baseline. Day 4's draw is
# ~19-24 h after the flare, so the inflammation marker (CRP) peaks there.
# CRP peaks at only ~2.5x (not the 5-8x we first planned) because that is
# what real crew showed: Inspiration4 CRP right after landing (R+1) was
# ~0.8-2x each person's own pre-flight (L-3) value (data/i4_blood.csv,
# crp_fold_change). A milder rise keeps the demo honest to real data.
BLOOD_HOUR = 8
BLOOD_PANEL = {
    #    day: (crp x, cortisol x, glucose x)
    1: (1.0, 1.00, 1.00),
    2: (1.1, 1.04, 1.01),
    4: (2.5, 1.83, 1.17),
    5: (1.8, 1.67, 1.16),
    7: (1.2, 1.08, 1.02),
}

# Daily mood + cognitive check at 09:00.
CHECK_HOUR = 9
DAILY_CHECK = {
    #    day: (reaction slowdown fraction, mood 1-5)
    1: (0.00, 4),
    2: (0.00, 4),
    3: (0.00, 4),  # 09:00 is before the flare starts at 10:00
    4: (0.32, 2),
    5: (0.25, 2),
    6: (0.10, 3),
    7: (0.03, 4),
}


def _dose_rate(day, hour, rng):
    # Hook: baseline dose + noise, multiplied up during the day-3 flare.
    mult = FLARE_DOSE_MULT.get(hour, 1) if day == FLARE_DAY else 1
    value = BASE_DOSE_RATE * mult + rng.normal(0, 1.0)
    return round(value, 1)


def _heart_rate(day, hour, rng):
    # Hook: resting heart rate + noise, boosted during/after the flare.
    boost = FLARE_HR_BOOST.get(hour, 0.0) if day == FLARE_DAY else 0.0
    value = BASE_HEART_RATE * (1 + boost) + rng.normal(0, 2.0)
    return round(value)


def load_i4_reference() -> pd.DataFrame:
    # Hook: real Inspiration4 blood values (OSD-575) for the dashboard to compare.
    # Caveats: 4 crew, draws only before/after flight (never during), a 3-day
    # mission, and big differences between people. Empty table if file missing.
    if not I4_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(I4_PATH)


def _glucose_baseline():
    # Hook: crew's real pre-flight glucose mean, or 90 mg/dL if no file.
    ref = load_i4_reference()
    if ref.empty:
        return DEFAULT_BASE_GLUCOSE
    # Pre-flight = before launch; skip any values flagged as suspect.
    preflight = ref[(ref["days_from_launch"] < 0) & ref["flag"].isna()]
    return float(preflight["glucose"].mean())


def _blood_panel(day, hour, rng, base_glucose):
    # Hook: blood values only at 08:00 on draw days; empty (NaN) otherwise.
    if hour != BLOOD_HOUR or day not in BLOOD_PANEL:
        return np.nan, np.nan, np.nan
    crp_x, cortisol_x, glucose_x = BLOOD_PANEL[day]
    # Small noise so values look measured, not typed in.
    crp = round(BASE_CRP * crp_x * (1 + rng.normal(0, 0.05)), 2)
    cortisol = round(BASE_CORTISOL * cortisol_x * (1 + rng.normal(0, 0.03)), 1)
    glucose = round(base_glucose * glucose_x + rng.normal(0, 1.5))
    return crp, cortisol, glucose


def _daily_check(day, hour, rng):
    # Hook: reaction time + mood only at 09:00; empty (NaN) otherwise.
    if hour != CHECK_HOUR or day not in DAILY_CHECK:
        return np.nan, np.nan
    slowdown, mood = DAILY_CHECK[day]
    reaction = round(BASE_REACTION * (1 + slowdown) + rng.normal(0, 8))
    return reaction, mood


def generate_mission(seed=42):
    # Hook: 7 days x 24 hours = 168 simulated readings, same every run (seed).
    rng = np.random.default_rng(seed)  # fixed seed -> repeatable demo
    base_glucose = _glucose_baseline()  # read once, not for every hour
    rows = []
    for i in range(MISSION_DAYS * 24):
        day, hour = i // 24 + 1, i % 24  # day is 1-based to match the scenario
        crp, cortisol, glucose = _blood_panel(day, hour, rng, base_glucose)
        reaction_ms, mood = _daily_check(day, hour, rng)
        rows.append({
            "timestamp": MISSION_START + pd.Timedelta(hours=i),
            "dose_rate": _dose_rate(day, hour, rng),
            "heart_rate": _heart_rate(day, hour, rng),
            "crp": crp,
            "cortisol": cortisol,
            "glucose": glucose,
            "reaction_ms": reaction_ms,
            "mood": mood,
        })

    df = pd.DataFrame(rows)
    # Each reading covers 1 hour, so µGy/h x 1 h = µGy; /1000 converts to mGy.
    df["total_dose"] = (df["dose_rate"].cumsum() / 1000).round(3)
    # "Int64" keeps whole numbers while still allowing empty cells.
    for col in INT_COLUMNS:
        df[col] = df[col].astype("Int64")
    return df[COLUMNS].sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# SQLite storage (mission.db). The spacecraft keeps its own copy first, so the
# dashboard works even with no link to Earth; Cloudflare sync comes later.
# ---------------------------------------------------------------------------

# Next to this file, so it works no matter which folder you run from.
DB_PATH = Path(__file__).parent / "mission.db"

# Whole-number columns (pandas "Int64" allows empty cells).
INT_COLUMNS = ["heart_rate", "glucose", "reaction_ms", "mood"]

# timestamp is UNIQUE so saving the same hour twice replaces it instead of
# making a duplicate (lets you re-run __main__ safely).
# synced = 0/1 is for the later sync_to_ground step: 0 means "not sent yet".
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    timestamp   TEXT PRIMARY KEY,
    dose_rate   REAL,
    total_dose  REAL,
    heart_rate  INTEGER,
    crp         REAL,
    cortisol    REAL,
    glucose     INTEGER,
    reaction_ms INTEGER,
    mood        INTEGER,
    synced      INTEGER NOT NULL DEFAULT 0
)
"""


def _connect():
    # Hook: open mission.db and make sure the table exists.
    conn = sqlite3.connect(DB_PATH)
    conn.execute(CREATE_TABLE_SQL)
    return conn


def _to_sql_value(value):
    # Hook: turn pandas/numpy values into plain Python values SQLite accepts.
    if value is None or pd.isna(value):
        return None  # empty cell -> NULL
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")  # text sorts in time order
    if isinstance(value, np.generic):
        return value.item()  # numpy number -> normal int/float
    return value


def save_reading(row: dict) -> None:
    # Hook: one reading in -> one row in mission.db (same timestamp = replace).
    timestamp = pd.Timestamp(row["timestamp"])  # accept a string or Timestamp
    values = [_to_sql_value(timestamp)]
    values += [_to_sql_value(row.get(col)) for col in COLUMNS[1:]]
    placeholders = ", ".join("?" for _ in COLUMNS)
    sql = (f"INSERT OR REPLACE INTO readings ({', '.join(COLUMNS)}) "
           f"VALUES ({placeholders})")
    with closing(_connect()) as conn:
        with conn:  # commits on success, rolls back on error
            conn.execute(sql, values)


def load_mission() -> pd.DataFrame:
    # Hook: everything in mission.db -> DataFrame, oldest reading first.
    with closing(_connect()) as conn:
        df = pd.read_sql_query(
            f"SELECT {', '.join(COLUMNS)} FROM readings ORDER BY timestamp", conn
        )
    # SQLite gives back text and plain numbers; restore the same types that
    # generate_mission() produces so the rest of the app sees one format.
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col])
    for col in INT_COLUMNS:
        df[col] = df[col].astype("Int64")
    return df


def _print_summary(df):
    # Hook: a quick sanity check you can read in the terminal.
    peak = df.loc[df["dose_rate"].idxmax()]
    print(f"Readings stored : {len(df)}")
    print(f"From            : {df['timestamp'].min()}")
    print(f"To              : {df['timestamp'].max()}")
    # "uGy/h" not "µGy/h": some Windows terminals can't print the µ sign.
    print(f"Peak dose rate  : {peak['dose_rate']} uGy/h at {peak['timestamp']}")
    print(f"Total dose      : {df['total_dose'].iloc[-1]} mGy")
    print(f"Blood draws     : {df['crp'].notna().sum()}")
    print(f"Daily checks    : {df['mood'].notna().sum()}")
    source = "Inspiration4 pre-flight mean" if I4_PATH.exists() else "default"
    print(f"Glucose baseline: {_glucose_baseline():.1f} mg/dL ({source})")
    print("\nBlood draws:")
    draws = df.dropna(subset=["crp"])[["timestamp", "crp", "cortisol", "glucose"]]
    print(draws.to_string(index=False))


# ---------------------------------------------------------------------------
# Sync to ground (Cloudflare Worker). The ship stores everything locally first;
# this sends what Earth hasn't seen yet. A failed link must never crash the app.
# ---------------------------------------------------------------------------

# Default pause before sending. Real Earth-Mars delay is ~4-24 minutes one way;
# 5 seconds keeps the demo quick while still showing that a delay exists.
DEFAULT_SYNC_DELAY = 5
HTTP_TIMEOUT = 10  # seconds per request, so a dead link can't hang the app
# Fallback rule (only if rules.py is missing): red at 10x baseline dose rate.
FALLBACK_RED_DOSE = 10 * BASE_DOSE_RATE


def _statuses(df):
    # Hook: green/yellow/red for every row, from rules.py if we have it.
    try:
        import rules  # Liz's alert rules (ai branch, merged into main)
        baseline = rules.get_baseline(df)
        # history = all rows up to this one, because some rules look back in time.
        statuses = [rules.status_for(df.iloc[i], baseline, df.iloc[: i + 1])
                    for i in range(len(df))]
        return statuses, "rules.py status_for"
    except ImportError:
        statuses = ["red" if rate >= FALLBACK_RED_DOSE else "green"
                    for rate in df["dose_rate"]]
        return statuses, "fallback (red if dose_rate >= 10x baseline)"


def _unsynced_timestamps():
    # Hook: which readings has Earth not received yet? (synced = 0)
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT timestamp FROM readings WHERE synced = 0 ORDER BY timestamp"
        ).fetchall()
    return {row[0] for row in rows}


def _mark_synced(timestamp):
    # Hook: Earth confirmed this reading -> never send it again.
    with closing(_connect()) as conn:
        with conn:
            conn.execute("UPDATE readings SET synced = 1 WHERE timestamp = ?",
                         (timestamp,))


def _post_reading(url, key, payload):
    # Hook: one reading -> one POST to the Worker. Raises if it didn't arrive.
    request = urllib.request.Request(
        f"{url.rstrip('/')}/readings",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sync-Key": key,
            # Some sites block urllib's default user agent, so name ourselves.
            "User-Agent": "astro-monitor-sync/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT):
        pass  # any 2xx is success; errors raise HTTPError / URLError


def sync_to_ground(delay_seconds=DEFAULT_SYNC_DELAY) -> int:
    # Hook: wait (comm delay), POST every unsynced row, mark each one synced.
    # Returns how many rows reached Earth. Never raises on network trouble.
    load_dotenv()
    url, key = os.getenv("WORKER_URL"), os.getenv("SYNC_KEY")
    if not url or not key:
        print("WARNING: WORKER_URL or SYNC_KEY missing in .env - sync skipped.")
        return 0

    df = load_mission()
    waiting = _unsynced_timestamps()
    if not waiting:
        print("Nothing to sync - Earth is up to date.")
        return 0

    # Status uses the WHOLE mission (baseline = first 3 days), not just new rows.
    statuses, source = _statuses(df)
    print(f"{len(waiting)} readings waiting. Status from: {source}")
    print(f"Simulating Earth communication delay: {delay_seconds} s ...")
    time.sleep(delay_seconds)

    sent = 0
    for (_, row), status in zip(df.iterrows(), statuses):
        payload = {col: _to_sql_value(row[col]) for col in COLUMNS}
        if payload["timestamp"] not in waiting:
            continue
        payload["status"] = status
        try:
            _post_reading(url, key, payload)
        except urllib.error.HTTPError as err:
            if err.code == 400:
                # Bad data won't fix itself by retrying: skip it, keep going.
                print(f"WARNING: Worker rejected {payload['timestamp']} "
                      f"(400: {err.read().decode(errors='replace')}). Skipped.")
                continue
            # 401 (wrong key), 5xx, etc.: stop now; unsent rows retry next time.
            print(f"WARNING: Worker error {err.code} - stopping, will retry later.")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            print(f"WARNING: can't reach Worker ({err}) - will retry later.")
            break
        _mark_synced(payload["timestamp"])  # only after Earth confirmed it
        sent += 1

    left = len(_unsynced_timestamps())
    print(f"Synced {sent} readings to ground. Still waiting: {left}.")
    return sent


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        # `python data.py sync`      -> send unsynced readings (5 s delay)
        # `python data.py sync 0`    -> same, no delay
        delay = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SYNC_DELAY
        sync_to_ground(delay)
    else:
        # `python data.py` -> (re)build mission.db from the simulated mission.
        mission = generate_mission()
        for record in mission.to_dict("records"):
            save_reading(record)
        print(f"Saved simulated mission to {DB_PATH.name}\n")
        _print_summary(load_mission())
