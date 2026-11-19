# MQ-2 dashboard and readings API

The FastAPI service accepts Pico W samples, stores them in Neon, sends threshold reminder emails, and serves the dashboard at `/` from the same Azure App Service.

## Dashboard

The dashboard has separate Leakage and Weight views. Leakage shows the latest raw MQ-2 reading and time, a rolling 24-hour average, total successful emails, the latest threshold-hit value and time, a current-reading bar, and daily/weekly/monthly graphs. It fetches on page load and has a button to request fresh data; it does not poll continuously.

The daily graph uses 5-minute averages, weekly uses hourly averages, and monthly uses daily averages. The API groups readings in Neon before sending them to the browser, so a high sample count remains manageable while the chart preserves within-day changes.

The dashboard data endpoint is `GET /api/dashboard?period=daily|weekly|monthly`. It is read-only and public. Database credentials and the Pico token are only used by the backend.

## Device endpoints

- `POST /api/readings` body: `{"value": 12345, "device_id": "pico-mq2-1"}`
- `POST /api/load-cell` body: `{"weight_grams": 12500, "device_id": "pico-mq2-1"}`

Both endpoints require `Authorization: Bearer <DEVICE_TOKEN>`. The current Pico sends MQ-2 readings; it does not yet send load-cell readings.

## Neon tables and cylinder setup

`mq2_readings` is the existing sensor table. On startup, the API creates `mq2_email_alerts` for successfully sent emails and `load_cell_readings` for load-cell samples. The email count starts with sends recorded after this version is deployed; earlier email sends cannot be reconstructed.

To calculate cylinder percentage, set `CYLINDER_EMPTY_WEIGHT_G` to the empty cylinder's gross weight and `CYLINDER_FULL_WEIGHT_G` to its full gross weight in App Service environment variables. The API uses the latest load-cell weight and clamps the result to 0–100%.

The configured MQ-2 threshold is a temporary raw ADC demo value, not calibrated LPG ppm. Calibrate before presenting it as an LPG detection level.

## Local run

Install `requirements.txt`, then run `python -m uvicorn app:app --host 0.0.0.0 --port 8000`. The Neon table `mq2_readings` must already exist.
