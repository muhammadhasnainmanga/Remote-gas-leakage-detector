import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from email_alert import send_lpg_alert, send_low_weight_alert

DATABASE_URL = 'postgresql://neondb_owner:npg_cpNXR0EOgD4j@ep-misty-meadow-bev3ppdk-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
DEVICE_TOKEN = '8nmWa9S8z62d3Ts3RdDB68MNfjCIxWt8mTcBFCatjtw'

LPG_RAW_THRESHOLD = 17000  # Demo threshold only; calibrate before claiming LPG detection.

last_email_sent_at = 0.0

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'

#just like initializing app in js idher fastapi karwa rhe
app = FastAPI(title='MQ-2 Dashboard API', version='1.1.0')

app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


class Reading(BaseModel):
    value: int = Field(ge=0, le=65535)
    device_id: str = Field(min_length=1, max_length=64)


class LoadCellReading(BaseModel):
    weight_grams: float = Field(ge=0, le=100000)
    device_id: str = Field(min_length=1, max_length=64)


class CylinderSettings(BaseModel):
    empty_weight_grams: float = Field(gt=0, le=100000)


def require_device_token(authorization: str | None) -> None:
    if authorization != f'Bearer {DEVICE_TOKEN}':
        raise HTTPException(status_code=401, detail='Unauthorized')


