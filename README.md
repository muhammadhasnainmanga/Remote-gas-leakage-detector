# MQ-2 dashboard and readings API

The FastAPI service accepts Pico W samples, stores them in Neon, sends threshold reminder emails, and serves the dashboard at `/` from the same Azure App Service.

## Dashboard

The dashboard has separate Leakage and Weight views. The Weight view shows gross weight, estimated gas remaining after subtracting the saved empty-cylinder weight, the last reading time, and hourly/daily/weekly weight graphs. A kg/g toggle changes website display only; Neon always stores the measured weight in grams. You can enter the empty cylinder's gross weight in kg on the page. The page refreshes dashboard data once per minute and also has a manual refresh button.

The hourly graph shows the last hour in 1-minute averages, daily uses 5-minute averages, and weekly uses hourly averages. At the current rate of about 11 readings per minute, the hourly graph represents about 660 readings. The API groups readings in Neon before sending them to the browser and the chart tooltip shows the actual sample count for each interval.

The dashboard data endpoint is `GET /api/dashboard?period=hourly|daily|weekly`. It is read-only and public. Database credentials and the Pico token are only used by the backend.

## Device endpoints

- `POST /api/readings` body: `{"value": 12345, "device_id": "pico-mq2-1"}`
- `POST /api/load-cell` body: `{"weight_grams": 12500, "device_id": "pico-mq2-1"}`

Both device endpoints require `Authorization: Bearer <DEVICE_TOKEN>`. Pico sends MQ-2 readings every five seconds and load-cell readings immediately at startup, then once per minute. The low-weight alert is based on estimated gas remaining (gross reading minus empty-cylinder weight); an email is sent when it crosses below 0.5 kg.

The firmware uses the calibrated HX711 settings from `Project2-source/blink.py`: DT/DOUT to Pico GP16, SCK/CLK to GP17, calibration factor 201.75, polarity -1, and 20 samples for startup tare. Each minute it saves one live, unsmoothed HX711 reading in grams. Leave the scale empty while the Pico starts.

## Neon tables and cylinder setup

`mq2_readings` is the existing sensor table. On startup, the API creates `mq2_email_alerts` and `loadcell_email_alerts`. Run the SQL in [`loadcell_schema.sql`](loadcell_schema.sql) once in Neon before deploying the updated API. It creates the reading history, empty-cylinder setting, and low-weight email log tables.

The API stores load-cell samples as grams in `loadcell_reading`. The weight graph plots each saved measurement directly without averaging or smoothing. Empty-cylinder gross weight is saved from the Weight page in `cylinder_settings`; the estimated gas is `max(gross_weight - empty_weight, 0)`. Low-weight emails are sent when remaining gas first falls below 500 grams, and will send again only after the weight rises above the threshold and falls below it again. Configure the existing `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, and `SMTP_PASSWORD` App Service settings for email delivery.

The configured MQ-2 threshold is a temporary raw ADC demo value, not calibrated LPG ppm. Calibrate before presenting it as an LPG detection level.

## Local run

Install `requirements.txt`, then run `python -m uvicorn app:app --host 0.0.0.0 --port 8000`. The Neon table `mq2_readings` must already exist.
