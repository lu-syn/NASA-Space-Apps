# MissionVitals

**Health answers on board, in minutes.**

A health monitor for astronauts on long missions. It combines radiation dose, blood markers and a daily mood and cognitive check, tells the astronaut what to do right now, syncs to mission control, and alerts the ground team.

**Live demo:** https://nasa-space-apps-missionvitals.streamlit.app/

Built for the NASA Space Apps Challenge (astronaut health monitoring), with the MLH Best Use of Gemini API, Cloudflare and Twilio tracks.

---

## The problem

Long-duration missions expose astronauts to space radiation, isolation and confinement, altered gravity and a closed environment. Astronauts carry much of the responsibility for spotting health changes in themselves.

Today, ISS crews draw and centrifuge their own blood, but samples are frozen and analyzed on Earth weeks or months later. On a Mars mission, samples can't come back, and every message takes minutes each way. MissionVitals gives the crew answers on board.

## What it does

| Layer | Signals | How often |
| --- | --- | --- |
| Real-time | Radiation dose rate and mission total, resting heart rate | Hourly |
| Blood panel (SERS) | CRP (inflammation), cortisol (stress), glucose | Every 1–2 days |
| Daily check | Mood questionnaire (Gemini), reaction time | Daily |

- **Rules raise the alarms.** `rules.py` compares each signal to the astronaut's own baseline and labels it green, yellow or red. Alarms work offline and never wait on the network.
- **Gemini explains them.** The "Explain with Gemini" button sends the current reading, the last 72 hours and the flagged rules to Gemini, which returns a plain summary, the reason and 2–3 actions. Gemini also writes and scores the daily mood questions. It never changes the status colors.
- **Mission control gets a copy.** Readings sync to a Cloudflare Worker and D1 database after a simulated Earth–Mars delay.
- **The ground team is alerted.** When the status changes to red, the Worker sends a WhatsApp message through Twilio: at most one per 30 minutes, with no health numbers in the message.

## How it works

```
data.py (simulated 7-day mission, calibrated with NASA data)
   │
   ├─► mission.db (SQLite, on board)
   │      │
   │      ├─► rules.py (green / yellow / red)
   │      ├─► ai.py (Gemini: explanation + mood check)
   │      └─► app.py (Streamlit dashboard)
   │
   └─► sync ──► Cloudflare Worker ──► D1 (mission control)
                     │
                     └─► Twilio WhatsApp (ground team, on change to red)
```

## Real vs simulated

We have no astronaut hardware, so the sensors are simulated and labeled on screen. Everything after the sensors runs for real.

| Part | Status |
| --- | --- |
| Dose, heart rate, SERS blood panel, daily scores | Simulated (labeled) |
| Inspiration4 crew blood (glucose, CRP) | Real NASA data |
| Gemini explanation and mood check | Live |
| Sync to Cloudflare | Live |
| WhatsApp alert | Live (Twilio WhatsApp Sandbox) |

The demo mission covers 7 days (168 hourly readings) with a solar flare on day 3 that peaks at about 28× the normal dose rate.

## NASA data

- **OSD-575 (Inspiration4 crew blood, NASA Open Science Data Repository):** metabolic panel (glucose) and cardiovascular panel (CRP).
  - Our glucose baseline (75.3 mg/dL) is the crew's real pre-flight average.
  - Our simulated CRP rise (~2.5× baseline) matches the crew's real rise the day after landing (0.8–2.1×). We first simulated 5–8× and lowered it to match the real data.
  - Caveats: 4 crew, blood drawn before and after the flight (not during), large individual differences.
- **OSD-157 (human blood irradiated in the lab, 0–8 Gy):** cited as evidence that blood can reveal radiation exposure; not loaded into the app.

## What we tried

- **SERS (surface-enhanced Raman spectroscopy):** our original plan for the blood panel. A 2025 study read blood serum with a handheld Raman device, and animal studies found CRP rises after radiation. But SERS needs a laser, a spectrometer and lab preparation, has only been tested on the ground, and radiation markers were shown only at accident-level doses. We simulated the panel instead.
- **Our own wearable:** a diode or Geiger-style radiation counter plus a pulse sensor on a microcontroller. We didn't have the components or tools to build and test it safely, so we built the software any real sensor would plug into.

## Tech stack

