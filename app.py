import os
import re
import secrets
import unicodedata
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from models import CheckResult, Incident, Monitor, db, now_jst
from security import env_enabled, is_monitor_url_allowed
from scheduler import start_scheduler


load_dotenv()


def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "sqlite:///kanshi.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    sslmode = os.environ.get("DATABASE_SSLMODE")
    if sslmode and url.startswith("postgresql://"):
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("sslmode", sslmode)
        url = urlunparse(parsed._replace(query=urlencode(query)))
    return url


def database_engine_options(url):
    if not url.startswith("postgresql://"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 30,
    }


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "kanshi-dev-secret")
DATABASE_URI = database_url()
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = database_engine_options(DATABASE_URI)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
app.config["DEBUG"] = DEBUG
db.init_app(app)


def admin_auth_enabled():
    return bool(os.environ.get("ADMIN_PASSWORD"))


def admin_authorized():
    if not admin_auth_enabled():
        return True

    auth = request.authorization
    expected_username = os.environ.get("ADMIN_USERNAME", "admin")
    expected_password = os.environ.get("ADMIN_PASSWORD", "")
    if not auth:
        return False
    return secrets.compare_digest(auth.username or "", expected_username) and secrets.compare_digest(
        auth.password or "", expected_password
    )


def require_admin_auth():
    return Response(
        "管理画面を見るには認証が必要です。",
        401,
        {"WWW-Authenticate": 'Basic realm="kanshi admin"'},
    )


@app.before_request
def protect_admin_routes():
    public_endpoints = {"beta_page", "status_page", "static"}
    if request.endpoint and request.endpoint not in public_endpoints and not admin_authorized():
        return require_admin_auth()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.template_global()
def csrf_token_value():
    return csrf_token()


def validate_csrf():
    token = session.get("csrf_token")
    submitted = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, submitted):
        abort(400, description="CSRFトークンが無効です。")


def generate_slug(name):
    normalized = unicodedata.normalize("NFKC", name).strip().lower()
    slug = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug or "monitor"


def unique_slug(name):
    base = generate_slug(name)
    candidate = base
    counter = 2
    while Monitor.query.filter_by(slug=candidate).first():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def validate_monitor_form(name, url, current_monitor_id=None):
    errors = []
    if not name:
        errors.append("サービス名を入力してください。")
    if not url:
        errors.append("URLを入力してください。")
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append("URLは http:// または https:// から始めてください。")
        elif not is_monitor_url_allowed(url):
            errors.append("localhost、社内ネットワーク、またはDNS解決できないURLは登録できません。")
        duplicate_query = Monitor.query.filter_by(url=url)
        if current_monitor_id is not None:
            duplicate_query = duplicate_query.filter(Monitor.id != current_monitor_id)
        if duplicate_query.first():
            errors.append("このURLはすでに登録されています。")
    return errors


def ensure_monitor_columns():
    inspector = inspect(db.engine)
    if "monitor" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("monitor")}
    dialect = db.engine.dialect.name
    bool_default_true = "TRUE" if dialect == "postgresql" else "1"
    bool_default_false = "FALSE" if dialect == "postgresql" else "0"
    add_column = "ADD COLUMN IF NOT EXISTS" if dialect == "postgresql" else "ADD COLUMN"
    migrations = [
        ("notification_email", f"ALTER TABLE monitor {add_column} notification_email VARCHAR(255)"),
        (
            "enable_discord",
            f"ALTER TABLE monitor {add_column} enable_discord BOOLEAN NOT NULL DEFAULT {bool_default_true}",
        ),
        (
            "enable_email",
            f"ALTER TABLE monitor {add_column} enable_email BOOLEAN NOT NULL DEFAULT {bool_default_false}",
        ),
        (
            "is_paused",
            f"ALTER TABLE monitor {add_column} is_paused BOOLEAN NOT NULL DEFAULT {bool_default_false}",
        ),
    ]

    for column, statement in migrations:
        if column not in existing_columns:
            try:
                db.session.execute(text(statement))
            except (OperationalError, ProgrammingError) as exc:
                db.session.rollback()
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise
    db.session.commit()


def ensure_check_result_columns():
    inspector = inspect(db.engine)
    if "check_result" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("check_result")}
    dialect = db.engine.dialect.name
    add_column = "ADD COLUMN IF NOT EXISTS" if dialect == "postgresql" else "ADD COLUMN"
    migrations = [
        ("failure_reason", f"ALTER TABLE check_result {add_column} failure_reason VARCHAR(120)"),
    ]

    for column, statement in migrations:
        if column not in existing_columns:
            try:
                db.session.execute(text(statement))
            except (OperationalError, ProgrammingError) as exc:
                db.session.rollback()
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise
    db.session.commit()


