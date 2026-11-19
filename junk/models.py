"""Junk removal data model.

A job's state is derived, never stored (see Job.state), so it can't disagree with its fields.
Every change writes a JobEvent. Deleting a job deletes it (and its history) for good.
"""
from datetime import datetime

from models import db


class Job(db.Model):
    __tablename__ = 'junk_job'

    id = db.Column(db.Integer, primary_key=True)

    # Customer details live on the job. Every field is optional: jobs don't always
    # follow the call → quote → schedule flow in order.
    customer_name = db.Column(db.String(120), nullable=True)
    customer_phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    # Set only when the address was picked from Google Places; typing by hand clears them.
    address_lat = db.Column(db.Float, nullable=True)
    address_lng = db.Column(db.Float, nullable=True)
    quote_amount = db.Column(db.Numeric(10, 2), nullable=True)  # NULL = "Needs quote"
    notes = db.Column(db.Text, nullable=True)

    # Scheduling: a day is an ordered line, not time slots.
    scheduled_date = db.Column(db.Date, nullable=True)       # Eastern calendar date; NULL = Unscheduled
    queue_position = db.Column(db.Integer, nullable=True)    # 1..n within its day, or within Unscheduled

    completed_at = db.Column(db.DateTime, nullable=True)     # UTC
    completed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = db.relationship('JobEvent', backref='job', lazy='dynamic',
                             order_by='JobEvent.id.desc()')
    assignments = db.relationship('JobAssignment', backref='job', lazy='select',
                                  order_by='JobAssignment.id', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('ix_junk_job_day_queue', 'scheduled_date', 'queue_position'),
    )

    @property
    def state(self):
        """'done' | 'scheduled' | 'unscheduled' — evaluated in that order."""
        if self.completed_at:
            return 'done'
        if self.scheduled_date:
            return 'scheduled'
        return 'unscheduled'

    @property
    def crew(self):
        """People on this job, in the order they were added."""
        return [a.user for a in self.assignments]

    @property
    def display_name(self):
        return self.customer_name or 'Untitled job'

    @property
    def needs_quote(self):
        return self.quote_amount is None


class JobEvent(db.Model):
    """Append-only change history for a Job. Never edited; deleted only along with its job."""
    __tablename__ = 'junk_job_event'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('junk_job.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # created | updated | done | undone
    action = db.Column(db.String(20), nullable=False)
    changes = db.Column(db.JSON, nullable=False, default=dict)  # {field: [old, new]}

    user = db.relationship('User', foreign_keys=[user_id])


class JobAssignment(db.Model):
    """One person on one job. Crew and managers can both be assigned (managers work jobs too).
    Pay is 20% of the job total per person assigned (computed later, never stored here)."""
    __tablename__ = 'junk_job_assignment'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('junk_job.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (db.UniqueConstraint('job_id', 'user_id', name='uq_junk_job_assignment'),)


def person_name(user):
    return (user.full_name or user.email or '').strip()


def initials(user):
    """HR for Henry Russell; MD for "Manager (dev)"; JO for jordan@…; one letter for a one-word name.
    Only letters and digits count, so punctuation never becomes an initial."""
    import re
    parts = re.findall(r'[^\W_]+', user.full_name or '')
    if parts:
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper()
    return (re.sub(r'[^\w]', '', (user.email or '').split('@')[0])[:2] or '?').upper()
