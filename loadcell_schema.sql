-- Run once in the Neon SQL editor before deploying the updated API.

-- All load-cell measurements are stored in grams.
CREATE TABLE IF NOT EXISTS loadcell_reading (
    id BIGSERIAL PRIMARY KEY,
    weight_grams DOUBLE PRECISION NOT NULL CHECK (weight_grams >= 0),
    device_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loadcell_reading_recorded_at
    ON loadcell_reading (recorded_at DESC);

CREATE TABLE IF NOT EXISTS cylinder_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    empty_weight_grams DOUBLE PRECISION NOT NULL CHECK (empty_weight_grams > 0),
    low_alert_active BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS loadcell_email_alerts (
    id BIGSERIAL PRIMARY KEY,
    reading_id BIGINT,
    weight_grams DOUBLE PRECISION NOT NULL,
    remaining_grams DOUBLE PRECISION NOT NULL,
    device_id TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loadcell_email_alerts_sent_at
    ON loadcell_email_alerts (sent_at DESC);
