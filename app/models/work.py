from datetime import datetime, timezone
from ..extensions import db

WORK_STATUSES = ('planning', 'in_progress', 'paused', 'completed', 'cancelled')
WORK_DOC_KINDS = ('task_attachment', 'start', 'completion', 'other')
WORK_TASK_STATUSES = (
    'todo',
    'in_progress',
    'review',
    'blocked',
    'done',
)
WORK_TASK_PRIORITIES = ('low', 'medium', 'high', 'critical')


class Work(db.Model):
    __tablename__ = 'works'

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey('units.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(220), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.Enum(*WORK_STATUSES, name='work_status'),
        default='planning',
        nullable=False,
    )
    progress = db.Column(db.Integer, default=0, nullable=False)
    location = db.Column(db.String(220), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    budget = db.Column(db.Numeric(12, 2), nullable=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    unit = db.relationship('Unit', lazy='joined')
    creator = db.relationship('User', lazy='joined')
    tasks = db.relationship(
        'WorkTask',
        back_populates='work',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )
    documents = db.relationship(
        'WorkDocument',
        back_populates='work',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'unit_id': self.unit_id,
            'unit_name': self.unit.name if self.unit else None,
            'unit_color': self.unit.color if self.unit else None,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'progress': self.progress,
            'location': self.location,
            'start_date': (
                self.start_date.isoformat() if self.start_date else None
            ),
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'budget': float(self.budget) if self.budget is not None else None,
            'created_by': self.created_by,
            'creator_name': self.creator.name if self.creator else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'tasks_count': self.tasks.count(),
            'done_tasks_count': self.tasks.filter_by(status='done').count(),
            'documents_count': self.documents.count(),
        }


class WorkDocument(db.Model):
    __tablename__ = 'work_documents'

    id = db.Column(db.Integer, primary_key=True)
    work_id = db.Column(
        db.Integer,
        db.ForeignKey('works.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    kind = db.Column(
        db.Enum(*WORK_DOC_KINDS, name='work_doc_kind'),
        default='other',
        nullable=False,
    )
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    uploaded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    work = db.relationship('Work', back_populates='documents', lazy='joined')
    uploader = db.relationship('User', lazy='joined')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'work_id': self.work_id,
            'kind': self.kind,
            'original_name': self.original_name,
            'mime_type': self.mime_type,
            'size_bytes': self.size_bytes,
            'uploaded_by': self.uploaded_by,
            'uploaded_by_name': self.uploader.name if self.uploader else None,
            'uploaded_at': self.uploaded_at.isoformat(),
            'download_url': f'/api/works/{self.work_id}/documents/{self.id}',
        }


class WorkTask(db.Model):
    __tablename__ = 'work_tasks'

    id = db.Column(db.Integer, primary_key=True)
    work_id = db.Column(
        db.Integer,
        db.ForeignKey('works.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(220), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.Enum(*WORK_TASK_STATUSES, name='work_task_status'),
        default='todo',
        nullable=False,
    )
    priority = db.Column(
        db.Enum(*WORK_TASK_PRIORITIES, name='work_task_priority'),
        default='medium',
        nullable=False,
    )
    responsible = db.Column(db.String(120), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    progress = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    work = db.relationship('Work', back_populates='tasks', lazy='joined')
    documents = db.relationship(
        'WorkTaskDocument',
        back_populates='task',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'work_id': self.work_id,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'responsible': self.responsible,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'progress': self.progress,
            'documents_count': self.documents.count(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class WorkTaskDocument(db.Model):
    __tablename__ = 'work_task_documents'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey('work_tasks.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    kind = db.Column(
        db.Enum(*WORK_DOC_KINDS, name='work_task_doc_kind'),
        default='task_attachment',
        nullable=False,
    )
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    uploaded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    task = db.relationship(
        'WorkTask',
        back_populates='documents',
        lazy='joined',
    )
    uploader = db.relationship('User', lazy='joined')

    def to_dict(self) -> dict:
        work_id = self.task.work_id if self.task else None
        task_id = self.task_id
        return {
            'id': self.id,
            'task_id': task_id,
            'work_id': work_id,
            'kind': self.kind,
            'original_name': self.original_name,
            'mime_type': self.mime_type,
            'size_bytes': self.size_bytes,
            'uploaded_by': self.uploaded_by,
            'uploaded_by_name': self.uploader.name if self.uploader else None,
            'uploaded_at': self.uploaded_at.isoformat(),
            'download_url': (
                f'/api/works/{work_id}/tasks/{task_id}/documents/{self.id}'
                if work_id is not None
                else None
            ),
        }
