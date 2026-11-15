"""ai.py - Gemini evaluation and the daily check.

Radiation alerts do NOT depend on this file (see rules.py). Gemini explains and advises.
"""
import json
import os
import random
import re

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

from rules import (MISSION_DOSE_BUDGET, demo_df, get_baseline, local_evaluation,
                   recent_dose_spike, worst)

load_dotenv()

MODEL = "gemini-4-hydrogen"
DISCLAIMER = "This tool supports, and does not replace, the flight surgeon."
VALID_STATUS = {"green", "yellow", "red"}

SYSTEM_PROMPT = """You are the analysis engine of an astronaut radiation and health dashboard.
This is a hackathon demo, not clinical guidance. All blood values (CRP, cortisol, glucose) are simulated.

You receive the latest reading, the baseline, daily trends for the past 7 days, and the status
that the local alert rules already computed.

Rules:
- Compare values to this astronaut's own baseline, never to population norms.
- A rising CRP counts as radiation-related ONLY if recent_dose_spike_48h is true.
  Otherwise call it "possible infection or strain".
- Never return a status lower than local_status.
- Keep reasons and actions short, specific and in plain language. At most 4 of each.
- If the status is red, one action must be to contact the flight surgeon.
- Reply with JSON only, in exactly this shape:
  {"status": "green|yellow|red", "reasons": ["..."], "actions": ["..."]}"""


_client_cache = None


def _client():
    global _client_cache
    if _client_cache is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is missing. Check your .env file.")
        _client_cache = genai.Client(api_key=key)
    return _client_cache


def _load_json(text):
    text = text.strip()
    if text.startswith("```"):                       # strip ```json fences if Gemini adds them
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def _ask_json(contents, system, validate):
    """Ask Gemini for JSON. Try once, retry once, then raise. Never invents an answer."""
    last_err = None
    for _ in range(2):
        try:
            resp = _client().models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return validate(_load_json(resp.text))
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Gemini failed twice: {last_err}")


# ---------- evaluate(df) ----------

def _check_evaluation(data):
    if (not isinstance(data, dict) or data.get("status") not in VALID_STATUS
            or not isinstance(data.get("reasons"), list)
            or not isinstance(data.get("actions"), list)):
        raise ValueError("Gemini returned JSON in the wrong shape")
    return data


def _daily_trends(df):
    """One row per day for the last 7 days (keeps the prompt small)."""
    t = pd.to_datetime(df["timestamp"])
    df = df[t >= t.max() - pd.Timedelta(days=7)]
    day = pd.to_datetime(df["timestamp"]).dt.date.astype(str)
    g = df.groupby(day)
    trends = pd.DataFrame({
        "dose_rate_max": g["dose_rate"].max(),
        "total_dose": g["total_dose"].max(),
        "heart_rate": g["heart_rate"].mean(),
        "crp": g["crp"].mean(),
        "cortisol": g["cortisol"].mean(),
        "glucose": g["glucose"].mean(),
        "reaction_ms": g["reaction_ms"].mean(),
        "mood": g["mood"].mean(),
    }).round(2)
    trends.index.name = "day"
    return json.loads(trends.reset_index().to_json(orient="records"))   # NaN becomes null


def evaluate(df):
    """Returns {status, reasons, actions, signals, disclaimer}, or {"error": "..."}."""
    if df is None or len(df) == 0:
        return {"error": "No data to evaluate."}

    local = local_evaluation(df)
    baseline = {k: (None if pd.isna(v) else round(float(v), 2)) for k, v in local["baseline"].items()}
    payload = {
        "latest_reading": json.loads(df.tail(1).to_json(orient="records", date_format="iso"))[0],
        "baseline": baseline,
        "daily_trends": _daily_trends(df),
        "local_status": local["status"],
        "local_signal_statuses": local["signals"],
        "recent_dose_spike_48h": recent_dose_spike(df, local["baseline"]),
    }

    try:
        data = _ask_json(json.dumps(payload), SYSTEM_PROMPT, _check_evaluation)
    except Exception as e:
        return {"error": str(e)}

    status = worst(local["status"], data["status"])      # Gemini can raise the alert, never lower it
    actions = list(data["actions"])
    if status == "red" and not any("flight surgeon" in a.lower() for a in actions):
        actions.append("Contact the flight surgeon.")
    return {
        "status": status,
        "reasons": data["reasons"],
        "actions": actions,
        "signals": local["signals"],
        "disclaimer": DISCLAIMER,
    }


