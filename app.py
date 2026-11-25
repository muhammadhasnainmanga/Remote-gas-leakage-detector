import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from email_alert import send_cylinder_alert, send_mq2_alert


DATABASE_URL = 'postgresql://neondb_owner:npg_cpNXR0EOgD4j@ep-misty-meadow-bev3ppdk-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
DEVICE_TOKEN = '8nmWa9S8z62d3Ts3RdDB68MNfjCIxWt8mTcBFCatjtw'
LPG_RAW_THRESHOLD = int(os.getenv("LPG_RAW_THRESHOLD", "17000"))
MQ2_ALERT_SAMPLES = 10
CYLINDER_LOW_GRAMS = 1000
CYLINDER_REARM_GRAMS = 1200
CYLINDER_CAPACITY_GRAMS = 10000

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="SafeKitchen Dashboard API", version="2.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Reading(BaseModel):
    value: int = Field(ge=0, le=65535)
    device_id: str = Field(min_length=1, max_length=64)
    boot_id: str | None = Field(default=None, max_length=64)
    sequence: int | None = Field(default=None, ge=0)
    device_time: datetime | None = None


class LoadCellReading(BaseModel):
    weight_grams: float = Field(ge=0, le=100000)
    device_id: str = Field(min_length=1, max_length=64)
    boot_id: str | None = Field(default=None, max_length=64)
    sequence: int | None = Field(default=None, ge=0)
    device_time: datetime | None = None


class CylinderSettings(BaseModel):
    empty_weight_grams: float = Field(ge=0, le=100000)


def require_database() -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return DATABASE_URL


