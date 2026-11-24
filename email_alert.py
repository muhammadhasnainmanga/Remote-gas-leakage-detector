"""SMTP delivery helpers; server login uses environment settings."""

import os
import smtplib
from email.message import EmailMessage


EMAIL_FROM = 'muhammadhasnainmanga@gmail.com'
EMAIL_TO = 'muhammadhasnainmanga@gmail.com, ishikaadvani16@gmail.com'


def _send(subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    recipients = [item.strip() for item in EMAIL_TO.split(",") if item.strip()]
    if not recipients:
        raise ValueError("EMAIL_TO has no recipients")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)


def send_mq2_alert(data: dict) -> None:
    """Send the gas alert after the configured consecutive high samples."""
    _send(
        "SafeKitchen alert: possible gas detected",
        "The MQ-2 reading stayed above the configured raw threshold for "
        f"{data['consecutive_samples']} consecutive readings.\n\n"
        f"Device: {data['device_id']}\n"
        f"Raw ADC reading: {data['value']}\n"
        f"Configured raw threshold: {data['threshold']}\n"
        f"Reading time: {data['recorded_at']}\n\n"
        "This prototype reports raw sensor values, not calibrated LPG ppm.",
    )


def send_cylinder_alert(data: dict) -> None:
    """Send a warning when estimated gas remaining falls below 1 kg."""
    _send(
        "SafeKitchen alert: cylinder gas below 1 kg",
        "Estimated gas remaining in the cylinder is below 1 kg.\n\n"
        f"Device: {data['device_id']}\n"
        f"Estimated gas remaining: {data['remaining_grams'] / 1000:.2f} kg\n"
        f"Low-gas threshold: {data['threshold_grams'] / 1000:.2f} kg\n"
        f"Reading time: {data['recorded_at']}\n",
    )
