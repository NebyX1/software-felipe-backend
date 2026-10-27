from datetime import datetime, timezone, timedelta
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import (
    VerifyMismatchError,
    InvalidHashError,
    VerificationError,
)
from werkzeug.security import check_password_hash
from flask_login import UserMixin
from ..extensions import db

_ph = PasswordHasher()

USER_ROLES = ('super_admin', 'admin', 'user', 'direccion_general', 'director_obra', 'tecnico', 'inspector', 'administrativo', 'consulta', 'empresa')


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(40),
        nullable=False,
        default='user',
    )
    # For 'user' role: which organizational unit they belong to
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey('units.id', ondelete='SET NULL'),
        nullable=True,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)
    demo = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    unit = db.relationship('Unit', back_populates='users', lazy='joined')
    two_factor_codes = db.relationship(
        'TwoFactorCode', back_populates='user', cascade='all, delete-orphan'
    )
    activity_logs = db.relationship(
        'ActivityLog', back_populates='user', cascade='all, delete-orphan'
    )
    created_projects = db.relationship(
        'Project', back_populates='creator', foreign_keys='Project.created_by'
    )

    def set_password(self, raw: str) -> None:
        self.password_hash = _ph.hash(raw)

    def check_password(self, raw: str) -> bool:
        try:
            return _ph.verify(self.password_hash, raw)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            # Backward compatibility for legacy hashes (e.g. Werkzeug/PBKDF2).
            try:
                if check_password_hash(self.password_hash, raw):
                    # Upgrade to Argon2 on successful login.
                    self.set_password(raw)
                    return True
            except Exception:
                return False
            return False
        except Exception:
            return False

    @property
    def is_admin(self) -> bool:
        return self.role in ('admin', 'super_admin')

    @property
    def is_super_admin(self) -> bool:
        return self.role == 'super_admin'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'company_id': self.company_id,
            'demo': self.demo,
            'unit_id': self.unit_id,
            'unit_name': self.unit.name if self.unit else None,
            'unit_color': self.unit.color if self.unit else None,
            'unit_emoji': self.unit.emoji if self.unit else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }

    def __repr__(self) -> str:
        return f'<User {self.email} role={self.role}>'


class TwoFactorCode(db.Model):
    __tablename__ = 'two_factor_codes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False
    )
    # DB stores a bcrypt/argon2 hash of the code
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    # consumed_at is NULL when not yet used
    consumed_at = db.Column(db.DateTime, nullable=True, default=None)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user = db.relationship('User', back_populates='two_factor_codes')

    # ── virtual property so auth.py can keep using .used / .used = True ──────
    @property
    def used(self) -> bool:
        return self.consumed_at is not None

    @used.setter
    def used(self, value: bool) -> None:
        if value:
            self.consumed_at = datetime.now(timezone.utc)
        else:
            self.consumed_at = None

    @staticmethod
    def generate(user: 'User') -> 'TwoFactorCode':
        raw_code = str(secrets.randbelow(900000) + 100000)  # 100000–999999
        entry = TwoFactorCode(
            user_id=user.id,
            code_hash=_ph.hash(raw_code),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.session.add(entry)
        # Attach plain code so auth.py / email service can read it before flush
        entry._plain_code = raw_code
        return entry

    @property
    def code(self) -> str:
        """Return plain code only right after generate(), before commit."""
        return getattr(self, '_plain_code', '')

    def is_valid(self, submitted: str) -> bool:
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if self.used or now > exp:
            return False
        try:
            return _ph.verify(self.code_hash, submitted.strip())
        except Exception:
            return False

    def __repr__(self) -> str:
        return f'<TwoFactorCode user={self.user_id} used={self.used}>'


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    username = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    timestamp = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user = db.relationship('User', back_populates='activity_logs')

    def to_dict(self) -> dict:
        import json as _json
        parsed: dict = {}
        if self.details:
            try:
                parsed = _json.loads(self.details)
            except (ValueError, TypeError):
                pass
        entity_type = parsed.pop('entity_type', None)
        entity_id = parsed.pop('entity_id', None)
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.name if self.user else (self.username or 'Sistema'),
            'user_email': self.user.email if self.user else None,
            'action': self.action,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': parsed if parsed else None,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat(),
            'created_at': self.timestamp.isoformat(),
        }

    def __repr__(self) -> str:
        return f'<ActivityLog {self.action} user={self.user_id}>'