# ---------- explain_status(row, flags, history) ----------

# Plain-language versions of the thresholds in rules.signal_statuses, so Gemini
# explains the SAME rules that colored the screen. Keep in sync with rules.py.
RULE_TEXT = {
    "dose_rate": "Dose rate: yellow at 3x baseline, red at 10x baseline.",
    "mission_dose": f"Mission total dose: yellow above 50%, red above 80% of the {MISSION_DOSE_BUDGET:g} mGy demo budget.",
    "heart_rate": "Resting heart rate: yellow at 15% above baseline, red at 30% above.",
    "crp": "CRP (latest draw): yellow at 2x baseline, red at 5x.",
    "glucose": "Fasting glucose (latest draw): yellow above 100 mg/dL, red above 126 mg/dL.",
    "reaction": "Reaction time (latest check): yellow at 15% slower than baseline, red at 30% slower.",
    "cortisol": "Cortisol: yellow if the last 2 draws are both 1.5x baseline or more, red at 2x.",
    "mood": "Mood: yellow after 3 days in a row averaging 2 or lower, red after 5 days.",
}

EXPLAIN_PROMPT = f"""You explain an astronaut health dashboard's alerts in plain language.
Hackathon demo: all data is simulated. Never diagnose a disease or condition; describe what the
numbers show and what the onboard guidance suggests. The alert colors were already set by fixed
rules; explain them, never change or argue with them.
Compare to this astronaut's own baseline. Call a CRP rise "likely radiation-related" ONLY if
recent_dose_spike_48h is true; otherwise say "possible infection or strain".
If any flag is red, one action must be to contact the flight surgeon.
Reply with JSON only, exactly:
{{"summary": "<one plain sentence>", "why": "<short reason>", "actions": ["<2 or 3 short steps>"]}}
The summary or why must briefly say: "{DISCLAIMER}\""""


def _check_explanation(data):
    if not isinstance(data, dict):
        raise ValueError("Gemini returned JSON in the wrong shape")
    actions = data.get("actions")
    if (not isinstance(data.get("summary"), str) or not isinstance(data.get("why"), str)
            or not isinstance(actions, list) or not 2 <= len(actions) <= 3
            or not all(isinstance(a, str) for a in actions)):
        raise ValueError("Gemini returned JSON in the wrong shape")
    return {"summary": data["summary"], "why": data["why"], "actions": actions}


def _trends_72h(history):
    """Last 72 h: dose and heart rate as 3-hour averages, plus every blood/check result."""
    t = pd.to_datetime(history["timestamp"])
    recent = history[t >= t.max() - pd.Timedelta(hours=72)].copy()
    recent["timestamp"] = pd.to_datetime(recent["timestamp"])
    live = (recent.set_index("timestamp")[["dose_rate", "heart_rate"]]
            .resample("3h").mean().round(1).reset_index())
    periodic = recent[["timestamp", "crp", "cortisol", "glucose", "reaction_ms", "mood"]]
    periodic = periodic.dropna(how="all", subset=periodic.columns[1:])
    as_records = lambda df: json.loads(df.to_json(orient="records", date_format="iso"))  # NaN -> null
    peak = recent.loc[recent["dose_rate"].idxmax()]  # true hourly peak (averages hide it)
    return {"every_3h": as_records(live), "measurements": as_records(periodic),
            "dose_rate_peak": {"value": float(peak["dose_rate"]), "time": peak["timestamp"].isoformat()}}


def explain_status(row, flags, history):
    """Gemini explains the current alerts. flags = {signal: "yellow"/"red"} from rules.py.

    Returns {"summary", "why", "actions"} or None on any error (no key, offline, bad JSON).
    """
    try:
        baseline = get_baseline(history)
        payload = {
            "current_reading": json.loads(pd.Series(row).to_json(date_format="iso")),
            "baseline_first_3_days": {k: (None if pd.isna(v) else round(float(v), 2))
                                      for k, v in baseline.items()},
            "flagged_signals": [{"signal": k, "status": s, "rule": RULE_TEXT.get(k, "")}
                                for k, s in flags.items()],
            "recent_dose_spike_48h": recent_dose_spike(history, baseline),
            "last_72h": _trends_72h(history),
        }
        result = _ask_json(json.dumps(payload), EXPLAIN_PROMPT, _check_explanation)
    except Exception:
        return None
    # Safety net: red always ends with the flight surgeon, even if Gemini forgot.
    if "red" in flags.values() and not any("flight surgeon" in a.lower() for a in result["actions"]):
        result["actions"].append("Contact the flight surgeon.")
    return result