| Area | Tools |
| --- | --- |
| Dashboard | Python, Streamlit, pandas, Altair |
| AI | Google Gemini API (`google-genai`) |
| On-board storage | SQLite |
| Mission control | Cloudflare Workers (TypeScript), Cloudflare D1, Wrangler |
| Alerts | Twilio WhatsApp Sandbox |
| Hosting | Streamlit Community Cloud |

## Project structure

```
app.py            Streamlit dashboard
ai.py             Gemini: explanation and mood questionnaire
rules.py          Alert rules (green / yellow / red) and baselines
data.py           Simulated mission, SQLite storage, sync to mission control
i4_data.py        Cleans the Inspiration4 (OSD-575) files
data/i4_blood.csv Cleaned Inspiration4 blood data
worker/           Cloudflare Worker, D1 migrations, WhatsApp alert
CLAUDE.md         Team conventions and build steps
```

## Run it locally

Requires Python 3.12+ (tested on 3.14).

```bash
git clone https://github.com/lu-syn/NASA-Space-Apps.git
cd NASA-Space-Apps

# Windows
python -m venv .venv
.venv\Scripts\activate
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file (never commit it):

```
GEMINI_API_KEY=your_gemini_key
# Optional, only for syncing to mission control:
WORKER_URL=https://your-worker.workers.dev
SYNC_KEY=your_sync_key
```

Then:

```bash
python data.py                    # build the simulated mission (mission.db)
python -m streamlit run app.py    # open the dashboard
python data.py sync 0             # optional: sync to mission control now
```

Without `WORKER_URL` and `SYNC_KEY`, the app runs fully on board and skips syncing.

## Mission control (Cloudflare)

The Worker in `worker/` exposes `POST /readings` and `GET /readings`, protected by an `X-Sync-Key` header, and stores readings in a D1 database. Requires Node.js.

```bash
cd worker
npm install
npx wrangler login
npx wrangler d1 migrations apply astro-db --remote
npx wrangler secret put SYNC_KEY
npx wrangler secret put TWILIO_ACCOUNT_SID
npx wrangler secret put TWILIO_AUTH_TOKEN
npx wrangler secret put TWILIO_FROM      # whatsapp:+1...
npx wrangler secret put ALERT_TO         # whatsapp:+1...
npm run deploy
```

**WhatsApp alerts:** we use the Twilio WhatsApp Sandbox because US SMS from a new number needs carrier registration that takes 10–15 business days. Join the sandbox by sending its join code from WhatsApp; the sandbox can message you within 24 hours of your last message to it.

## Privacy and safety

- All data is simulated or public; no real patient data.
- The WhatsApp alert carries no health numbers, only a prompt to open the dashboard.
- Mission control data sits behind a key-protected API; secrets are stored in `.env`, Cloudflare secrets and Streamlit secrets, never in the repo.
- MissionVitals supports, and does not replace, the flight surgeon. It is not a medical device.
- The 10 mGy mission dose budget is a demo value; real limits are set over a career.

## What's next

- Real dosimeter and wearable input
- Validate SERS radiation markers at real space doses
- Run the AI on board for deep space, with no live Earth link
- A crew view for flight surgeons

## Team


| Name | Focus |
| --- | --- |
| Luis | Data and cloud |
| Liz | AI and alert rules |
| Gowri | Dashboard and design |

## Sources

- [Inspiration4 data access through NASA OSDR (npj Microgravity, 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11094041)
- [Inspiration4 crew immune profiles: CRP up after flight](https://pmc.ncbi.nlm.nih.gov/articles/pmid/38862516)
- [Portable Raman SERS for blood biomarkers in spaceflight (2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12994128/)
- [SERS CRP test after radiation in nonhuman primates (Analyst, 2018)](https://pubs.rsc.org/os/content/articlelanding/2018/an/c8an00160j)
- [OSD-157: human blood irradiated ex vivo](https://catalog.data.gov/dataset/gene-expression-in-human-peripheral-blood-48-hours-after-exposure-to-ionizing-radiation)
- [ISS blood centrifuge: astronauts process their own samples](https://druckerdiagnostics.com/resources/blog/how-drucker-helped-bring-centrifugation-to-the-international-space-station/)
- [Twilio: unregistered US 10DLC messaging blocked](https://support.twilio.com/hc/en-us/articles/14910496447771-Shutdown-of-Unregistered-10DLC-Messaging)