def require_device_token(authorization: str | None) -> None:
    if not DEVICE_TOKEN:
        raise HTTPException(status_code=503, detail="Device API is not configured")
    if authorization != f"Bearer {DEVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def ensure_dashboard_tables() -> None:
    if not DATABASE_URL:
        print("DATABASE_URL is not configured; database features are unavailable")
        return
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS mq2_email_alerts (
                        id BIGSERIAL PRIMARY KEY,
                        reading_id BIGINT,
                        value INTEGER NOT NULL,
                        device_id TEXT NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loadcell_email_alerts (
                        id BIGSERIAL PRIMARY KEY,
                        reading_id BIGINT,
                        weight_grams DOUBLE PRECISION NOT NULL,
                        remaining_grams DOUBLE PRECISION NOT NULL,
                        device_id TEXT NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loadcell_reading (
                        id BIGSERIAL PRIMARY KEY,
                        weight_grams DOUBLE PRECISION NOT NULL CHECK (weight_grams >= 0),
                        device_id TEXT NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cylinder_settings (
                        id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                        empty_weight_grams DOUBLE PRECISION NOT NULL DEFAULT 0
                            CHECK (empty_weight_grams >= 0),
                        low_alert_active BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                # Upgrade the old positive-only tare column so an unset tare can be 0.
                cursor.execute("ALTER TABLE cylinder_settings ALTER COLUMN empty_weight_grams SET DEFAULT 0")
                cursor.execute("ALTER TABLE cylinder_settings ALTER COLUMN empty_weight_grams DROP NOT NULL")
                cursor.execute("ALTER TABLE cylinder_settings DROP CONSTRAINT IF EXISTS cylinder_settings_empty_weight_grams_check")
                cursor.execute("""
                    UPDATE cylinder_settings SET empty_weight_grams = 0
                    WHERE empty_weight_grams IS NULL
                """)
                cursor.execute("""
                    INSERT INTO cylinder_settings (id, empty_weight_grams)
                    VALUES (1, 0) ON CONFLICT (id) DO NOTHING
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS mq2_sample_state (
                        device_id TEXT PRIMARY KEY,
                        high_streak INTEGER NOT NULL DEFAULT 0,
                        alert_active BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute("""
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
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_outbox_pending
                    ON notification_outbox (next_attempt_at, created_at)
                    WHERE status IN ('queued', 'retry', 'sending')
                """)
                for table in ("mq2_readings", "loadcell_reading"):
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS boot_id TEXT")
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS sequence BIGINT")
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS device_time TIMESTAMPTZ")
                    cursor.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_{table}_recorded_at
                        ON {table} (recorded_at DESC)
                    """)
                    cursor.execute(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_device_sequence
                        ON {table} (device_id, boot_id, sequence)
                    """)
            print("Dashboard database tables are ready")
    except Exception as exc:
        print(f"Dashboard table setup failed: {type(exc).__name__}")


def _enqueue_email(cursor, alert_type: str, device_id: str, reading_id: int,
                   boot_id: str | None, sequence: int | None, payload: dict) -> None:
    cursor.execute("""
        INSERT INTO notification_outbox
            (alert_type, device_id, reading_id, boot_id, sequence, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, alert_type, boot_id, sequence) DO NOTHING
    """, (alert_type, device_id, reading_id, boot_id, sequence, Jsonb(payload)))


def _claim_email():
    if not DATABASE_URL:
        return None
    with psycopg.connect(DATABASE_URL, connect_timeout=10, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                WITH candidate AS (
                    SELECT id FROM notification_outbox
                    WHERE (status IN ('queued', 'retry') AND next_attempt_at <= NOW())
                       OR (status = 'sending' AND claimed_at < NOW() - INTERVAL '5 minutes')
                    ORDER BY created_at
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE notification_outbox AS outbox
                SET status = 'sending', attempts = attempts + 1, claimed_at = NOW()
                FROM candidate WHERE outbox.id = candidate.id
                RETURNING outbox.id, outbox.alert_type, outbox.payload, outbox.attempts
            """)
            return cursor.fetchone()


def _mark_email_sent(email_id: int) -> None:
    with psycopg.connect(require_database(), connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE notification_outbox
                SET status = 'sent', sent_at = NOW(), claimed_at = NULL, last_error = NULL
                WHERE id = %s
            """, (email_id,))


def _mark_email_retry(email_id: int, attempts: int, error: Exception) -> None:
    delay_seconds = min(3600, 15 * (2 ** min(attempts - 1, 8)))
    with psycopg.connect(require_database(), connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE notification_outbox
                SET status = 'retry', claimed_at = NULL,
                    next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                    last_error = %s
                WHERE id = %s
            """, (delay_seconds, type(error).__name__, email_id))


async def _email_worker() -> None:
    """Durable outbox worker; SMTP work stays outside request/interrupt paths."""
    while True:
        try:
            event = await asyncio.to_thread(_claim_email)
            if event is None:
                await asyncio.sleep(2)
                continue
            try:
                send = send_mq2_alert if event["alert_type"] == "mq2" else send_cylinder_alert
                await asyncio.to_thread(send, event["payload"])
                await asyncio.to_thread(_mark_email_sent, event["id"])
            except Exception as exc:
                print(f"Email delivery failed: {type(exc).__name__}")
                await asyncio.to_thread(_mark_email_retry, event["id"], event["attempts"], exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Email worker error: {type(exc).__name__}")
            await asyncio.sleep(5)


@app.on_event("startup")
def startup_database() -> None:
    ensure_dashboard_tables()


@app.on_event("startup")
async def start_email_worker() -> None:
    app.state.email_worker = asyncio.create_task(_email_worker())


@app.on_event("shutdown")
async def stop_email_worker() -> None:
    task = getattr(app.state, "email_worker", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.get("/")
def dashboard_page():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/readings", status_code=201)
def create_reading(reading: Reading, authorization: str | None = Header(default=None)):
    require_device_token(authorization)
    url = require_database()
    try:
        with psycopg.connect(url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO mq2_readings
                        (value, device_id, boot_id, sequence, device_time)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (device_id, boot_id, sequence) DO NOTHING
                    RETURNING id, recorded_at
                """, (reading.value, reading.device_id, reading.boot_id,
                      reading.sequence, reading.device_time))
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute("""
                        SELECT id, recorded_at FROM mq2_readings
                        WHERE device_id = %s AND boot_id = %s AND sequence = %s
                    """, (reading.device_id, reading.boot_id, reading.sequence))
                    duplicate = cursor.fetchone()
                    if duplicate:
                        return {"id": duplicate[0], "duplicate": True}
                    raise RuntimeError("Could not save reading")
                reading_id, recorded_at = inserted

                cursor.execute("""
                    INSERT INTO mq2_sample_state (device_id) VALUES (%s)
                    ON CONFLICT (device_id) DO NOTHING
                """, (reading.device_id,))
                cursor.execute("""
                    SELECT high_streak, alert_active FROM mq2_sample_state
                    WHERE device_id = %s FOR UPDATE
                """, (reading.device_id,))
                high_streak, alert_active = cursor.fetchone()
                high_streak = high_streak + 1 if reading.value >= LPG_RAW_THRESHOLD else 0
                should_alert = high_streak >= MQ2_ALERT_SAMPLES and not alert_active
                if reading.value < LPG_RAW_THRESHOLD:
                    alert_active = False
                elif should_alert:
                    alert_active = True
                cursor.execute("""
                    UPDATE mq2_sample_state
                    SET high_streak = %s, alert_active = %s, updated_at = NOW()
                    WHERE device_id = %s
                """, (high_streak, alert_active, reading.device_id))
                if should_alert:
                    _enqueue_email(cursor, "mq2", reading.device_id, reading_id,
                                   reading.boot_id, reading.sequence,
                                   {"value": reading.value, "threshold": LPG_RAW_THRESHOLD,
                                    "consecutive_samples": MQ2_ALERT_SAMPLES,
                                    "device_id": reading.device_id,
                                    "recorded_at": recorded_at.isoformat()})
    except HTTPException:
        raise
    except Exception as exc:
        print(f"MQ-2 insert failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Reading save failed") from exc
    return {"id": reading_id, "value": reading.value, "device_id": reading.device_id,
            "recorded_at": recorded_at.isoformat(), "high_streak": high_streak,
            "alert_active": alert_active}


@app.post("/api/load-cell", status_code=201)
def create_load_cell_reading(reading: LoadCellReading,
                             authorization: str | None = Header(default=None)):
    require_device_token(authorization)
    url = require_database()
    try:
        with psycopg.connect(url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT empty_weight_grams, low_alert_active
                    FROM cylinder_settings WHERE id = 1 FOR UPDATE
                """)
                settings = cursor.fetchone()
                empty_grams, low_alert_active = settings if settings else (0, False)
                empty_grams = float(empty_grams or 0)
                cursor.execute("""
                    INSERT INTO loadcell_reading
                        (weight_grams, device_id, boot_id, sequence, device_time)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (device_id, boot_id, sequence) DO NOTHING
                    RETURNING id, recorded_at
                """, (reading.weight_grams, reading.device_id, reading.boot_id,
                      reading.sequence, reading.device_time))
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute("""
                        SELECT id, recorded_at FROM loadcell_reading
                        WHERE device_id = %s AND boot_id = %s AND sequence = %s
                    """, (reading.device_id, reading.boot_id, reading.sequence))
                    duplicate = cursor.fetchone()
                    if duplicate:
                        return {"id": duplicate[0], "duplicate": True}
                    raise RuntimeError("Could not save load-cell reading")
                reading_id, recorded_at = inserted
                remaining_grams = max(0.0, reading.weight_grams - empty_grams)
                was_low = bool(low_alert_active)
                should_alert = remaining_grams < CYLINDER_LOW_GRAMS and not was_low
                if remaining_grams >= CYLINDER_REARM_GRAMS:
                    low_alert_active = False
                elif should_alert:
                    low_alert_active = True
                cursor.execute("""
                    INSERT INTO cylinder_settings
                        (id, empty_weight_grams, low_alert_active, updated_at)
                    VALUES (1, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET low_alert_active = EXCLUDED.low_alert_active,
                        updated_at = NOW()
                """, (empty_grams, low_alert_active))
                if should_alert:
                    _enqueue_email(cursor, "cylinder", reading.device_id, reading_id,
                                   reading.boot_id, reading.sequence,
                                   {"weight_grams": reading.weight_grams,
                                    "empty_weight_grams": empty_grams,
                                    "remaining_grams": remaining_grams,
                                    "threshold_grams": CYLINDER_LOW_GRAMS,
                                    "device_id": reading.device_id,
                                    "recorded_at": recorded_at.isoformat()})
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Load-cell insert failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Load-cell save failed") from exc
    return {"id": reading_id, "weight_grams": reading.weight_grams,
            "remaining_grams": remaining_grams, "device_id": reading.device_id,
            "recorded_at": recorded_at.isoformat(), "alert_active": low_alert_active}


@app.get("/api/cylinder-settings")
def get_cylinder_settings():
    try:
        with psycopg.connect(require_database(), connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT empty_weight_grams FROM cylinder_settings WHERE id = 1")
                row = cursor.fetchone()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        print(f"Cylinder settings query failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Cylinder settings unavailable") from exc
    return {"empty_weight_grams": float(row[0] or 0) if row else 0}


@app.put("/api/cylinder-settings")
def update_cylinder_settings(settings: CylinderSettings):
    try:
        with psycopg.connect(require_database(), connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO cylinder_settings (id, empty_weight_grams, low_alert_active)
                    VALUES (1, %s, FALSE)
                    ON CONFLICT (id) DO UPDATE
                    SET empty_weight_grams = EXCLUDED.empty_weight_grams,
                        low_alert_active = FALSE, updated_at = NOW()
                    RETURNING empty_weight_grams
                """, (settings.empty_weight_grams,))
                row = cursor.fetchone()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        print(f"Cylinder settings update failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Could not save cylinder settings") from exc
    return {"empty_weight_grams": float(row[0])}


@app.get("/api/dashboard")
def dashboard_data(period: str = Query(default="hourly"),
                   weight_period: str = Query(default="hourly")):
    valid_periods = {"hourly", "daily", "weekly"}
    if period not in valid_periods:
        period = "hourly"
    if weight_period not in valid_periods:
        weight_period = "hourly"
    windows = {"hourly": "1 hour", "daily": "24 hours", "weekly": "7 days"}
    bucket_widths = {"hourly": "1 minute", "daily": "5 minutes", "weekly": "1 hour"}
    try:
        with psycopg.connect(require_database(), connect_timeout=10,
                             row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT value, device_id, recorded_at FROM mq2_readings
                    ORDER BY recorded_at DESC LIMIT 1
                """)
                latest = cursor.fetchone()
                cursor.execute("""
                    SELECT AVG(value)::double precision AS average
                    FROM mq2_readings WHERE recorded_at >= NOW() - INTERVAL '24 hours'
                """)
                average_24h = cursor.fetchone()["average"]
                cursor.execute("""
                    SELECT date_bin(%s::interval, recorded_at,
                                    TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
                           AVG(value)::double precision AS average,
                           MIN(value) AS minimum, MAX(value) AS maximum, COUNT(*) AS samples
                    FROM mq2_readings
                    WHERE recorded_at >= NOW() - %s::interval
                    GROUP BY bucket ORDER BY bucket
                """, (bucket_widths[period], windows[period]))
                mq2_points = cursor.fetchall()
                cursor.execute("""
                    SELECT high_streak, alert_active FROM mq2_sample_state
                    WHERE device_id = %s
                """, (latest["device_id"],) if latest else ("",))
                mq2_state = cursor.fetchone()
                cursor.execute("""
                    SELECT payload, created_at FROM notification_outbox
                    WHERE alert_type = 'mq2' ORDER BY created_at DESC LIMIT 1
                """)
                latest_mq2_alert = cursor.fetchone()
                cursor.execute("""
                    SELECT weight_grams, device_id, recorded_at FROM loadcell_reading
                    ORDER BY recorded_at DESC LIMIT 1
                """)
                load_cell = cursor.fetchone()
                cursor.execute("""
                    SELECT weight_grams, recorded_at
                    FROM loadcell_reading
                    WHERE recorded_at >= NOW() - %s::interval
                    ORDER BY recorded_at
                """, (windows[weight_period],))
                weight_points = cursor.fetchall()
                cursor.execute("SELECT empty_weight_grams FROM cylinder_settings WHERE id = 1")
                settings = cursor.fetchone()
                cursor.execute("""
                    SELECT alert_type, COUNT(*) FILTER (WHERE status = 'sent') AS total,
                           MAX(sent_at) AS last_sent_at
                    FROM notification_outbox GROUP BY alert_type
                """)
                outbox_stats = {row["alert_type"]: row for row in cursor.fetchall()}
                cursor.execute("""
                    SELECT (SELECT COUNT(*) FROM mq2_email_alerts) AS mq2_legacy,
                           (SELECT COUNT(*) FROM loadcell_email_alerts) AS cylinder_legacy,
                           (SELECT MAX(sent_at) FROM mq2_email_alerts) AS mq2_last,
                           (SELECT MAX(sent_at) FROM loadcell_email_alerts) AS cylinder_last
                """)
                legacy_stats = cursor.fetchone()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        print(f"Dashboard query failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Dashboard data unavailable") from exc

    latest_value = latest["value"] if latest else None
    latest_at = latest["recorded_at"] if latest else None
    stale = latest_at is None or datetime.now(timezone.utc) - latest_at > timedelta(minutes=2)
    high_streak = int(mq2_state["high_streak"]) if mq2_state else 0
    mq2_alert_active = bool(mq2_state["alert_active"]) if mq2_state else False
    mq2_status = "offline" if stale else (
        "alert" if mq2_alert_active else "watch" if high_streak else "normal"
    )
    empty_grams = float(settings["empty_weight_grams"] or 0) if settings else 0.0
    gross_grams = float(load_cell["weight_grams"]) if load_cell else None
    remaining_grams = max(0.0, gross_grams - empty_grams) if gross_grams is not None else None
    mq2_outbox = outbox_stats.get("mq2")
    cylinder_outbox = outbox_stats.get("cylinder")
    mq2_mail_count = int(legacy_stats["mq2_legacy"]) + (int(mq2_outbox["total"]) if mq2_outbox else 0)
    cylinder_mail_count = int(legacy_stats["cylinder_legacy"]) + (int(cylinder_outbox["total"]) if cylinder_outbox else 0)
    last_mq2_mail = max(filter(None, [
        mq2_outbox["last_sent_at"] if mq2_outbox else None, legacy_stats["mq2_last"]
    ]), default=None)
    last_cylinder_mail = max(filter(None, [
        cylinder_outbox["last_sent_at"] if cylinder_outbox else None, legacy_stats["cylinder_last"]
    ]), default=None)

    return {
        "period": period,
        "weight_period": weight_period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold": LPG_RAW_THRESHOLD,
        "mq2_alert_samples": MQ2_ALERT_SAMPLES,
        "mq2": {
            "latest_value": latest_value,
            "latest_at": _iso(latest_at),
            "device_id": latest["device_id"] if latest else None,
            "status": mq2_status,
            "high_streak": high_streak,
            "average_24h": round(float(average_24h), 1) if average_24h is not None else None,
            "last_threshold_hit": {
                "value": latest_mq2_alert["payload"]["value"],
                "time": _iso(latest_mq2_alert["created_at"]),
            } if latest_mq2_alert else None,
            "points": [
                {"time": _iso(row["bucket"]), "average": round(float(row["average"]), 1),
                 "minimum": row["minimum"], "maximum": row["maximum"], "samples": row["samples"]}
                for row in mq2_points
            ],
        },
        "emails": {
            "total": mq2_mail_count + cylinder_mail_count,
            "mq2": {"total": mq2_mail_count, "last_sent_at": _iso(last_mq2_mail)},
            "cylinder": {"total": cylinder_mail_count, "last_sent_at": _iso(last_cylinder_mail)},
            "last_sent_at": _iso(max(filter(None, [last_mq2_mail, last_cylinder_mail]), default=None)),
        },
        "cylinder": {
            "has_reading": load_cell is not None,
            "weight_grams": round(gross_grams, 1) if gross_grams is not None else None,
            "recorded_at": _iso(load_cell["recorded_at"]) if load_cell else None,
            "empty_weight_grams": round(empty_grams, 1),
            "remaining_grams": round(remaining_grams, 1) if remaining_grams is not None else None,
            "capacity_grams": CYLINDER_CAPACITY_GRAMS,
            "low_threshold_grams": CYLINDER_LOW_GRAMS,
            "low_weight": remaining_grams is not None and remaining_grams < CYLINDER_LOW_GRAMS,
            "points": [
                {"time": _iso(row["recorded_at"]),
                 "weight_grams": round(max(0.0, float(row["weight_grams"]) - empty_grams), 1)}
                for row in weight_points
            ],
            "emails": {"total": cylinder_mail_count, "last_sent_at": _iso(last_cylinder_mail)},
        },
    }


def _iso(value):
    return value.isoformat() if value is not None else None
