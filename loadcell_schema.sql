-- Run in the Neon SQL editor before deploying the updated API.
-- This is safe to run again after it has been applied once.

CREATE TABLE IF NOT EXISTS loadcell_reading (
    id BIGSERIAL PRIMARY KEY,
    weight_grams DOUBLE PRECISION NOT NULL CHECK (weight_grams >= 0),
    device_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device_time TIMESTAMPTZ,
    boot_id TEXT,
    sequence BIGINT
);
ALTER TABLE loadcell_reading ADD COLUMN IF NOT EXISTS device_time TIMESTAMPTZ;
ALTER TABLE loadcell_reading ADD COLUMN IF NOT EXISTS boot_id TEXT;
ALTER TABLE loadcell_reading ADD COLUMN IF NOT EXISTS sequence BIGINT;
CREATE INDEX IF NOT EXISTS idx_loadcell_reading_recorded_at
    ON loadcell_reading (recorded_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_loadcell_reading_device_sequence
    ON loadcell_reading (device_id, boot_id, sequence);

CREATE TABLE IF NOT EXISTS cylinder_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    empty_weight_grams DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (empty_weight_grams >= 0),
    low_alert_active BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE cylinder_settings ALTER COLUMN empty_weight_grams SET DEFAULT 0;
ALTER TABLE cylinder_settings ALTER COLUMN empty_weight_grams DROP NOT NULL;
ALTER TABLE cylinder_settings DROP CONSTRAINT IF EXISTS cylinder_settings_empty_weight_grams_check;
UPDATE cylinder_settings SET empty_weight_grams = 0 WHERE empty_weight_grams IS NULL;
INSERT INTO cylinder_settings (id, empty_weight_grams)
VALUES (1, 0) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS mq2_sample_state (
    device_id TEXT PRIMARY KEY,
    high_streak INTEGER NOT NULL DEFAULT 0,
    alert_active BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('mq2', 'cylinder')),
    device_id TEXT NOT NULL,
    reading_id BIGINT,
    boot_id TEXT,
    sequence BIGINT,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sending', 'retry', 'sent')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (device_id, alert_type, boot_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_notification_outbox_pending
    ON notification_outbox (next_attempt_at, created_at)
    WHERE status IN ('queued', 'retry', 'sending');

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

ALTER TABLE mq2_readings ADD COLUMN IF NOT EXISTS device_time TIMESTAMPTZ;
ALTER TABLE mq2_readings ADD COLUMN IF NOT EXISTS boot_id TEXT;
ALTER TABLE mq2_readings ADD COLUMN IF NOT EXISTS sequence BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mq2_readings_device_sequence
    ON mq2_readings (device_id, boot_id, sequence);
CREATE INDEX IF NOT EXISTS idx_mq2_readings_recorded_at
    ON mq2_readings (recorded_at DESC);
