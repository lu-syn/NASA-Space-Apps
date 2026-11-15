-- Remembers when the last WhatsApp alert was sent, so a burst of red readings
-- (or a re-sync) can't spam the crew's phone: at most one alert per 30 minutes.
-- Key -> value so we can add other alert bookkeeping later without a new table.
CREATE TABLE IF NOT EXISTS alert_log (
    key   TEXT PRIMARY KEY,
    value TEXT
);
