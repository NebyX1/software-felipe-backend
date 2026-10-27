from datetime import datetime, timezone
from ..extensions import db


class Project(db.Model):
    """Project / initiative belonging to an organizational unit."""

    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey('units.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
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
    unit = db.relationship('Unit', back_populates='projects', lazy='joined')
    creator = db.relationship(
        'User', back_populates='created_projects', foreign_keys=[created_by], lazy='joined'
    )
    tasks = db.relationship(
        'Task', back_populates='project', cascade='all, delete-orphan', lazy='dynamic'
    )

    def to_dict(self, include_task_count: bool = True) -> dict:
        d = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'unit_id': self.unit_id,
            'unit_name': self.unit.name if self.unit else None,
            'unit_color': self.unit.color if self.unit else None,
            'created_by': self.created_by,
            'creator_name': self.creator.name if self.creator else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
        if include_task_count:
            d['task_count'] = self.tasks.count()
        return d

    def __repr__(self) -> str:
        return f'<Project {self.name} unit={self.unit_id}>'
