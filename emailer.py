import logging
import os
import smtplib
from email.message import EmailMessage

import requests
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


def resend_config():
    load_dotenv()
    return {
        "api_key": os.environ.get("RESEND_API_KEY"),
        "from": os.environ.get("RESEND_FROM"),
    }


def send_resend_email(to_email, subject, body):
    config = resend_config()
    if not all([config["api_key"], config["from"]]):
        return False

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "from": config["from"],
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        response_text = getattr(exc.response, "text", "") if getattr(exc, "response", None) else ""
        logger.warning("Resend email notification failed: %s %s", exc, response_text)
        return False


def send_smtp_email(to_email, subject, body):
    config = smtp_config()
    if not all([config["host"], config["from"]]):
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
        logger.warning("SMTP email notification failed: %s", exc)
        return False


def send_email_notification(to_email, subject, body):
    if not to_email:
        return False

    resend = resend_config()
    if resend["api_key"] and resend["from"]:
        return send_resend_email(to_email, subject, body)

    smtp = smtp_config()
    if smtp["host"] and smtp["from"]:
        return send_smtp_email(to_email, subject, body)

    logger.info("Email notification skipped: Resend and SMTP are not configured.")
    return False
