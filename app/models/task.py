from datetime import datetime, timezone
from ..extensions import db

TASK_STATUSES = ('todo', 'in_progress', 'review', 'done')
TASK_PRIORITIES = ('low', 'medium', 'high', 'urgent')


class Task(db.Model):
    """Task / action item belonging to a project."""

    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.Enum(*TASK_STATUSES, name='task_status'),
        default='todo',
        nullable=False,
    )
    priority = db.Column(
        db.Enum(*TASK_PRIORITIES, name='task_priority'),
        default='medium',
        nullable=False,
    )
    responsible = db.Column(db.String(150), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = db.relationship('Project', back_populates='tasks', lazy='joined')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'responsible': self.responsible,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f'<Task {self.title!r} status={self.status}>'