#run on startup and make sure everything is set up
@app.on_event('startup')
def ensure_dashboard_tables() -> None:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mq2_email_alerts (
                        id BIGSERIAL PRIMARY KEY,
                        reading_id BIGINT,
                        value INTEGER NOT NULL,
                        device_id TEXT NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_mq2_email_alerts_sent_at
                    ON mq2_email_alerts (sent_at DESC)
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS loadcell_email_alerts (
                        id BIGSERIAL PRIMARY KEY,
                        reading_id BIGINT,
                        weight_grams DOUBLE PRECISION NOT NULL,
                        remaining_grams DOUBLE PRECISION NOT NULL,
                        device_id TEXT NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                ''')
        print('Dashboard database tables are ready')
    except psycopg.Error as exc:
        print(f'Dashboard table setup failed: {type(exc).__name__}')


@app.get('/')
def dashboard_page():
    return FileResponse(STATIC_DIR / 'index.html')

#just for checking if the server is working or not
@app.get('/health')
def health():
    return {'status': 'ok'}


#sending threeshold alert after 60 sec from the last one, if it is reached right now
def maybe_send_threshold_alert(value: int, device_id: str, reading_id: int) -> bool:
    global last_email_sent_at
    if value < LPG_RAW_THRESHOLD:
        return False
    now = time.monotonic()
    if now - last_email_sent_at < 60:
        return False
    last_email_sent_at = now
    try:
        #sending mail
        send_lpg_alert(value, device_id, LPG_RAW_THRESHOLD)
        #adding the data in to databse
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        'INSERT INTO mq2_email_alerts (reading_id, value, device_id) VALUES (%s, %s, %s)',
                        (reading_id, value, device_id),
                    )
            print(f'Threshold alert email sent for device {device_id}')
        except psycopg.Error as exc:
            print(f'Email sent but dashboard log failed: {type(exc).__name__}')
        return True
    except Exception as exc:
        print(f'Threshold alert email failed: {type(exc).__name__}')
        return False


#sending reading on the database via server
@app.post('/api/readings', status_code=201)
def create_reading(reading: Reading, authorization: str | None = Header(default=None)):
    require_device_token(authorization)
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO mq2_readings (value, device_id) VALUES (%s, %s) RETURNING id, recorded_at',
                    (reading.value, reading.device_id),
                )
                row_id, recorded_at = cursor.fetchone()
    except psycopg.Error as exc:
        print(f'Database insert failed: {type(exc).__name__}')
        raise HTTPException(status_code=503, detail='Database insert failed') from exc
    maybe_send_threshold_alert(reading.value, reading.device_id, row_id)
    return {'id': row_id, 'value': reading.value, 'device_id': reading.device_id,
            'recorded_at': recorded_at.isoformat()}


@app.post('/api/load-cell', status_code=201)
def create_load_cell_reading(reading: LoadCellReading,
                             authorization: str | None = Header(default=None)):
    require_device_token(authorization)
    empty_weight = None
    low_alert_was_active = False
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT empty_weight_grams, low_alert_active FROM cylinder_settings WHERE id = 1 FOR UPDATE'
                )
                settings_row = cursor.fetchone()
                empty_weight = float(settings_row[0]) if settings_row else None
                low_alert_was_active = bool(settings_row[1]) if settings_row else False
                cursor.execute(
                    'INSERT INTO loadcell_reading (weight_grams, device_id) VALUES (%s, %s) RETURNING id, recorded_at',
                    (reading.weight_grams, reading.device_id),
                )
                row_id, recorded_at = cursor.fetchone()
                remaining_weight = max(0.0, reading.weight_grams - empty_weight) if empty_weight is not None else None
                low_alert_active = remaining_weight is not None and remaining_weight < 500
                if settings_row and low_alert_active != low_alert_was_active:
                    cursor.execute(
                        'UPDATE cylinder_settings SET low_alert_active = %s WHERE id = 1',
                        (low_alert_active,),
                    )
    except psycopg.Error as exc:
        print(f'Load-cell insert failed: {type(exc).__name__}')
        raise HTTPException(status_code=503, detail='Load-cell insert failed') from exc

    low_alert_active = remaining_weight is not None and remaining_weight < 500
    should_send_low_alert = low_alert_active and not low_alert_was_active
    if should_send_low_alert:
        try:
            send_low_weight_alert(reading.weight_grams, empty_weight,
                                  remaining_weight, reading.device_id)
            with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        'INSERT INTO loadcell_email_alerts (reading_id, weight_grams, remaining_grams, device_id) VALUES (%s, %s, %s, %s)',
                        (row_id, reading.weight_grams, remaining_weight, reading.device_id),
                    )
        except Exception as exc:
            print(f'Low-weight alert failed: {type(exc).__name__}')
            try:
                with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute('UPDATE cylinder_settings SET low_alert_active = FALSE WHERE id = 1')
            except psycopg.Error:
                pass
    return {'id': row_id, 'weight_grams': reading.weight_grams,
            'device_id': reading.device_id, 'recorded_at': recorded_at.isoformat()}


@app.get('/api/cylinder-settings')
def get_cylinder_settings():
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT empty_weight_grams FROM cylinder_settings WHERE id = 1')
                row = cursor.fetchone()
    except psycopg.Error as exc:
        print(f'Cylinder settings query failed: {type(exc).__name__}')
        raise HTTPException(status_code=503, detail='Cylinder settings unavailable') from exc
    return {'empty_weight_grams': float(row[0]) if row else None}


@app.put('/api/cylinder-settings')
def update_cylinder_settings(settings: CylinderSettings):
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO cylinder_settings (id, empty_weight_grams)
                    VALUES (1, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET empty_weight_grams = EXCLUDED.empty_weight_grams,
                        updated_at = NOW(),
                        low_alert_active = FALSE
                    RETURNING empty_weight_grams
                ''', (settings.empty_weight_grams,))
                row = cursor.fetchone()
    except psycopg.Error as exc:
        print(f'Cylinder settings update failed: {type(exc).__name__}')
        raise HTTPException(status_code=503, detail='Could not save cylinder settings') from exc
    return {'empty_weight_grams': float(row[0])}


#getting all the required value for dashboard
@app.get('/api/dashboard')
def dashboard_data(period: str = Query(default='hourly'),
                   weight_period: str = Query(default='hourly')):
    if period not in {'hourly', 'daily', 'weekly'}:
        raise HTTPException(status_code=422, detail='period must be hourly, daily, or weekly')
    if weight_period not in {'hourly', 'daily', 'weekly'}:
        raise HTTPException(status_code=422, detail='weight_period must be hourly, daily, or weekly')

    windows = {'hourly': '1 hour', 'daily': '24 hours', 'weekly': '7 days'}
    bucket_widths = {'hourly': '1 minute', 'daily': '5 minutes', 'weekly': '1 hour'}
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT value, device_id, recorded_at FROM mq2_readings ORDER BY recorded_at DESC LIMIT 1')
                latest = cursor.fetchone()
                cursor.execute('''
                    SELECT AVG(value)::double precision AS average
                    FROM mq2_readings WHERE recorded_at >= NOW() - INTERVAL '24 hours'
                ''')
                average_24h = cursor.fetchone()['average']
                cursor.execute('''
                    SELECT date_bin(%s::interval, recorded_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
                           AVG(value)::double precision AS average,
                           MIN(value) AS minimum, MAX(value) AS maximum, COUNT(*) AS samples
                    FROM mq2_readings
                    WHERE recorded_at >= NOW() - %s::interval
                    GROUP BY bucket ORDER BY bucket
                ''', (bucket_widths[period], windows[period]))
                points = cursor.fetchall()
                cursor.execute('''
                    SELECT value, recorded_at FROM mq2_readings
                    WHERE value >= %s ORDER BY recorded_at DESC LIMIT 1
                ''', (LPG_RAW_THRESHOLD,))
                detection = cursor.fetchone()
                cursor.execute('SELECT COUNT(*) AS total FROM mq2_email_alerts')
                emails = cursor.fetchone()
                cursor.execute('''
                    SELECT weight_grams, device_id, recorded_at
                    FROM loadcell_reading ORDER BY recorded_at DESC LIMIT 1
                ''')
                load_cell = cursor.fetchone()
                cursor.execute('''
                    SELECT recorded_at, weight_grams
                    FROM loadcell_reading
                    WHERE recorded_at >= NOW() - %s::interval
                    ORDER BY recorded_at
                ''', (windows[weight_period],))
                weight_points = cursor.fetchall()
                cursor.execute('SELECT empty_weight_grams FROM cylinder_settings WHERE id = 1')
                cylinder_settings = cursor.fetchone()
    except psycopg.Error as exc:
        print(f'Dashboard query failed: {type(exc).__name__}')
        raise HTTPException(status_code=503, detail='Dashboard data unavailable') from exc

    latest_value = latest['value'] if latest else None
    latest_at = latest['recorded_at'] if latest else None
    stale = latest_at is None or datetime.now(timezone.utc) - latest_at > timedelta(minutes=2)
    status = 'offline' if stale else ('alert' if latest_value >= LPG_RAW_THRESHOLD else 'normal')
    empty_g = float(cylinder_settings['empty_weight_grams']) if cylinder_settings else None
    weight_g = float(load_cell['weight_grams']) if load_cell else None
    remaining_g = max(0.0, weight_g - empty_g) if weight_g is not None and empty_g is not None else None

    return {
        'period': period,
        'weight_period': weight_period,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'threshold': LPG_RAW_THRESHOLD,
        'mq2': {
            'latest_value': latest_value,
            'latest_at': _iso(latest_at),
            'device_id': latest['device_id'] if latest else None,
            'status': status,
            'average_24h': round(float(average_24h), 1) if average_24h is not None else None,
            'last_threshold_hit': {
                'value': detection['value'], 'time': _iso(detection['recorded_at'])
            } if detection else None,
            'points': [
                {'time': _iso(row['bucket']), 'average': round(float(row['average']), 1),
                 'minimum': row['minimum'], 'maximum': row['maximum'], 'samples': row['samples']}
                for row in points
            ],
        },
        'emails': {'total': int(emails['total'])},
        'cylinder': {
            'has_reading': load_cell is not None,
            'weight_grams': round(weight_g, 1) if weight_g is not None else None,
            'recorded_at': _iso(load_cell['recorded_at']) if load_cell else None,
            'empty_weight_grams': round(empty_g, 1) if empty_g is not None else None,
            'remaining_grams': round(remaining_g, 1) if remaining_g is not None else None,
            'low_weight': remaining_g is not None and remaining_g < 500,
            'points': [
                {'time': _iso(row['recorded_at']), 'weight_grams': round(float(row['weight_grams']), 1)}
                for row in weight_points
            ],
        },
    }

def _iso(value):
    return value.isoformat() if value is not None else None


def _optional_float(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None
