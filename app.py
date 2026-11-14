import streamlit as st

from data import load_mission

# Browser tab title + icon, and use the full width of the screen
st.set_page_config(page_title="Astronaut Health Monitor", page_icon="🛰️", layout="wide")

DISCLAIMER = "⚕️ This tool supports, and does not replace, the flight surgeon."


@st.cache_data  # read the database once, then reuse it (keeps the app fast)
def get_mission():
    return load_mission()


mission = get_mission()

# ---------- Title ----------
st.title("🛰️ Astronaut Radiation & Health Monitor")

# ---------- 1. Status card (top) ----------
st.info("STATUS CARD goes here: green / yellow / red  (item 2)")

# ---------- Two tabs ----------
dashboard_tab, check_tab = st.tabs(["📊 Dashboard", "🧠 Daily check"])

with dashboard_tab:
    # ---------- 2. Real-time panel ----------
    st.subheader("Real-time")
    st.write("Dose rate, mission total and heart rate go here  (item 2)")

    st.divider()

    # ---------- 3. Blood panel ----------
    st.subheader("Blood panel (SERS)")
    st.write("CRP, cortisol and glucose charts go here  (item 3)")

with check_tab:
    # ---------- 4. Daily check ----------
    st.subheader("Daily check")
    st.write("Mood and reaction time go here")

# ---------- Bottom of every page ----------
st.caption(f"Mission data loaded: {len(mission)} readings")
st.caption(DISCLAIMER)