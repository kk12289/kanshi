from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy


JST = ZoneInfo("Asia/Tokyo")
db = SQLAlchemy()


def now_jst():
    return datetime.now(JST)


class Monitor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(500), nullable=False, unique=True, index=True)
    discord_webhook = db.Column(db.String(1000), nullable=True)
    notification_email = db.Column(db.String(255), nullable=True)
    enable_discord = db.Column(db.Boolean, default=True, nullable=False)
    enable_email = db.Column(db.Boolean, default=False, nullable=False)
    is_paused = db.Column(db.Boolean, default=False, nullable=False)
    slug = db.Column(db.String(180), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_jst, nullable=False)

    check_results = db.relationship(
        "CheckResult",
        backref="monitor",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="desc(CheckResult.checked_at)",
    )
    incidents = db.relationship(
        "Incident",
        backref="monitor",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="desc(Incident.started_at)",
    )

    @property
    def latest_result(self):
        return CheckResult.query.filter_by(monitor_id=self.id).order_by(CheckResult.checked_at.desc()).first()

    @property
    def open_incident(self):
        return (
            Incident.query.filter_by(monitor_id=self.id, resolved_at=None)
            .order_by(Incident.started_at.desc())
            .first()
        )


class CheckResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monitor_id = db.Column(db.Integer, db.ForeignKey("monitor.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    response_time_ms = db.Column(db.Integer, nullable=True)
    failure_reason = db.Column(db.String(120), nullable=True)
    checked_at = db.Column(db.DateTime(timezone=True), default=now_jst, nullable=False, index=True)


class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monitor_id = db.Column(db.Integer, db.ForeignKey("monitor.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
