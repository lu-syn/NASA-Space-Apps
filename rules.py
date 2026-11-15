"""rules.py - local alert rules. No Gemini in here, so red alerts show instantly.

Thresholds come from the alert table in the hackathon plan. Most compare to the
astronaut's own baseline (first 3 days). The overall status is the worst signal.
"""
import pandas as pd

MISSION_DOSE_BUDGET = 10.0   # same units as the total_dose column; agree on this with the data person
BASELINE_DAYS = 3
LEVELS = {"green": 0, "yellow": 1, "red": 2}


def worst(*statuses):
    return max(statuses, key=lambda s: LEVELS[s])


def get_baseline(df):
    """Typical value of each signal over the first 3 days.

    Uses the median (not the mean) so a day-3 solar flare doesn't inflate the baseline.
    """
    t = pd.to_datetime(df["timestamp"])
    early = df[t < t.min() + pd.Timedelta(days=BASELINE_DAYS)]
    cols = ["dose_rate", "heart_rate", "crp", "cortisol", "reaction_ms"]
    return {c: early[c].median() for c in cols}  # median skips empty cells


def _ratio(value, base, yellow, red):
    """Green/yellow/red by how many times bigger `value` is than `base`."""
    if pd.isna(value) or pd.isna(base) or base == 0:
        return "green"
    r = value / base
    return "red" if r >= red else "yellow" if r >= yellow else "green"


def _limit(value, yellow, red):
    """Green/yellow/red against fixed numbers ('above 100' means strictly above)."""
    if pd.isna(value):
        return "green"
    return "red" if value > red else "yellow" if value > yellow else "green"


def _streak(values, test):
    """How many of the most recent values in a row pass `test`."""
    n = 0
    for v in reversed(list(values)):
        if not test(v):
            break
        n += 1
    return n


def signal_statuses(row, baseline, history):
    """Status of every signal for one reading.

    `history` = all rows up to and including `row` (needed for the 'for 2+ days' rules).
    """
    def latest(col):
        """Most recent value that exists (blood and daily-check cells are empty on most hourly rows)."""
        vals = history[col].dropna()
        return vals.iloc[-1] if len(vals) else float("nan")

    out = {
        "dose_rate": _ratio(row["dose_rate"], baseline["dose_rate"], 3, 10),
        "mission_dose": _limit(row["total_dose"] / MISSION_DOSE_BUDGET, 0.5, 0.8),
        "heart_rate": _ratio(row["heart_rate"], baseline["heart_rate"], 1.15, 1.30),
        "crp": _ratio(latest("crp"), baseline["crp"], 2, 5),
        "glucose": _limit(latest("glucose"), 100, 126),
        "reaction": _ratio(latest("reaction_ms"), baseline["reaction_ms"], 1.15, 1.30),
    }


    # Cortisol: the last 2 blood draws both high (draws are every 1-2 days).
    cort = history["cortisol"].dropna() / baseline["cortisol"]
    if _streak(cort, lambda v: v >= 2.0) >= 2:
        out["cortisol"] = "red"
    elif _streak(cort, lambda v: v >= 1.5) >= 2:
        out["cortisol"] = "yellow"
    else:
        out["cortisol"] = "green"

    # Mood: consecutive recent days with a daily average of 2 or lower.
    day = pd.to_datetime(history["timestamp"]).dt.date
    daily_mood = history["mood"].groupby(day).mean().dropna()
    low_days = _streak(daily_mood, lambda v: v <= 2)
    out["mood"] = "red" if low_days >= 5 else "yellow" if low_days >= 3 else "green"
    return out


def status_for(row, baseline, history=None):
    """Overall status for one reading: 'green', 'yellow' or 'red'."""
    if history is None:
        history = pd.DataFrame([row])
    return worst(*signal_statuses(row, baseline, history).values())


def recent_dose_spike(history, baseline, hours=48):
    """True if dose rate was 3x baseline or more at any point in the last `hours` hours."""
    t = pd.to_datetime(history["timestamp"])
    window = history[t >= t.max() - pd.Timedelta(hours=hours)]
    return bool((window["dose_rate"] >= 3 * baseline["dose_rate"]).any())


def local_evaluation(df):
    """Status of the latest reading plus the per-signal breakdown (handy for the dashboard colors)."""
    baseline = get_baseline(df)
    signals = signal_statuses(df.iloc[-1], baseline, df)
    return {"status": worst(*signals.values()), "signals": signals, "baseline": baseline}


def demo_df():
    """Fake 7-day mission with a day-3 solar flare, for testing on your own."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-11-14", periods=7, freq="D"),
        "dose_rate": [1.0, 1.1, 14.0, 4.0, 2.0, 1.0, 1.0],
        "total_dose": [5, 10, 40, 55, 60, 62, 64],
        "heart_rate": [60, 61, 80, 72, 66, 62, 61],
        "crp": [1.0, None, 1.1, 6.0, None, 3.0, None],
        "cortisol": [10, None, 11, 24, None, 23, None],
        "glucose": [90, None, 92, 95, None, 91, None],
        "reaction_ms": [300, 305, 310, 330, 320, 305, 300],
        "mood": [4, 4, 3, 2, 2, 3, 4],
    })


if __name__ == "__main__":
    df = demo_df()
    base = get_baseline(df)
    for i in range(len(df)):
        sub = df.iloc[: i + 1]
        print(sub.iloc[-1]["timestamp"].date(), status_for(sub.iloc[-1], base, sub))
    print(local_evaluation(df)["signals"])
