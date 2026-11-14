-- Ground copy of the astronaut readings. Same columns as the shared row format
-- (and as the readings table in mission.db, minus the local-only `synced` flag).
-- Units: dose_rate µGy/h, total_dose mGy, heart_rate bpm, crp mg/L,
-- cortisol µg/dL, glucose mg/dL, reaction_ms ms, mood 1-5.
-- timestamp is the primary key, so a retried sync replaces instead of duplicating.
CREATE TABLE IF NOT EXISTS readings (
    timestamp   TEXT PRIMARY KEY,
    dose_rate   REAL,
    total_dose  REAL,
    heart_rate  INTEGER,
    crp         REAL,
    cortisol    REAL,
    glucose     INTEGER,
    reaction_ms INTEGER,
    mood        INTEGER
);
