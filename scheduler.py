import logging
import os
import time
from datetime import timedelta

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from models import CheckResult, Incident, Monitor, JST, db, now_jst
from notifier import send_discord_notification
from emailer import send_email_notification
from security import is_monitor_url_allowed


logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; kanshi/1.0; +https://kanshi.local/status)"
}


def format_datetime(dt):
    return dt.strftime("%Y年%m月%d日 %H:%M")


def status_page_url(monitor):
    base_url = os.environ.get("BASE_URL") or os.environ.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000"
    base_url = base_url.rstrip("/")
    return f"{base_url}/status/{monitor.slug}"


def ensure_jst(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt


def check_monitor(monitor):
    if monitor.is_paused:
        logger.info("Monitor check skipped because paused: %s", monitor.url)
        return

    previous = monitor.latest_result
    previous_status = previous.status if previous else None
    checked_at = now_jst()
    response_time_ms = None
    notification = None

    try:
        if not is_monitor_url_allowed(monitor.url):
            logger.warning("Monitor URL blocked by SSRF protection: %s", monitor.url)
            status = "DOWN"
            raise RuntimeError("blocked private monitor URL")
        started = time.perf_counter()
        response = requests.get(
            monitor.url,
            timeout=TIMEOUT_SECONDS,
            headers=REQUEST_HEADERS,
            allow_redirects=False,
        )
        response_time_ms = int((time.perf_counter() - started) * 1000)
        status = "UP" if response.status_code == 200 else "DOWN"
    except requests.RequestException as exc:
        logger.info("Monitor check failed for %s: %s", monitor.url, exc)
        status = "DOWN"
    except RuntimeError as exc:
        logger.info("Monitor check skipped for %s: %s", monitor.url, exc)

    db.session.add(
        CheckResult(
            monitor_id=monitor.id,
            status=status,
            response_time_ms=response_time_ms,
            checked_at=checked_at,
        )
    )

    if previous_status != status:
        notification = handle_status_change(monitor, previous_status, status, checked_at)

    db.session.commit()
    if notification:
        send_status_change_notifications(monitor, notification)


def handle_status_change(monitor, previous_status, current_status, changed_at):
    if current_status == "DOWN":
        if not monitor.open_incident:
            db.session.add(Incident(monitor_id=monitor.id, started_at=changed_at))

        if previous_status in ("UP", None):
            return {"status": "DOWN", "changed_at": changed_at, "duration": None}

    if current_status == "UP" and previous_status == "DOWN":
        incident = monitor.open_incident
        duration = 0
        if incident:
            incident.resolved_at = changed_at
            started_at = ensure_jst(incident.started_at)
            duration = max(1, int((changed_at - started_at).total_seconds() // 60))
            incident.duration_minutes = duration

        return {"status": "UP", "changed_at": changed_at, "duration": duration}

    return None


def send_status_change_notifications(monitor, notification):
    current_status = notification["status"]
    changed_at = notification["changed_at"]

    if current_status == "DOWN":
        message = (
            f"🔴 障害検知：{monitor.url} が応答していません。\n"
            f"発生時刻：{format_datetime(changed_at)}\n"
            "原因を調査中です。\n"
            f"公開ステータスページ：{status_page_url(monitor)}"
        )
        if monitor.enable_discord and monitor.discord_webhook:
            send_discord_notification(monitor.discord_webhook, message)
        if monitor.enable_email and monitor.notification_email:
            subject = f"【kanshi】障害検知：{monitor.name}"
            body = (
                f"🔴 障害検知：{monitor.name}\n\n"
                f"{monitor.url} が応答していません。\n\n"
                f"発生時刻：{format_datetime(changed_at)}\n\n"
                "原因を調査中です。\n\n"
                "公開ステータスページ：\n"
                f"{status_page_url(monitor)}"
            )
            send_email_notification(monitor.notification_email, subject, body)

    if current_status == "UP":
        duration = notification["duration"] or 0
        message = (
            f"🟢 復旧：{monitor.url} が復旧しました。\n"
            f"復旧時刻：{format_datetime(changed_at)}\n"
            f"{duration}分間の障害でした。\n"
            f"公開ステータスページ：{status_page_url(monitor)}"
        )
        if monitor.enable_discord and monitor.discord_webhook:
            send_discord_notification(monitor.discord_webhook, message)
        if monitor.enable_email and monitor.notification_email:
            subject = f"【kanshi】復旧：{monitor.name}"
            body = (
                f"🟢 復旧：{monitor.name}\n\n"
                f"{monitor.url} が復旧しました。\n\n"
                f"復旧時刻：{format_datetime(changed_at)}\n\n"
                f"{duration}分間の障害でした。\n\n"
                "公開ステータスページ：\n"
                f"{status_page_url(monitor)}"
            )
            send_email_notification(monitor.notification_email, subject, body)


def check_all_monitors(app):
    with app.app_context():
        monitors = Monitor.query.order_by(Monitor.created_at.asc()).all()
        for monitor in monitors:
            try:
                check_monitor(monitor)
            except Exception:
                db.session.rollback()
                logger.exception("Unexpected error while checking monitor %s", monitor.id)


def start_scheduler(app):
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(
        func=lambda: check_all_monitors(app),
        trigger="interval",
        seconds=60,
        id="monitor_checks",
        replace_existing=True,
        next_run_time=now_jst() + timedelta(seconds=3),
    )
    scheduler.start()
    return scheduler
