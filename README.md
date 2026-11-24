# SafeKitchen monitor

The Pico W sends MQ-2 and HX711 readings to a FastAPI service on Azure App Service. The API stores readings in Neon Postgres, records alert emails in a durable outbox, and serves the dashboard.

## Current demo behavior

- MQ-2 is sampled and uploaded continuously by `Project2-source/newMQ2.py`; there is no fixed upload interval. An email is queued after **10 consecutive readings at or above raw ADC threshold 17000**. One alert is sent per high streak; a below-threshold reading rearms it. The raw threshold is not calibrated LPG ppm.
- Load-cell weight is averaged from five HX711 samples, rounded to the nearest 10 grams, and uploaded every **15 seconds**. Database values remain grams; the dashboard displays kilograms by default.
- Estimated gas is `max(gross_weight - empty_cylinder_weight, 0)`. If empty-cylinder tare is unset, it defaults to 0. The dashboard shows a 10 kg scale, a 1 kg email threshold, last checked value/time, and cylinder-email count/last-send time. The graph plots estimated gas remaining.
- Low-gas email triggers when estimated gas falls below **1 kg**. It rearms only after weight rises to at least **1.2 kg**, which prevents noisy repeated emails around the threshold.
- Pico assigns each reading a boot ID, sequence number, and (when NTP is available) device timestamp. The API also stores its own receive timestamp and deduplicates retries by device/boot/sequence.
- If the network is down, the Pico keeps a bounded FIFO of 200 readings in `offline_readings.jsonl` and retries them after reconnecting. The timer callback only flags that a weight sample is due; all HX711, file, HTTP, and email operations run outside interrupt callbacks.
- Email sends happen from a database-backed outbox worker, outside the reading request. Failed sends are retried with increasing delays; the dashboard counts successful sends.

## Neon setup

Run [`loadcell_schema.sql`](loadcell_schema.sql) in the Neon SQL editor before deployment. The API also creates and upgrades its operational tables on startup. The existing `mq2_readings` table must contain `value`, `device_id`, and `recorded_at` columns.

Empty-cylinder tare is configuration, separate from measurement history. It is stored server-side so the website and the email threshold use the same value. The website allows 0 kg until the tare is entered.

## API configuration

The prototype keeps its database URL and device token directly in `app.py`; the alert sender and recipients are constants in `email_alert.py`. SMTP server login is read from environment variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, and `SMTP_PASSWORD`). The Pico Wi-Fi settings are in `Project2-source/main.py`, while its API URL and token are in `Project2-source/newMQ2.py`.

## Pico setup

Copy `main.py` and `newMQ2.py` to the Pico W. Wi-Fi settings are directly in `main.py`; API URL and token are directly in `newMQ2.py`. `main.py` attempts NTP clock synchronization; if that fails, server receive timestamps remain available.

The Pico timer is used only to set a flag every 15 seconds. Sampling the HX711 and making HTTP requests happen in the regular main loop, never in the interrupt callback.

## API endpoints

- `POST /api/readings`: continuous MQ-2 readings. Payload includes `value`, `device_id`, `boot_id`, `sequence`, and optional `device_time`.
- `POST /api/load-cell`: load-cell readings every 15 seconds, in grams, with the same deduplication/timestamp fields.
- `GET /api/dashboard?period=hourly|daily|weekly&weight_period=hourly|daily|weekly`
- `GET/PUT /api/cylinder-settings`: read/update empty-cylinder tare in grams.
- `GET /health`: API health.