def uptime_percentage(monitor_id, since=None):
    query = CheckResult.query.filter_by(monitor_id=monitor_id)
    if since:
        query = query.filter(CheckResult.checked_at >= since)
    total = query.count()
    if total == 0:
        return None
    up = query.filter(CheckResult.status == "UP").count()
    return round((up / total) * 100, 2)


def latest_check_detail(latest, status):
    if not latest:
        return ""
    if status == "DOWN":
        return latest.failure_reason or "取得失敗"
    if latest.response_time_ms is not None:
        return f"{latest.response_time_ms} ms"
    return ""


def incident_report(monitor):
    incident = monitor.open_incident
    if incident:
        return (
            f"現在、{monitor.name}にアクセスしづらい状態を確認しています。\n"
            "原因を確認しており、状況が分かり次第あらためてご連絡いたします。\n\n"
            "現時点では原因を確認中です。\n"
            "サーバー・WordPress・プラグイン・ネットワークの可能性を含めて切り分けを行っています。"
        )

    latest_resolved = (
        Incident.query.filter(Incident.monitor_id == monitor.id, Incident.resolved_at.isnot(None))
        .order_by(Incident.resolved_at.desc())
        .first()
    )
    if latest_resolved:
        return (
            f"{monitor.name}の表示不具合は、{latest_resolved.resolved_at.strftime('%H:%M')} 時点で復旧していることを確認しました。\n"
            "ご不便をおかけし申し訳ありません。\n"
            "引き続き状況を確認いたします。"
        )
    return ""


def monitor_view_model(monitor):
    latest = monitor.latest_result
    status = "PAUSED" if monitor.is_paused else latest.status if latest else "CHECKING"
    notification_methods = []
    if monitor.enable_discord and monitor.discord_webhook:
        notification_methods.append("Discord")
    if monitor.enable_email and monitor.notification_email:
        notification_methods.append("メール")
    return {
        "monitor": monitor,
        "latest": latest,
        "status": status,
        "uptime": uptime_percentage(monitor.id),
        "uptime_30d": uptime_percentage(monitor.id, now_jst() - timedelta(days=30)),
        "notification_label": " / ".join(notification_methods) if notification_methods else "通知なし",
        "outage_report": (
            f"現在、{monitor.name}にアクセスしづらい状態を確認しています。\n"
            "原因を確認しており、状況が分かり次第あらためてご連絡いたします。\n\n"
            "現時点では原因を確認中です。\n"
            "サーバー・WordPress・プラグイン・ネットワークの可能性を含めて切り分けを行っています。"
        ),
    }


def dashboard_summary(items):
    response_times = [
        item["latest"].response_time_ms
        for item in items
        if item["latest"] and item["latest"].response_time_ms is not None
    ]
    average_response_time = None
    if response_times:
        average_response_time = round(sum(response_times) / len(response_times))

    return {
        "total": len(items),
        "up": sum(1 for item in items if item["status"] == "UP"),
        "down": sum(1 for item in items if item["status"] == "DOWN"),
        "average_response_time": average_response_time,
    }


@app.template_filter("jst")
def jst_filter(dt):
    if not dt:
        return "-"
    return dt.strftime("%Y年%m月%d日 %H:%M")


@app.route("/")
def index():
    monitors = Monitor.query.order_by(Monitor.created_at.desc()).all()
    items = [monitor_view_model(monitor) for monitor in monitors]
    return render_template("index.html", items=items, summary=dashboard_summary(items))


@app.route("/beta")
def beta_page():
    feedback_form_url = os.environ.get("GOOGLE_FORM_URL") or os.environ.get("FEEDBACK_FORM_URL")
    demo_status_slug = os.environ.get("DEMO_STATUS_SLUG")

    feedback_url = None
    feedback_label = "デモ監視リクエスト準備中"
    if feedback_form_url:
        feedback_url = feedback_form_url
        feedback_label = "監視したいURLを送る"

    demo_status_url = None
    if demo_status_slug:
        demo_status_url = url_for("status_page", page_slug=demo_status_slug)

    return render_template(
        "beta.html",
        feedback_url=feedback_url,
        feedback_label=feedback_label,
        demo_status_url=demo_status_url,
    )


