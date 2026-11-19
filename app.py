import time

import psycopg
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from email_alert import send_lpg_alert


DATABASE_URL = 'postgresql://neondb_owner:npg_cpNXR0EOgD4j@ep-misty-meadow-bev3ppdk-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
DEVICE_TOKEN = '8nmWa9S8z62d3Ts3RdDB68MNfjCIxWt8mTcBFCatjtw'

app = FastAPI(title="MQ-2 readings API", version="1.0.0")

# Set this to the calibrated raw ADC threshold. None keeps alerts off.
LPG_RAW_THRESHOLD = None
last_email_sent_at = 0


class Reading(BaseModel):
    value: int = Field(ge=0, le=65535)
    device_id: str = Field(min_length=1, max_length=64)


@app.get("/health")
def health():
    return {"status": "ok"}


def maybe_send_threshold_alert(value: int, device_id: str) -> None:
    global last_email_sent_at

    if LPG_RAW_THRESHOLD is None or value < LPG_RAW_THRESHOLD:
        return

    now = time.monotonic()
    if now - last_email_sent_at < 60:
        return

    last_email_sent_at = now
    try:
        send_lpg_alert(value, device_id, LPG_RAW_THRESHOLD)
        print(f"Threshold alert email sent for device {device_id}")
    except Exception as exc:
        print(f"Threshold alert email failed: {type(exc).__name__}")

@app.post("/api/readings", status_code=201)
def create_reading(reading: Reading, authorization: str | None = Header(default=None)):
    if not DATABASE_URL or not DEVICE_TOKEN:
        raise HTTPException(status_code=503, detail="API is not configured")

    if authorization != f"Bearer {DEVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO mq2_readings (value, device_id) VALUES (%s, %s) RETURNING id, recorded_at",
                    (reading.value, reading.device_id),
                )
                row_id, recorded_at = cursor.fetchone()
    except psycopg.Error as exc:
        # Keep credentials and database details out of the public response.
        print(f"Database insert failed:  {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Database insert failed") from exc

    maybe_send_threshold_alert(reading.value, reading.device_id)

    return {"id": row_id, "value": reading.value, "device_id": reading.device_id,
            "recorded_at": recorded_at.isoformat()}
