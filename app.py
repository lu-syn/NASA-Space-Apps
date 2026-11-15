"""
The data is a SIMULATED feed: data.py (Lu) stores a 7-day mission and this file
"plays" it one mission hour at a time, like a live sensor stream. Alert colors
come from rules.py (Liz) and run onboard instantly; Gemini (ai.py) only explains.
Demo controls (jump to the flare, speed, pause) live in the sidebar, out of the
astronaut's way.
"""
from data import ensure_ready; ensure_ready()  # build mission.db if needed + one background sync
import time

import altair as alt
import pandas as pd
import streamlit as st

from data import get_sync_status, load_i4_reference, load_mission
from rules import MISSION_DOSE_BUDGET, get_baseline, recent_dose_spike, signal_statuses, worst

# ai.py talks to Gemini. If it can't be imported, the monitor still works:
# alerts come from rules.py, never from Gemini.
try:
    import ai
    AI_IMPORT_ERROR = None
except Exception as import_error:  # noqa: BLE001 - keep the dashboard alive
    ai = None
    AI_IMPORT_ERROR = str(import_error)


# ===========================================================================
# Settings and text (safe to tweak)
# ===========================================================================

MISSION_NAME = "Deep-Space Transit · Demo Mission"
CREW_MEMBER = "Crew member CM-2"
DISCLAIMER = ("This tool supports, and does not replace, the flight surgeon. "
              "Demo data and demo thresholds, not clinical guidance.")

REFRESH_SECONDS = 2           # how often the screen updates
SPEEDS = {                    # real seconds per mission hour
    "Slow (1 h every 5 s)": 5.0,
    "Normal (1 h every 2 s)": 2.0,
    "Fast (1 h every 0.5 s)": 0.5,
}
DEFAULT_SPEED = "Normal (1 h every 2 s)"
FEED_START = (3, 6)           # (day, hour) the live feed starts at: just before the flare

# "Cabin panel" palette: calm navy hull, three alarm colors from patient monitors.
STATUS_COLOR = {"green": "#3FB68B", "yellow": "#F2B33D", "red": "#EF5A4C"}
STATUS_WORD = {"green": "Nominal", "yellow": "Caution", "red": "Warning"}

NUMBER_COLUMNS = ["dose_rate", "total_dose", "heart_rate", "crp",
                  "cortisol", "glucose", "reaction_ms", "mood"]
# Measured only now and then (blood draw / daily check), so we show the last value.
PERIODIC_COLUMNS = ["crp", "cortisol", "glucose", "reaction_ms", "mood"]

# One entry per tile. "signal" = the key rules.py uses for its color.
# "info" is the plain-language guidance shown on the Body & guidance page.
INDICATORS = {
    "dose_rate": {
        "name": "Radiation dose rate", "icon": "☢️", "column": "dose_rate", "unit": "µGy/h",
        "fmt": "{:.0f}", "source": "Simulated live feed · dosimeter",
        "info": {
            "what": "How much space radiation your body is absorbing right now.",
            "why": "Outside Earth's magnetic field, galactic cosmic rays and solar flares (solar "
                   "particle events) can raise exposure quickly. Radiation is one of NASA's five "
                   "hazards of human spaceflight.",
            "measure": "Personal and area dosimeters update continuously.",
            "act": "Caution at 3× your baseline, warning at 10× (likely solar flare).",
        },
        "actions": {
            "yellow": ["Prepare to move to the shielded storm shelter.",
                       "Postpone any spacewalk or work in lightly shielded areas."],
            "red": ["Go to the storm shelter now and stay until the dose rate is back to baseline.",
                    "Log the time you entered and left the shelter."],
        },
    },
    "mission_dose": {
        "name": "Mission dose total", "icon": "📈", "column": "total_dose", "unit": "mGy",
        "fmt": "{:.2f}", "source": "Simulated live feed · running total",
        "info": {
            "what": "All the radiation you've absorbed since launch.",
            "why": "Long-term exposure raises lifetime cancer risk and may affect the heart and "
                   "brain, so every mission has a dose budget.",
            "measure": "Added up automatically from the dosimeter.",
            "act": f"Caution at 50% of the {MISSION_DOSE_BUDGET:.0f} mGy demo budget, warning at 80%.",
        },
        "actions": {
            "yellow": ["Review the remaining dose budget with the ground team."],
            "red": ["Limit all non-essential exposure; ask the ground team to replan tasks."],
        },
    },
    "heart_rate": {
        "name": "Heart rate (resting)", "icon": "❤️", "column": "heart_rate", "unit": "bpm",
        "fmt": "{:.0f}", "source": "Simulated live feed · wearable",
        "info": {
            "what": "How fast your heart beats at rest.",
            "why": "Altered gravity shifts body fluids and deconditions the heart; stress, poor "
                   "sleep and illness also raise resting heart rate.",
            "measure": "A chest strap or wrist wearable, continuously.",
            "act": "Caution at 15% above your baseline, warning at 30% above.",
        },
        "actions": {
            "yellow": ["Rest for 15 minutes, drink water, then re-measure."],
            "red": ["Stop physical work, sit or lie down, and re-measure in 5 minutes.",
                    "Report chest pain, dizziness or shortness of breath immediately."],
        },
    },
    "crp": {
        "name": "CRP (inflammation)", "icon": "🩸", "column": "crp", "unit": "mg/L",
        "fmt": "{:.2f}", "source": "SIMULATED · SERS blood panel",
        "info": {
            "what": "C-reactive protein, a blood marker of inflammation.",
            "why": "Radiation and spaceflight stress can change the immune system. A rise within "
                   "48 h of a dose spike is likely radiation-related; otherwise it may be an "
                   "infection or strain.",
            "measure": "A drop of blood on the SERS sensor every 1 to 2 days (simulated here).",
            "act": "Caution at 2× your baseline, warning at 5×.",
        },
        "actions": {
            "yellow": ["Repeat the blood panel at the next scheduled draw.",
                       "Check your temperature and note any symptoms."],
            "red": ["Repeat the blood panel within 24 hours.",
                    "Check for fever, wounds or other signs of infection."],
        },
    },
    "cortisol": {
        "name": "Cortisol (stress)", "icon": "🧪", "column": "cortisol", "unit": "µg/dL",
        "fmt": "{:.1f}", "source": "SIMULATED · SERS blood panel",
        "info": {
            "what": "A stress hormone.",
            "why": "Isolation, confinement, workload and disrupted sleep keep cortisol high, which "
                   "can weaken immunity and affect mood.",
            "measure": "SERS blood panel every 1 to 2 days (simulated here).",
            "act": "Caution when 1.5× your baseline on 2 draws in a row, warning at 2×.",
        },
        "actions": {
            "yellow": ["Protect your sleep period tonight and take a decompression break."],
            "red": ["Ask the ground team to lighten your schedule.",
                    "Book a private conference with the behavioral health team."],
        },
    },
    "glucose": {
        "name": "Glucose (fasting)", "icon": "🍬", "column": "glucose", "unit": "mg/dL",
        "fmt": "{:.0f}", "source": "SIMULATED · SERS blood panel",
        "info": {
            "what": "Blood sugar before breakfast.",
            "why": "Stress hormones, less exercise and changes in diet in space can push blood "
                   "sugar up.",
            "measure": "SERS blood panel, fasting, every 1 to 2 days (simulated here).",
            "act": "Caution above 100 mg/dL, warning above 126 mg/dL.",
        },
        "actions": {
            "yellow": ["Re-test fasting glucose at the next draw.",
                       "Keep up your daily exercise session and regular meals."],
            "red": ["Re-test tomorrow morning before eating.",
                    "Review your meals with the ground nutrition team."],
        },
    },
    "reaction": {
        "name": "Reaction time", "icon": "⚡", "column": "reaction_ms", "unit": "ms",
        "fmt": "{:.0f}", "source": "Daily check · 09:00",
        "info": {
            "what": "How quickly you respond on the daily cognitive test.",
            "why": "Fatigue, poor sleep, stress and radiation can slow thinking, which matters for "
                   "critical tasks like docking or spacewalks.",
            "measure": "A short test on the daily check-in.",
            "act": "Caution at 15% slower than your baseline, warning at 30% slower.",
        },
        "actions": {
            "yellow": ["Take a break and re-test later today."],
            "red": ["Avoid critical tasks (docking, spacewalk, robotics) until you re-test normal."],
        },
    },
    "mood": {
        "name": "Mood", "icon": "🙂", "column": "mood", "unit": "/ 5",
        "fmt": "{:.0f}", "source": "Daily check · 09:00",
        "info": {
            "what": "How you rate your mood each day (1 = very low, 5 = very good).",
            "why": "Isolation, confinement and distance from Earth are NASA hazards for behavioral "
                   "health; a low mood that lasts several days is worth acting on.",
            "measure": "Daily check-in questions, scored with Gemini.",
            "act": "Caution after 3 days at 2 or lower, warning after 5 days.",
        },
        "actions": {
            "yellow": ["Schedule time with family or a crewmate today."],
            "red": ["Book a private conference with the behavioral health team."],
        },
    },
}

