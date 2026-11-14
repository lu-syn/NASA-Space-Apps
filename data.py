"""Simulated mission data for the Astronaut Radiation & Health Monitor.

Everything here is SIMULATED demo data, not clinical data. It stands in for
the real dosimeter, heart-rate sensor, SERS blood panel and daily check.
"""

import numpy as np
import pandas as pd

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

# Blood draws at 08:00. Day 4's draw is ~19-24 h after the flare, so the
# inflammation marker (CRP) peaks there, then decays.
BLOOD_HOUR = 8
BLOOD_PANEL = {
    #    day: (crp mg/L, cortisol µg/dL, glucose mg/dL)
    1: (1.0, 12.0, 90.0),
    2: (1.1, 12.5, 91.0),
    4: (7.0, 22.0, 105.0),
    5: (4.5, 20.0, 104.0),
    7: (1.6, 13.0, 92.0),
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


def _blood_panel(day, hour, rng):
    # Hook: blood values only at 08:00 on draw days; empty (NaN) otherwise.
    if hour != BLOOD_HOUR or day not in BLOOD_PANEL:
        return np.nan, np.nan, np.nan
    crp, cortisol, glucose = BLOOD_PANEL[day]
    # Small noise so values look measured, not typed in.
    crp = round(crp * (1 + rng.normal(0, 0.05)), 2)
    cortisol = round(cortisol * (1 + rng.normal(0, 0.03)), 1)
    glucose = round(glucose + rng.normal(0, 1.5))
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
    rows = []
    for i in range(MISSION_DAYS * 24):
        day, hour = i // 24 + 1, i % 24  # day is 1-based to match the scenario
        crp, cortisol, glucose = _blood_panel(day, hour, rng)
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
    for col in ["heart_rate", "glucose", "reaction_ms", "mood"]:
        df[col] = df[col].astype("Int64")
    return df[COLUMNS].sort_values("timestamp").reset_index(drop=True)
