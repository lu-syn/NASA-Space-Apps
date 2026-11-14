# CLAUDE.md — NASA Space Apps: Astronaut Radiation & Health Monitor

## Project in one paragraph
A Streamlit dashboard that tells an astronaut three things: whether they are being
exposed to radiation right now, how their body is responding, and what to do.
Three data layers: real-time dose + heart rate; a SERS blood panel (CRP, cortisol,
glucose) every 1-2 days; a daily Gemini mood + cognitive check. We build the
software for real and SIMULATE all hardware data, labeled "simulated" on screen.
Hackathon: ~24 hours, 3 people. Prize tracks: NASA challenge, MLH Best Use of
Gemini API, Cloudflare sponsor prize.

## Team and file ownership (do not edit files you don't own)
| Owner | Branch | Files |
| --- | --- | --- |
| Lu | `data` | `data.py`, `i4_data.py`, `data/`, `worker/` (Cloudflare) |
| Teammate | `ai` | `ai.py`, `rules.py` |
| Teammate | `ui` | `app.py` |

If a change is needed in someone else's file, stop and tell me instead of editing it.

## Shared contracts (other files depend on these; never rename without asking)
```python
load_mission() -> pandas.DataFrame   # all readings, sorted by timestamp
save_reading(row: dict) -> None      # store one reading (SQLite, then Cloudflare)
```
Row format (one row per reading; blood columns empty when there is no draw):
```
timestamp,dose_rate,total_dose,heart_rate,crp,cortisol,glucose,reaction_ms,mood
```
Units: dose_rate µGy/h, total_dose mGy, heart_rate bpm, crp mg/L,
cortisol µg/dL, glucose mg/dL, reaction_ms milliseconds, mood 1-5.

## Build order for Lu (do one step at a time; stop after each for me to test)
1. `data.py`: `generate_mission(seed=42)` builds the 7-day scenario below as a DataFrame.
2. `data.py`: SQLite storage in `mission.db` — create table, `save_reading`, `load_mission`.
   Add a `__main__` block that generates the mission, saves it, and prints a summary.
3. Push, open a PR into `main`, so teammates can use real-looking data.
4. Real NASA data from OSD-575 (Inspiration4 crew blood). HARD LIMIT: 2 hours.
   - Lu downloads the processed CSV files (metabolic panel with glucose; cytokine panel
     with CRP) from the OSD-575 page into `data/raw/` by hand. Do NOT call the OSDR API
     at runtime; the demo must work offline.
   - `i4_data.py`: read those files and write one small clean file
     `data/i4_blood.csv` with columns `crew_id,timepoint,days_from_launch,glucose,crp`
     (add `cortisol` only if it exists in the files; do not invent it).
     First print the raw column names and units so we can map them correctly together.
   - `data.py`: `generate_mission()` sets the glucose and CRP baselines from the crew's
     pre-flight average in `data/i4_blood.csv` (fall back to the defaults below if the
     file is missing).
   - `load_i4_reference() -> DataFrame` returns the clean file so the dashboard can show
     real Inspiration4 values next to the simulated mission.
   - Caveats to keep in comments: 4 crew, draws before and after flight (not during),
     3-day mission, large individual differences.
5. `worker/`: Cloudflare Worker + D1 database `astro-db` with
   `POST /readings` (insert one row) and `GET /readings` (return all rows as JSON).
   Require a shared secret header `X-Sync-Key`; reject requests without it.
6. `data.py`: `sync_to_ground(delay_seconds)` — queue unsent rows and POST them to the
   Worker after a simulated Earth-communication delay. Mark rows as synced in SQLite.
   Cloudflare failures must never crash the app; log and retry later.

## Simulated mission scenario (demo values, not clinical data)
- 7 days, one reading per hour (168 rows). Fixed random seed so the demo is repeatable.
- Dose rate: baseline ~20 µGy/h with small noise. Day 3, 10:00-16:00: solar flare,
  rising to 10-30x baseline, then back to baseline. total_dose is the running sum.
- Heart rate: resting ~65 bpm with noise; +15-25% during and a few hours after the flare.
- Blood draws at 08:00 on days 1, 2, 4, 5, 7 (other rows empty):
  - CRP: baseline ~1 mg/L; ~5-8x baseline about 24 h after the flare, then decays.
  - Cortisol: baseline ~12 µg/dL; ~1.5-2x on days 4-5.
  - Glucose: ~90 mg/dL fasting; mild rise to ~105 on days 4-5.
- Daily check at 09:00 each day: reaction_ms baseline ~300, 20-35% slower on days 4-5;
  mood 4 baseline, dropping to 2 on days 4-5, recovering by day 7.
- Days 1-3 before the flare are the baseline period for alert rules.

## Rules
- Windows + PowerShell. Activate the venv first: `.venv\Scripts\activate`.
- Run the app: `python -m streamlit run app.py`.
- Secrets (GEMINI_API_KEY, WORKER_URL, SYNC_KEY) live in `.env`. Never commit `.env`,
  `mission.db`, `.venv/`, `data/raw/`, or `worker/node_modules/`.
  DO commit the small cleaned file `data/i4_blood.csv`.
- Data sources to cite in comments and the README: NASA OSDR OSD-575 (Inspiration4
  blood, CBC/CMP/cytokines) and OSD-157 (human blood irradiated ex vivo, 0-8 Gy;
  cited as evidence only, not loaded).
- Ask before adding any new dependency. Python deps go in `requirements.txt`.
- Keep code beginner-readable: short functions, comments explaining *why*, and a
  one-line memory hook comment at the top of each main function.
- After each step, explain in plain words what changed and how to test it.
- Small commits with clear messages. Never force-push. Never commit to `main` directly.

## Out of scope
No real sensor or SERS hardware code unless asked. No medical claims: the app
supports, and does not replace, the flight surgeon.