# Body map groups (clickable on the Body & guidance page).
BODY_SYSTEMS = {
    "Whole body: radiation": ["dose_rate", "mission_dose"],
    "Heart & circulation": ["heart_rate"],
    "Immune & metabolism": ["crp", "glucose"],
    "Brain & behavior": ["reaction", "mood", "cortisol"],
}

SOURCES = ("Sources: [NASA HRP: 5 Hazards of Human Spaceflight](https://www.nasa.gov/hrp/hazards/) · "
           "[NASA HRP: Risks](https://www.nasa.gov/hrp/risks/) · "
           "[CSA: Monitoring radiation for astronaut health](https://www.asc-csa.gc.ca/eng/news/articles/"
           "2026/2026-02-26-monitoring-radiation-astronaut-health.asp)")


st.set_page_config(page_title="Astronaut Health Monitor", page_icon="🛰️", layout="wide")

# Look and feel: a spacecraft cabin panel crossed with a patient monitor.
# Dark navy (low glare in a dim cabin), Barlow type (aerospace placard style),
# calm when nominal, loud only when something needs attention.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600;700&display=swap');
:root {--hull:#0E1A2B; --panel:#15263C; --edge:#24405F; --ink:#E8EEF6; --dim:#93A6BF;
       --ok:#3FB68B; --warn:#F2B33D; --alarm:#EF5A4C; --cabin:#7FB7FF;}
.stApp {background:var(--hull);}
.stApp, .stApp p, .stApp li, .stApp label, .stApp button, .stApp input, .stApp textarea {
    font-family:'Barlow','Segoe UI',sans-serif;}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {font-family:'Barlow Semi Condensed','Barlow',sans-serif;
    font-weight:600;}
.block-container {padding-top:3.5rem; max-width:1500px;}

/* Page buttons */
.st-key-nav button {border-radius:10px; min-height:44px;}
.st-key-nav button p {font-size:15px; font-weight:600;}

/* Mission header: name, the mission clock (hero), feed + ground link */
.mhead {background:var(--panel); border:1px solid var(--edge); border-radius:14px;
        padding:14px 20px 10px; color:var(--ink); margin-top:4px;}
.mtop {display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap;}
.mname {font-size:19px; font-weight:600; line-height:1.3;}
.mname small {display:block; font-size:14px; font-weight:400; color:var(--dim);}
.met {text-align:center;}
.met .lbl {display:block; font-size:13px; color:var(--dim);}
.met .val {font-family:'Barlow Semi Condensed',sans-serif; font-size:36px; font-weight:600;
           line-height:1; font-variant-numeric:tabular-nums; letter-spacing:.5px;}
.met .day {display:block; font-size:14px; color:var(--dim); margin-top:2px;}
.mstate {text-align:right; font-size:14px; color:var(--dim); line-height:1.6;}
.live {color:var(--alarm); font-weight:600;}
.live:before {content:"\\25CF  ";}
.paused {color:var(--dim); font-weight:600;}

/* Mission ribbon: one bar per mission hour, colored by that hour's status */
.ribbon {position:relative; margin-top:14px;}
.ribbon svg {width:100%; height:14px; display:block;}
.ribbon .now {position:absolute; top:-5px; width:3px; height:24px; background:var(--ink);
              border-radius:2px; transform:translateX(-50%);}
.ribbon .draw {position:absolute; top:19px; width:7px; height:7px; border:1px solid var(--dim);
               transform:translateX(-50%) rotate(45deg);}
.ribbon .draw.done {background:var(--ink); border-color:var(--ink);}
.ribbon .days {display:flex; margin-top:16px; font-size:12px; color:var(--dim);}
.ribbon .days span {flex:1;}
.ribbon .key {font-size:12px; color:var(--dim); text-align:right; margin-top:2px;}

/* Status banner: quiet when nominal, filled amber or red when not */
.banner {display:flex; gap:6px 18px; align-items:baseline; flex-wrap:wrap; border-radius:14px;
         padding:14px 22px; margin:14px 0;}
.banner .word {font-family:'Barlow Semi Condensed',sans-serif; font-size:32px; font-weight:700; line-height:1;}
.banner .head {font-size:19px; font-weight:600;}
.banner .small {flex-basis:100%; font-size:15px;}
.banner-green {background:var(--panel); border:1px solid var(--edge); border-left:6px solid var(--ok); color:var(--ink);}
.banner-green .word {color:var(--ok);}
.banner-yellow {background:var(--warn); color:#241A02;}
.banner-red {background:var(--alarm); color:#FFFFFF; animation:alarm 2.4s ease-in-out infinite;}
@keyframes alarm {0%, 100% {box-shadow:0 0 0 0 rgba(239,90,76,0);}
                  50% {box-shadow:0 0 0 7px rgba(239,90,76,.35);}}
@media (prefers-reduced-motion: reduce) {.banner-red {animation:none;}}

/* Vital-sign tiles (one per channel, like a patient monitor) */
.tile {background:var(--panel); border:1px solid var(--edge); border-left:4px solid; border-radius:12px;
       padding:12px 14px; margin-bottom:14px; color:var(--ink); min-height:160px;}
.tile.s-yellow {border-color:rgba(242,179,61,.6);}
.tile.s-red {border-color:rgba(239,90,76,.75); box-shadow:0 0 0 1px rgba(239,90,76,.35) inset;}
.tile .lbl {font-size:14px; font-weight:500; color:var(--dim); display:flex; justify-content:space-between;
            align-items:center; gap:6px;}
.tile .pill {font-size:12px; font-weight:600; padding:1px 10px; border-radius:999px; color:#0E1A2B;}
.tile .val {font-family:'Barlow Semi Condensed',sans-serif; font-size:40px; font-weight:600; line-height:1.1;
            margin-top:6px; font-variant-numeric:tabular-nums; color:var(--ink);}
.tile .unit {font-family:'Barlow',sans-serif; font-size:15px; font-weight:400; color:var(--dim); margin-left:3px;}
.tile .sub {font-size:14px;}
.tile .foot {font-size:12px; color:var(--dim); margin-top:4px;}

/* Side panels */
.panel {background:var(--panel); border:1px solid var(--edge); border-radius:12px; padding:14px 16px;
        margin-bottom:14px; color:var(--ink); font-size:14px;}
.panel h4 {margin:0 0 8px 0; padding:0; font-size:17px; font-weight:600; color:var(--ink);}
.ev {border-left:3px solid; padding:3px 10px; margin:6px 0; font-size:14px;}

/* ---------- Phones (screens 640px wide or less) ---------- */
@media (max-width: 640px) {
  .block-container {padding:3.5rem 0.75rem 1rem 0.75rem;}
  .mhead {padding:12px 14px 8px;}
  .mtop {flex-direction:column; align-items:flex-start; gap:8px;}
  .met {text-align:left;}
  .met .val {font-size:30px;}
  .mstate {text-align:left;}
  .ribbon .key {text-align:left;}
  .banner {padding:12px 14px;}
  .banner .word {font-size:24px;}
  .banner .head {font-size:16px;}
  .banner .small {font-size:13px;}
  /* Tiles: compact, 2 per row instead of 1 long column */
  .tile {min-height:0; padding:10px; margin-bottom:8px;}
  .tile .lbl {font-size:12px; flex-wrap:wrap; gap:4px;}
  .tile .val {font-size:28px;}
  .tile .sub {font-size:12px;}
  .st-key-tiles [data-testid="stHorizontalBlock"] {flex-wrap:wrap !important; gap:0.5rem !important;}
  .st-key-tiles [data-testid="stColumn"], .st-key-tiles [data-testid="column"] {
      flex:1 1 calc(50% - 0.5rem) !important; min-width:calc(50% - 0.5rem) !important;
      width:calc(50% - 0.5rem) !important;}
  /* Page buttons: stay side by side in one row */
  .st-key-nav [data-testid="stHorizontalBlock"] {flex-wrap:nowrap !important; gap:0.4rem !important;}
  .st-key-nav [data-testid="stColumn"], .st-key-nav [data-testid="column"] {
      flex:1 1 0 !important; min-width:0 !important; width:auto !important;}
  .st-key-nav button {padding:0.3rem 0.2rem !important;}
  .st-key-nav button p {font-size:12px !important;}
  /* Main area: show "Do this now" ABOVE the charts on a phone */
  .st-key-main [data-testid="stHorizontalBlock"] {flex-direction:column !important;}
  .st-key-main [data-testid="stColumn"]:nth-child(2),
  .st-key-main [data-testid="column"]:nth-child(2) {order:-1;}
}
</style>
""", unsafe_allow_html=True)


# ===========================================================================
# Data and status (cached: computed once, reused on every refresh)
# ===========================================================================

@st.cache_data
def get_mission():
    # Hook: read mission.db once; plain floats so charts handle empty cells.
    df = load_mission()
    df[NUMBER_COLUMNS] = df[NUMBER_COLUMNS].astype("float64")
    return df


def evaluate_now(history):
    # Hook: status of every signal at the last row of `history`, using rules.py.
    # Blood and check-in values arrive only now and then, so we judge the LAST
    # measured value (a high CRP stays flagged until the next draw), not just
    # the current hour, which is usually empty.
    baseline = get_baseline(history)
    row = history.iloc[-1].copy()
    for column in ["crp", "glucose", "reaction_ms"]:
        measured = history[column].dropna()
        row[column] = measured.iloc[-1] if not measured.empty else float("nan")
    signals = signal_statuses(row, baseline, history)
    return {"status": worst(*signals.values()), "signals": signals, "baseline": baseline}


@st.cache_data
def status_timeline(mission):
    # Hook: the status at every hour of the mission, worked out once.
    return [evaluate_now(mission.iloc[: i + 1]) for i in range(len(mission))]


def alert_events(mission, timeline, now_index):
    # Hook: every time a signal changed color, newest first (the alert log).
    events = []
    for i in range(1, now_index + 1):
        before, after = timeline[i - 1]["signals"], timeline[i]["signals"]
        for key, new in after.items():
            if new != before.get(key):
                events.append({"time": mission["timestamp"].iloc[i], "key": key,
                               "old": before.get(key), "new": new})
    return events[::-1]


def find_dose_spikes(df, baseline_dose):
    # Hook: time windows where dose was 3x baseline or more (shaded on charts).
    high = df["dose_rate"] >= 3 * baseline_dose
    group_id = (high != high.shift()).cumsum()
    spikes = [{"start": block["timestamp"].min(),
               "end": block["timestamp"].max() + pd.Timedelta(hours=1)}
              for _, block in df[high].groupby(group_id[high])]
    return pd.DataFrame(spikes, columns=["start", "end"])


@st.cache_data
def get_i4_reference():
    # Hook: real Inspiration4 crew blood (NASA OSDR OSD-575), read once.
    # Empty table if Lu's data/i4_blood.csv is missing; the app then skips it.
    return load_i4_reference()


def i4_crp_note():
    # Hook: one line on the CRP tile about what the REAL crew showed right
    # after landing (R+1), worked out from the file so it stays honest.
    ref = get_i4_reference()
    if ref.empty or "crp_fold_change" not in ref:
        return ""
    after = ref.loc[ref["timepoint"] == "R+1", "crp_fold_change"].dropna()
    if after.empty:
        return ""
    return (f"Real Inspiration4 crew, day after landing: {after.min():.1f}–{after.max():.1f}× "
            f"pre-flight CRP (NASA OSDR OSD-575)")


def i4_crp_chart():
    # Hook: REAL data chart: each crew member's CRP vs their own pre-flight
    # value (1.0 = pre-flight), before and after the 3-day flight.
    ref = get_i4_reference().dropna(subset=["crp_fold_change"])
    flight = pd.DataFrame({"start": [0], "end": [3]})  # Inspiration4 flew 3 days
    band = alt.Chart(flight).mark_rect(color="#7FB7FF", opacity=0.15).encode(x="start:Q", x2="end:Q")
    one = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(strokeDash=[4, 4], color="#93A6BF").encode(y="y:Q")
    lines = alt.Chart(ref).mark_line(point=True).encode(
        x=alt.X("days_from_launch:Q", title="Days from launch (flight = shaded)"),
        y=alt.Y("crp_fold_change:Q", title="CRP × pre-flight"),
        color=alt.Color("crew_id:N", title="Crew member"),
        tooltip=[alt.Tooltip("crew_id:N", title="Crew"), alt.Tooltip("timepoint:N", title="Timepoint"),
                 alt.Tooltip("crp_fold_change:Q", title="× pre-flight")],
    )
    return (band + one + lines).properties(
        title="REAL DATA · Inspiration4 crew CRP vs pre-flight (NASA OSDR OSD-575)", height=260)


def latest(df, column):
    # Hook: the most recent measured value and when it was measured (or None, None).
    measured = df[["timestamp", column]].dropna()
    if measured.empty:
        return None, None
    last = measured.iloc[-1]
    return last[column], last["timestamp"]


# ===========================================================================
# Live clock: which mission hour the "live feed" has reached
# ===========================================================================

mission = get_mission()
if mission.empty:
    st.error("No mission data found. In the terminal, run:  python data.py")
    st.stop()

START = mission["timestamp"].min()
LAST = len(mission) - 1


def index_of(day, hour):
    # Hook: (day 3, 13:00) -> row number in the mission table.
    return min((day - 1) * 24 + hour, LAST)


# The feed position = where we anchored it + time passed since then.
st.session_state.setdefault("anchor_index", index_of(*FEED_START))
st.session_state.setdefault("anchor_time", time.time())
st.session_state.setdefault("paused", False)
st.session_state.setdefault("speed", DEFAULT_SPEED)
st.session_state.setdefault("ai_result", None)


def current_index():
    # Hook: how far the live feed has got right now.
    if st.session_state.paused:
        return st.session_state.anchor_index
    hours_passed = (time.time() - st.session_state.anchor_time) / SPEEDS[st.session_state.speed]
    return min(st.session_state.anchor_index + int(hours_passed), LAST)


def set_feed(index):
    # Hook: restart the feed from a given mission hour.
    st.session_state.anchor_index = max(0, min(index, LAST))
    st.session_state.anchor_time = time.time()


def toggle_pause():
    set_feed(current_index())
    st.session_state.paused = not st.session_state.paused


def change_speed():
    # Re-anchor so changing speed doesn't make the feed jump.
    new_speed = st.session_state.speed_choice
    set_feed(current_index())
    st.session_state.speed = new_speed


def mission_clock(ts):
    # Hook: timestamp -> ("Day 3 · 13:00", "MET 02d 13h 00m").
    elapsed = ts - START
    day = elapsed.days + 1
    hours, minutes = divmod(elapsed.seconds // 60, 60)
    return f"Day {day} · {ts:%H:%M}", f"MET {elapsed.days:02d}d {hours:02d}h {minutes:02d}m"


# Sidebar: demo controls (not part of the astronaut's view).
with st.sidebar:
    st.header("🎛️ Demo controls")
    st.caption("For presenting only. The feed is a simulated replay of data.py's 7-day mission.")
    st.button("▶ Resume feed" if st.session_state.paused else "⏸ Pause feed",
              on_click=toggle_pause, width="stretch")
    st.selectbox("Feed speed", list(SPEEDS), index=list(SPEEDS).index(st.session_state.speed),
                 key="speed_choice", on_change=change_speed)
    st.markdown("**Jump to**")
    jumps = {
        "Mission start": index_of(1, 0),
        "Just before the solar flare": index_of(3, 9),
        "Solar flare peak": int(mission["dose_rate"].idxmax()),
        "Morning after (blood panel)": index_of(4, 8),
        "Recovery": index_of(7, 9),
    }
    for label, target in jumps.items():
        st.button(label, on_click=set_feed, args=(target,), width="stretch")


# ===========================================================================
# Small display pieces
# ===========================================================================

def sparkline(values, color):
    # Hook: a tiny line drawing of the recent values (pure SVG, no chart library).
    values = [v for v in values if pd.notna(v)]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = 100 / (len(values) - 1)
    points = " ".join(f"{i * step:.1f},{22 - (v - low) / span * 20:.1f}" for i, v in enumerate(values))
    return (f'<svg viewBox="0 0 100 24" preserveAspectRatio="none" style="width:100%;height:26px">'
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.6" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def hours_ago(then, now):
    hours = int((now - then).total_seconds() // 3600)
    return "just now" if hours == 0 else f"{hours} h ago"


def describe(key, now_df, baseline):
    # Hook: (big value, comparison line, footer, recent values) for one indicator.
    ind = INDICATORS[key]
    column = ind["column"]
    now = now_df["timestamp"].iloc[-1]
    value, measured_at = latest(now_df, column)
    if value is None:
        return "—", "No measurement yet", ind["source"], []

    if key == "dose_rate":
        sub = f"{value / baseline['dose_rate']:.1f}× baseline ({baseline['dose_rate']:.0f})"
    elif key == "mission_dose":
        sub = f"{100 * value / MISSION_DOSE_BUDGET:.1f}% of {MISSION_DOSE_BUDGET:.0f} mGy budget"
    elif key == "heart_rate":
        sub = f"{100 * (value / baseline['heart_rate'] - 1):+.0f}% vs baseline ({baseline['heart_rate']:.0f})"
    elif key in ("crp", "cortisol") and pd.notna(baseline[column]):
        sub = f"{value / baseline[column]:.1f}× baseline ({baseline[column]:g})"
    elif key == "glucose":
        sub = "Above the 100 mg/dL target" if value > 100 else "Target: 100 or lower"
    elif key == "reaction" and pd.notna(baseline["reaction_ms"]):
        sub = f"{100 * (value / baseline['reaction_ms'] - 1):+.0f}% vs baseline ({baseline['reaction_ms']:.0f})"
    elif key == "mood":
        sub = "1 = very low · 5 = very good"
    else:
        sub = "Baseline being set (days 1-3)"

    recent = now_df[column].tail(48) if column in ("dose_rate", "total_dose", "heart_rate") \
        else now_df[column].dropna()
    footer = f"{ind['source']} · {hours_ago(measured_at, now)}"
    return ind["fmt"].format(value), sub, footer, list(recent)


def tile(key, status, now_df, baseline):
    # Hook: one vital-sign card: name, color pill, big number, comparison, sparkline.
    ind = INDICATORS[key]
    value, sub, footer, recent = describe(key, now_df, baseline)
    color = STATUS_COLOR[status]
    st.markdown(f"""
    <div class="tile s-{status}" style="border-left-color:{color}">
      <div class="lbl"><span>{ind['icon']} {ind['name']}</span>
        <span class="pill" style="background:{color}">{STATUS_WORD[status]}</span></div>
      <div class="val">{value} <span class="unit">{ind['unit']}</span></div>
      <div class="sub">{sub}</div>
      {sparkline(recent, color)}
      {f'<div class="foot">🧬 {i4_crp_note()}</div>' if key == "crp" and i4_crp_note() else ""}
      <div class="foot">{footer}</div>
    </div>""", unsafe_allow_html=True)


def sync_label():
    # Hook: "Synced to mission control ✓ 168/168 · last sync 21:05" from Lu's
    # get_sync_status(). Never breaks the header if the database can't be read.
    try:
        sync = get_sync_status()
    except Exception:  # noqa: BLE001 - a status line must never crash the app
        return "📡 Sync status unavailable"
    if not sync["last_sync"]:
        return "📡 Not synced yet"
    return (f"📡 Synced to mission control ✓ {sync['synced']}/{sync['total']} "
            f"· last sync {sync['last_sync']}")


def mission_ribbon(now_index):
    # Hook: the whole mission as one strip, one thin bar per hour, colored by
    # that hour's status. Hours not reached yet stay dim. White line = now,
    # diamonds = blood draws (filled once done).
    timeline = status_timeline(mission)
    total = len(mission)
    bars = "".join(
        f'<rect x="{i}" y="0" width="0.82" height="10" '
        f'fill="{STATUS_COLOR[timeline[i]["status"]] if i <= now_index else "#24405F"}"/>'
        for i in range(total))
    draws = "".join(
        f'<span class="draw{" done" if i <= now_index else ""}" style="left:{100 * (i + 0.4) / total:.2f}%" '
        f'title="SERS blood draw"></span>'
        for i in mission.index[mission["crp"].notna()])
    days = "".join(f"<span>Day {d}</span>" for d in range(1, total // 24 + 1))
    return f"""
      <div class="ribbon" role="img" aria-label="Mission timeline, one bar per hour colored by status">
        <svg viewBox="0 0 {total} 10" preserveAspectRatio="none">{bars}</svg>
        <span class="now" style="left:{100 * (now_index + 1) / total:.2f}%"></span>
        {draws}
        <div class="days">{days}</div>
        <div class="key">Each bar is one mission hour, colored by status. Diamonds are blood draws.</div>
      </div>"""


def mission_bar(now_ts):
    # Hook: mission name, the mission clock (MET), feed state, ground link,
    # and the mission ribbon underneath.
    day_label, met = mission_clock(now_ts)
    now_index = int((now_ts - START) / pd.Timedelta(hours=1))
    feed = ('<span class="paused">Feed paused</span>' if st.session_state.paused
            else '<span class="live">SIMULATED LIVE</span>')
    st.markdown(f"""
    <div class="mhead">
      <div class="mtop">
        <div class="mname">🛰️ {MISSION_NAME}<small>👩‍🚀 {CREW_MEMBER}, on board the spacecraft</small></div>
        <div class="met"><span class="lbl">Mission elapsed time</span>
          <span class="val">{met.removeprefix("MET ")}</span><span class="day">{day_label}</span></div>
        <div class="mstate">{feed}<br>{sync_label()}</div>
      </div>
      {mission_ribbon(now_index)}
    </div>""", unsafe_allow_html=True)


def status_banner(status, signals, now_df, baseline):
    # Hook: the overall status line. Worst signal decides the color.
    flagged = sorted((k for k, s in signals.items() if s != "green"),
                     key=lambda k: signals[k] != "red")  # reds first
    if flagged:
        details = " · ".join(f"{INDICATORS[k]['name']}: {describe(k, now_df, baseline)[1]}" for k in flagged[:3])
    else:
        details = "All indicators within your normal range."
    headline = {"green": "All systems nominal.",
                "yellow": "Keep an eye on the flagged indicators.",
                "red": "Act now and contact the flight surgeon."}[status]
    st.markdown(f"""
    <div class="banner banner-{status}" role="status">
      <div class="word">{STATUS_WORD[status]}</div>
      <div class="head">{headline}</div>
      <div class="small">{details}</div>
    </div>""", unsafe_allow_html=True)


def actions_for(signals, now_df, baseline):
    # Hook: the "do this now" list, most urgent first, from the guidance table.
    actions = []
    for key in sorted(signals, key=lambda k: signals[k] != "red"):
        status = signals[key]
        if status == "green":
            continue
        for text in INDICATORS[key]["actions"][status]:
            actions.append((status, f"{INDICATORS[key]['icon']} {text}"))
        if key == "crp":  # the plan's rule: blame radiation only after a recent dose spike
            if recent_dose_spike(now_df, baseline):
                actions.append((status, "🩸 CRP rose within 48 h of a dose spike: likely radiation-related."))
            else:
                actions.append((status, "🩸 No dose spike in the last 48 h: possible infection or strain."))
    if any(s == "red" for s in signals.values()):
        actions.insert(0, ("red", "📞 Contact the flight surgeon (ground) now. Expect a signal delay."))
    return actions


def upcoming_tasks(now_index):
    # Hook: next scheduled blood draw and daily check-in, from the mission schedule.
    tasks = []
    for column, label in [("crp", "🩸 SERS blood panel"), ("mood", "📝 Daily check-in")]:
        future = mission.iloc[now_index:][mission[column].iloc[now_index:].notna()]
        if future.empty:
            tasks.append((label, "none scheduled"))
            continue
        due = future["timestamp"].iloc[0]
        hours = int((due - mission["timestamp"].iloc[now_index]).total_seconds() // 3600)
        when = "**due now**" if hours == 0 else f"in {hours} h ({mission_clock(due)[0]})"
        tasks.append((label, when))
    return tasks


def trend_chart(df, column, title, unit, spikes, window_hours, points=False):
    # Hook: a scrolling chart of the last `window_hours`, flare periods shaded red.
    now = df["timestamp"].iloc[-1]
    start = max(START, now - pd.Timedelta(hours=window_hours))
    domain = [start.isoformat(), (now + pd.Timedelta(hours=1)).isoformat()]
    data = df[df["timestamp"] >= start][["timestamp", column]].dropna()
    x = alt.X("timestamp:T", title=None, scale=alt.Scale(domain=domain),
              axis=alt.Axis(format="%d %b %H:%M", labelAngle=0, tickCount=4))
    line = alt.Chart(data).mark_line(point=points, color="#7FB7FF").encode(
        x=x, y=alt.Y(f"{column}:Q", title=unit, scale=alt.Scale(zero=False), axis=alt.Axis(format="~g")),
        tooltip=[alt.Tooltip("timestamp:T", title="Time", format="%d %b %H:%M"),
                 alt.Tooltip(f"{column}:Q", title=title)])
    shown = spikes[spikes["end"] >= start] if not spikes.empty else spikes
    if not shown.empty:
        band = alt.Chart(shown).mark_rect(color="#EF5A4C", opacity=0.22).encode(x="start:T", x2="end:T")
        line = band + line
    return line.properties(title=title, height=200)


def body_map_svg(system_status, selected):
    # Hook: a simple human figure; each body system is colored by its worst status.
    c = {name: STATUS_COLOR[s] for name, s in system_status.items()}
    def ring(name):  # thicker white outline on the selected system
        return 'stroke="#E8EEF6" stroke-width="3"' if name == selected else 'stroke="#0E1A2B" stroke-width="1"'
    rad, heart = "Whole body: radiation", "Heart & circulation"
    imm, brain = "Immune & metabolism", "Brain & behavior"
    return f"""
    <svg viewBox="0 0 200 330" style="width:100%;max-width:260px;display:block;margin:auto">
      <g fill="#15263C" stroke="{c[rad]}" stroke-width="{4 if selected == rad else 2.5}">
        <circle cx="100" cy="40" r="26"/>
        <rect x="62" y="72" width="76" height="110" rx="20"/>
        <rect x="34" y="78" width="22" height="100" rx="11"/>
        <rect x="144" y="78" width="22" height="100" rx="11"/>
        <rect x="68" y="186" width="26" height="120" rx="12"/>
        <rect x="106" y="186" width="26" height="120" rx="12"/>
      </g>
      <circle cx="100" cy="38" r="14" fill="{c[brain]}" {ring(brain)}/>
      <path d="M113 104 c0-8 12-8 12 0 c0 8-12 14-12 18 c0-4-12-10-12-18 c0-8 12-8 12 0z"
            fill="{c[heart]}" {ring(heart)}/>
      <ellipse cx="100" cy="150" rx="24" ry="16" fill="{c[imm]}" {ring(imm)}/>
    </svg>"""


def ai_panel(now_df, now_ts):
    # Hook: Gemini explains the current situation, on request (slow, needs internet).
    st.markdown("**🤖 AI assessment (Gemini)**")
    if ai is None:
        st.caption(f"Unavailable ({AI_IMPORT_ERROR}). Onboard alerts above still work.")
        return
    if st.button("Analyze current status", width="stretch"):
        with st.spinner("Asking Gemini..."):
            st.session_state.ai_result = {"at": now_ts, "result": ai.evaluate(now_df)}
    saved = st.session_state.ai_result
    if saved is None:
        st.caption("Gemini explains the alerts and suggests next steps. Alerts never wait for it.")
        return
    result = saved["result"]
    st.caption(f"Assessment from {mission_clock(saved['at'])[1]} ({hours_ago(saved['at'], now_ts)})")
    if "error" in result:
        st.error(f"Gemini could not answer: {result['error']}")  # never a made-up status
        return
    st.markdown(f"Status: **{STATUS_WORD[result['status']]}**")
    for reason in result["reasons"]:
        st.markdown(f"- {reason}")
    st.markdown("**Suggested actions**")
    for action in result["actions"]:
        st.markdown(f"- {action}")


def explain_panel(now_df, now_ts, signals):
    # Hook: on click, Gemini explains the CURRENT rule colors in plain words.
    # Kept in session_state so the 2-second refresh doesn't wipe it.
    if st.button("Explain with Gemini", key="explain_btn", width="stretch"):
        flags = {k: s for k, s in signals.items() if s != "green"}
        with st.spinner("Asking Gemini..."):
            result = ai.explain_status(now_df.iloc[-1], flags, now_df) if ai else None
        st.session_state.explanation = {"at": now_ts, "result": result}
    saved = st.session_state.get("explanation")
    if saved is None:
        return
    with st.container(border=True):
        st.markdown(f"**Gemini explanation** · {mission_clock(saved['at'])[0]}")
        result = saved["result"]
        if result is None:
            st.warning("Gemini unavailable; the rules above still apply.")
            return
        st.markdown(result["summary"])
        st.caption(f"Why: {result['why']}")
        for step in result["actions"]:
            st.markdown(f"- {step}")


# ===========================================================================
# Pages
# ===========================================================================

PAGES = ["🖥️ Live monitor", "🧍 Body & guidance", "📝 Daily check-in"]
st.session_state.setdefault("page", PAGES[0])


def go_to_page(name):
    st.session_state.page = name


# Page menu: three big buttons. The page you're on is filled in (primary).
nav = st.container(key="nav")  # named so phone styles can keep it in one row
for column, name in zip(nav.columns(len(PAGES)), PAGES):
    column.button(name, on_click=go_to_page, args=(name,), width="stretch",
                  type="primary" if st.session_state.page == name else "secondary")
page = st.session_state.page


@st.fragment(run_every=REFRESH_SECONDS)
def live_monitor():
    # Hook: the main screen. Redraws itself every few seconds with the newest data.
    now_index = current_index()
    now_df = mission.iloc[: now_index + 1]
    now_ts = now_df["timestamp"].iloc[-1]
    current = status_timeline(mission)[now_index]
    signals, baseline = current["signals"], current["baseline"]
    spikes = find_dose_spikes(now_df, baseline["dose_rate"])

    mission_bar(now_ts)
    status_banner(current["status"], signals, now_df, baseline)

    tile_keys = list(INDICATORS)
    tiles = st.container(key="tiles")  # named so phone styles can show 2 tiles per row
    for row_keys in (tile_keys[:4], tile_keys[4:]):
        for col, key in zip(tiles.columns(4), row_keys):
            with col:
                tile(key, signals[key], now_df, baseline)

    main = st.container(key="main")  # named so phones show "Do this now" first
    left, right = main.columns([2, 1])
    with left:
        window = st.radio("Trend window", ["Last 24 h", "Last 72 h", "Whole mission"],
                          index=1, horizontal=True, key="window")
        window_hours = {"Last 24 h": 24, "Last 72 h": 72, "Whole mission": 24 * 7}[window]
        live_tab, blood_tab, check_tab = st.tabs(
            ["Radiation & heart", "Blood panel (simulated)", "Cognition & mood"])
        with live_tab:
            a, b = st.columns(2)
            a.altair_chart(trend_chart(now_df, "dose_rate", "Dose rate", "µGy/h", spikes, window_hours),
                           width="stretch")
            b.altair_chart(trend_chart(now_df, "heart_rate", "Heart rate", "bpm", spikes, window_hours),
                           width="stretch")
        with blood_tab:
            st.caption("🧪 SIMULATED SERS blood panel values (stand-in for the onboard sensor).")
            if not get_i4_reference().empty:
                st.altair_chart(i4_crp_chart(), width="stretch")
                st.caption("🧬 REAL data from 4 Inspiration4 crew (3-day flight, Sept 2021): blood was drawn "
                           "before and after flight, never during. 1.0 = that person's own pre-flight level "
                           "(3 days before launch). Source: NASA OSDR OSD-575.")
            for col, (column, title, unit) in zip(st.columns(3), [
                    ("crp", "CRP (simulated)", "mg/L"),
                    ("cortisol", "Cortisol (simulated)", "µg/dL"),
                    ("glucose", "Glucose (simulated)", "mg/dL")]):
                col.altair_chart(trend_chart(now_df, column, title, unit, spikes, window_hours, points=True),
                                 width="stretch")
        with check_tab:
            a, b = st.columns(2)
            a.altair_chart(trend_chart(now_df, "reaction_ms", "Reaction time", "ms", spikes,
                                       window_hours, points=True), width="stretch")
            b.altair_chart(trend_chart(now_df, "mood", "Mood (1-5)", "score", spikes,
                                       window_hours, points=True), width="stretch")
        if not spikes.empty:
            st.caption("🟥 Red band = radiation dose spike (3× baseline or more).")

    with right:
        actions = actions_for(signals, now_df, baseline)
        items = "".join(f'<div class="ev" style="border-color:{STATUS_COLOR[s]}">{text}</div>'
                        for s, text in actions) or "No action needed. Keep your normal routine."
        st.markdown(f'<div class="panel"><h4>Do this now</h4>{items}</div>', unsafe_allow_html=True)
        explain_panel(now_df, now_ts, signals)

        tasks = "".join(f"<div>{label}: {when.replace('**', '')}</div>" for label, when in upcoming_tasks(now_index))
        st.markdown(f'<div class="panel"><h4>Upcoming measurements</h4>{tasks}</div>', unsafe_allow_html=True)

        events = alert_events(mission, status_timeline(mission), now_index)[:6]
        log = "".join(
            f'<div class="ev" style="border-color:{STATUS_COLOR[e["new"]]}">'
            f'{mission_clock(e["time"])[0]} · {INDICATORS[e["key"]]["name"]} → {STATUS_WORD[e["new"]]}</div>'
            for e in events) or "No alerts yet this mission."
        st.markdown(f'<div class="panel"><h4>Alert log</h4>{log}</div>', unsafe_allow_html=True)

    st.caption(f"⚕️ {DISCLAIMER}")


@st.fragment(run_every=REFRESH_SECONDS)
def body_and_guidance():
    # Hook: body map colored live + plain-language guidance for each indicator.
    now_index = current_index()
    now_df = mission.iloc[: now_index + 1]
    current = status_timeline(mission)[now_index]
    signals, baseline = current["signals"], current["baseline"]

    mission_bar(now_df["timestamp"].iloc[-1])
    system_status = {name: worst(*(signals[k] for k in keys)) for name, keys in BODY_SYSTEMS.items()}

    left, right = st.columns([1, 2])
    with right:
        selected = st.radio("Body system", list(BODY_SYSTEMS), horizontal=True, key="system",
                            format_func=lambda n: f"{n} ({STATUS_WORD[system_status[n]]})")
    with left:
        st.markdown(body_map_svg(system_status, selected), unsafe_allow_html=True)
        st.caption("Outline = whole body (radiation) · Head = brain & behavior · "
                   "Heart = heart & circulation · Belly = immune & metabolism")
    with right:
        for key in BODY_SYSTEMS[selected]:
            ind, status = INDICATORS[key], signals[key]
            value, sub, footer, _ = describe(key, now_df, baseline)
            with st.container(border=True):
                st.markdown(f"#### {ind['icon']} {ind['name']}: "
                            f":{'green' if status == 'green' else 'orange' if status == 'yellow' else 'red'}"
                            f"[{STATUS_WORD[status]}]")
                st.markdown(f"**Now:** {value} {ind['unit']} · {sub}  \n*{footer}*")
                st.markdown(f"**What it is:** {ind['info']['what']}  \n"
                            f"**Why it changes in space:** {ind['info']['why']}  \n"
                            f"**How it's measured onboard:** {ind['info']['measure']}  \n"
                            f"**When to act:** {ind['info']['act']}")
                if status != "green":
                    st.markdown("**What to do now:**  \n" +
                                "  \n".join(f"• {a}" for a in ind["actions"][status]))
    st.caption(SOURCES)
    st.caption(f"⚕️ {DISCLAIMER}")


def daily_check_in():
    # Hook: today's mood questions (Gemini) and a memory test. No auto-refresh here,
    # so the page doesn't jump while the astronaut is typing.
    mission_bar(mission["timestamp"].iloc[current_index()])
    st.subheader("📝 Daily check-in")
    st.caption("Takes about 2 minutes. Your answers help spot stress, fatigue and low mood early.")
    if ai is None:
        st.warning(f"The check-in needs ai.py, which could not be loaded: {AI_IMPORT_ERROR}")
        return

    mood_col, memory_col = st.columns(2)
    with mood_col, st.container(border=True):
        st.markdown("**1. How are you feeling?**")
        if "questions" not in st.session_state:
            with st.spinner("Preparing today's questions..."):
                st.session_state.questions = ai.get_mood_questions()
        with st.form("mood_form"):
            answers = [st.text_area(q, key=f"answer_{i}", height=70)
                       for i, q in enumerate(st.session_state.questions)]
            submitted = st.form_submit_button("Submit answers", width="stretch")
        if submitted:
            with st.spinner("Gemini is reading your answers..."):
                st.session_state.mood_result = ai.score_mood(st.session_state.questions, answers)
        result = st.session_state.get("mood_result")
        if result and "error" in result:
            st.error(f"Gemini could not score the check-in: {result['error']}")
        elif result:
            st.success(f"Mood score: **{result['mood']} / 5**. {result['summary']}")

    with memory_col, st.container(border=True):
        st.markdown("**2. Memory recall**")
        st.caption("Read the 5 words, hide them, then type as many as you remember.")
        if st.button("Show me 5 words", width="stretch"):
            st.session_state.memory_words = ai.memory_words()
            st.session_state.memory_hidden = False
            st.session_state.pop("memory_score", None)
        words = st.session_state.get("memory_words")
        if words and not st.session_state.get("memory_hidden"):
            st.markdown("### " + "  ·  ".join(words))
            if st.button("I've memorised them: hide", width="stretch"):
                st.session_state.memory_hidden = True
                st.rerun()
        elif words:
            recalled = st.text_input("Type every word you remember")
            if st.button("Check", width="stretch"):
                st.session_state.memory_score = ai.memory_score(words, recalled)
            if "memory_score" in st.session_state:
                st.success(f"You remembered **{st.session_state.memory_score}%** of the words.")
    st.caption(f"⚕️ {DISCLAIMER}")


if page == "🖥️ Live monitor":
    live_monitor()
elif page == "🧍 Body & guidance":
    body_and_guidance()
else:
    daily_check_in()