@app.route("/add", methods=["GET", "POST"])
def add_monitor():
    if request.method == "POST":
        validate_csrf()
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        discord_webhook = request.form.get("discord_webhook", "").strip() or None
        notification_email = request.form.get("notification_email", "").strip() or None
        enable_discord = request.form.get("enable_discord") == "on"
        enable_email = request.form.get("enable_email") == "on"
        errors = validate_monitor_form(name, url)
        if notification_email and "@" not in notification_email:
            errors.append("通知用メールアドレスの形式を確認してください。")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "add.html",
                name=name,
                url=url,
                discord_webhook=discord_webhook,
                notification_email=notification_email,
                enable_discord=enable_discord,
                enable_email=enable_email,
            )

        monitor = Monitor(
            name=name,
            url=url,
            discord_webhook=discord_webhook,
            notification_email=notification_email,
            enable_discord=enable_discord,
            enable_email=enable_email,
            slug=unique_slug(name),
        )
        db.session.add(monitor)
        db.session.commit()
        flash("監視URLを追加しました。初回チェックはまもなく実行されます。", "success")
        return redirect(url_for("index"))

    return render_template("add.html")


@app.route("/edit/<int:monitor_id>", methods=["GET", "POST"])
def edit_monitor(monitor_id):
    monitor = Monitor.query.get_or_404(monitor_id)

    if request.method == "POST":
        validate_csrf()
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        discord_webhook = request.form.get("discord_webhook", "").strip() or None
        notification_email = request.form.get("notification_email", "").strip() or None
        enable_discord = request.form.get("enable_discord") == "on"
        enable_email = request.form.get("enable_email") == "on"
        errors = validate_monitor_form(name, url, current_monitor_id=monitor.id)
        if notification_email and "@" not in notification_email:
            errors.append("通知用メールアドレスの形式を確認してください。")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "edit.html",
                monitor=monitor,
                name=name,
                url=url,
                discord_webhook=discord_webhook,
                notification_email=notification_email,
                enable_discord=enable_discord,
                enable_email=enable_email,
            )

        monitor.name = name
        monitor.url = url
        monitor.discord_webhook = discord_webhook
        monitor.notification_email = notification_email
        monitor.enable_discord = enable_discord
        monitor.enable_email = enable_email
        db.session.commit()
        flash("監視設定を更新しました。", "success")
        return redirect(url_for("index"))

    return render_template(
        "edit.html",
        monitor=monitor,
        name=monitor.name,
        url=monitor.url,
        discord_webhook=monitor.discord_webhook,
        notification_email=monitor.notification_email,
        enable_discord=monitor.enable_discord,
        enable_email=monitor.enable_email,
    )


@app.route("/toggle/<int:monitor_id>", methods=["POST"])
def toggle_monitor(monitor_id):
    validate_csrf()
    monitor = Monitor.query.get_or_404(monitor_id)
    monitor.is_paused = not monitor.is_paused
    db.session.commit()
    flash("監視を再開しました。" if not monitor.is_paused else "監視を一時停止しました。", "success")
    return redirect(url_for("index"))


@app.route("/delete/<int:monitor_id>", methods=["POST"])
def delete_monitor(monitor_id):
    validate_csrf()
    monitor = Monitor.query.get_or_404(monitor_id)
    db.session.delete(monitor)
    db.session.commit()
    flash("監視URLを削除しました。", "success")
    return redirect(url_for("index"))


@app.route("/status/<page_slug>")
def status_page(page_slug):
    monitor = Monitor.query.filter_by(slug=page_slug).first_or_404()
    latest = monitor.latest_result
    status = "PAUSED" if monitor.is_paused else latest.status if latest else "CHECKING"
    incidents = Incident.query.filter_by(monitor_id=monitor.id).order_by(Incident.started_at.desc()).all()
    return render_template(
        "status.html",
        monitor=monitor,
        latest=latest,
        status=status,
        uptime_30d=uptime_percentage(monitor.id, now_jst() - timedelta(days=30)),
        incidents=incidents,
        report_text="" if monitor.is_paused else incident_report(monitor),
        latest_check_detail=latest_check_detail(latest, status),
    )


def should_start_scheduler():
    if not env_enabled("SCHEDULER_ENABLED", default=True):
        return False
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


with app.app_context():
    db.create_all()
    ensure_monitor_columns()
    ensure_check_result_columns()


scheduler = None
if should_start_scheduler():
    scheduler = start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=DEBUG)
