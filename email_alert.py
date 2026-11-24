"""SMTP helper for MQ-2 threshold alerts."""

import os
import smtplib
from email.message import EmailMessage

# Put the visible email addresses here.
EMAIL_FROM = "muhammadhasnainmanga@gmail.com"
EMAIL_TO = "muhammadhasnainmanga@gmail.com, ishikaadvani16@gmail.com"


def send_lpg_alert(value: int, device_id: str, threshold: int) -> None:
    """Send one plain-text alert email; raises an exception if SMTP fails."""
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    message = EmailMessage()
    message["Subject"] = "Alert !! MQ-2 reading crossed the configured threshold"
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message.set_content(
        "An MQ-2 raw reading reached or exceeded the configured threshold.\n\n"
        f"Device: {device_id}\n"
        f"Raw ADC reading: {value}\n"
        f"Configured raw threshold: {threshold}\n\n"
        "This is a raw sensor reading, not a calibrated LPG concentration in ppm."
    )

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


def send_low_weight_alert(weight_grams: float, empty_weight_grams: float,
                          remaining_grams: float, device_id: str) -> None:
    """Send an alert when estimated gas remaining falls below 500 grams."""
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]

    message = EmailMessage()
    message["Subject"] = "SafeKitchen alert: cylinder gas is low"
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message.set_content(
        "Estimated cylinder gas has fallen below 0.5 kg.\n\n"
        f"Device: {device_id}\n"
        f"Gross cylinder weight: {weight_grams / 1000:.3f} kg\n"
        f"Configured empty-cylinder weight: {empty_weight_grams / 1000:.3f} kg\n"
        f"Estimated gas remaining: {remaining_grams / 1000:.3f} kg\n"
    )

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
