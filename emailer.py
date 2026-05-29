import logging
import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def smtp_config():
    load_dotenv()
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from": os.environ.get("SMTP_FROM"),
    }


def send_email_notification(to_email, subject, body):
    if not to_email:
        return False

    config = smtp_config()
    if not all([config["host"], config["from"]]):
        logger.info("SMTP_HOST or SMTP_FROM is not configured; email notification skipped.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from"]
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as smtp:
            smtp.starttls()
            if config["user"] and config["password"]:
                smtp.login(config["user"], config["password"])
            smtp.send_message(message)
        return True
    except Exception as exc:
        logger.warning("Email notification failed: %s", exc)
        return False
