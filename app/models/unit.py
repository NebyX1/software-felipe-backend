from datetime import datetime, timezone
from ..extensions import db


class Unit(db.Model):
    """Organizational unit / area / department / directorate."""

    __tablename__ = 'units'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    color = db.Column(db.String(20), default='#6366f1', nullable=False)
    emoji = db.Column(db.String(16), default='🏛️', nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    users = db.relationship('User', back_populates='unit', lazy='dynamic')
    projects = db.relationship(
        'Project', back_populates='unit', cascade='all, delete-orphan', lazy='dynamic'
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'color': self.color,
            'emoji': self.emoji,
            'created_at': self.created_at.isoformat(),
            'project_count': self.projects.filter_by(is_active=True).count(),
            'user_count': self.users.filter_by(is_active=True).count(),
        }

    def __repr__(self) -> str:
        return f'<Unit {self.name}>'