# ---------- summarize_check_ins(df) ----------

JOURNAL_PROMPT = f"""You read an astronaut's recent daily check-ins (hackathon demo; rows marked
simulated are demo data). Each has: mission day, mood (1 = very low, 5 = very good), memory
recall (% of 5 words remembered) and reaction time (ms, lower is faster).
Write 2-3 plain, kind sentences about the TREND, for example
"Your memory recall has improved since day 4." Compare days with each other; use the numbers.
Never diagnose a disease or condition and never give medical advice.
Then add this exact sentence: "{DISCLAIMER}"
Reply with JSON only: {{"summary": "<your sentences>"}}"""


def summarize_check_ins(df):
    """Gemini's 2-3 sentence trend summary of check-ins (from data.load_check_ins).

    Returns the text, or None on any error (no key, offline, bad JSON, no data).
    """
    try:
        from data import MISSION_START  # day numbers like the dashboard ("day 4")
        if df is None or len(df) == 0:
            return None
        rows = df.sort_values("timestamp")  # oldest first reads as a trend
        entries = [{
            "mission_day": (pd.Timestamp(r["timestamp"]) - MISSION_START).days + 1,
            "date": str(pd.Timestamp(r["timestamp"]).date()),
            "mood": None if pd.isna(r["mood"]) else int(r["mood"]),
            "memory_percent": None if pd.isna(r["memory_score"]) else float(r["memory_score"]),
            "reaction_ms": None if pd.isna(r["reaction_ms"]) else int(r["reaction_ms"]),
            "simulated": bool(r.get("simulated", 0)),
        } for _, r in rows.iterrows()]

        def check(data):
            if not (isinstance(data, dict) and isinstance(data.get("summary"), str)
                    and data["summary"].strip()):
                raise ValueError("Gemini returned JSON in the wrong shape")
            return data["summary"].strip()

        summary = _ask_json(json.dumps(entries), JOURNAL_PROMPT, check)
    except Exception:
        return None
    # Safety net: the flight-surgeon sentence is always there.
    return summary if "flight surgeon" in summary.lower() else f"{summary} {DISCLAIMER}"


# ---------- daily check ----------

DEFAULT_QUESTIONS = [
    "How would you describe your mood today?",
    "How well did you sleep last night?",
    "Is anything weighing on you or making you feel on edge?",
]
WORDS = ["river", "copper", "lantern", "meadow", "orbit", "violin", "harbor",
         "pencil", "comet", "garden", "anchor", "marble", "thunder", "candle"]


def get_mood_questions(n=3):
    """Short check-in questions from Gemini. Falls back to a fixed list (questions only, never a status)."""
    def check(data):
        if not (isinstance(data, list) and len(data) == n and all(isinstance(q, str) for q in data)):
            raise ValueError("expected a list of strings")
        return data
    try:
        return _ask_json(
            f"Write {n} short, varied daily check-in questions for an astronaut about mood, "
            f"stress and sleep. Reply with a JSON list of {n} strings only.",
            None, check)
    except Exception:
        return DEFAULT_QUESTIONS[:n]


def score_mood(questions, answers):
    """Gemini reads the astronaut's answers. Returns {mood: 1-5, summary} or {"error": "..."}."""
    def check(data):
        if not (isinstance(data, dict) and data.get("mood") in (1, 2, 3, 4, 5)
                and isinstance(data.get("summary"), str)):
            raise ValueError("Gemini returned JSON in the wrong shape")
        return data
    qa = [{"question": q, "answer": a} for q, a in zip(questions, answers)]
    try:
        return _ask_json(
            json.dumps(qa),
            'You score an astronaut\'s daily mood check-in (hackathon demo, not a diagnosis). '
            'Reply with JSON only: {"mood": <integer 1-5, 1 = very low, 5 = very good>, '
            '"summary": "<one short, kind sentence>"}',
            check)
    except Exception as e:
        return {"error": str(e)}


def memory_words(n=5):
    """Words to show the astronaut for the memory-recall test."""
    return random.sample(WORDS, n)


def memory_score(shown, recalled_text):
    """Percent of the shown words that were recalled (0-100)."""
    recalled = {w for w in re.split(r"[^a-z]+", recalled_text.lower()) if w}
    return round(100 * sum(w in recalled for w in shown) / len(shown))


if __name__ == "__main__":
    print(evaluate(demo_df()))
    print(get_mood_questions())
