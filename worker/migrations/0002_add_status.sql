-- Overall alert status for each reading, computed on the ship (rules.py)
-- before syncing, so the ground team sees the same color the astronaut saw.
-- Nullable: older rows, or senders without rules, simply have no status.
-- The CHECK makes the database itself refuse anything but the three colors.
ALTER TABLE readings
    ADD COLUMN status TEXT CHECK (status IN ('green', 'yellow', 'red'));
