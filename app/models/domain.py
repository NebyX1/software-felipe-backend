"""Business entities. Binary originals live in S3; decimals never become floats."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from ..extensions import db


def now():
    return datetime.now(timezone.utc)


class Entity:
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    def to_dict(self):
        result = {}
        for col in self.__table__.columns:
            if col.name in ('storage_key', 'jti', 'password_hash'):
                continue
            value = getattr(self, self.__mapper__.get_property_by_column(col).key)
            result[col.name] = str(value) if isinstance(value, Decimal) else value.isoformat() if hasattr(value, 'isoformat') else value
        return result


class DemoInstallation(Entity, db.Model):
    __tablename__ = 'demo_installations'
    seed_version = db.Column(db.String(40), unique=True, nullable=False)
    state = db.Column(db.String(20), nullable=False)


class Company(Entity, db.Model):
    __tablename__ = 'companies'
    name = db.Column(db.String(200), nullable=False)
    rut = db.Column(db.String(40), unique=True, nullable=False)
    status = db.Column(db.String(40), default='activa', nullable=False)
    contact = db.Column(db.JSON, default=dict, nullable=False)
    demo = db.Column(db.Boolean, default=False, nullable=False)


class Professional(Entity, db.Model):
    __tablename__ = 'professionals'
    name = db.Column(db.String(200), nullable=False)
    registration = db.Column(db.String(100), unique=True, nullable=False)
    contact = db.Column(db.JSON, default=dict, nullable=False)
    source = db.Column(db.String(250))


class Intervention(Entity, db.Model):
    __tablename__ = 'interventions'
    code = db.Column(db.String(50), unique=True, nullable=False, default=lambda: 'OB-'+uuid4().hex[:10].upper())
    name = db.Column(db.String(220), nullable=False)
    description = db.Column(db.Text, default='', nullable=False)
    locality = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(250), default='')
    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))
    intervention_type = db.Column(db.String(100), default='Edificación')
    objective = db.Column(db.String(200), default='')
    surface = db.Column(db.Numeric(20, 4), default=0, nullable=False)
    budget = db.Column(db.Numeric(24, 2), default=0, nullable=False)
    funding = db.Column(db.JSON, default=list, nullable=False)
    stage = db.Column(db.String(30), default='proyecto', nullable=False)
    status = db.Column(db.String(40), default='planificada', nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    cover_id = db.Column(db.Integer)
    public = db.Column(db.Boolean, default=False, nullable=False)
    demo = db.Column(db.Boolean, default=False, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)


class Assignment(Entity, db.Model):
    __tablename__ = 'assignments'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'))
    role = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.JSON, default=dict, nullable=False)
    __table_args__ = (db.UniqueConstraint('work_id', 'user_id', name='uq_assignment_user'),)


class Contract(Entity, db.Model):
    __tablename__ = 'contracts'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(30), default='inicial', nullable=False)
    status = db.Column(db.String(30), default='borrador', nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    number = db.Column(db.String(100), default='')
    tender_number = db.Column(db.String(100), default='')
    dossier_number = db.Column(db.String(100), default='')
    procurement_type = db.Column(db.String(100), default='licitación')
    bps_number = db.Column(db.String(100), default='')
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    amount = db.Column(db.Numeric(24, 2), default=0, nullable=False)
    rules = db.Column(db.JSON, default=dict, nullable=False)
    reason = db.Column(db.Text, default='')
    __table_args__ = (db.UniqueConstraint('work_id', 'version', name='uq_contract_version'),)


class BudgetLine(Entity, db.Model):
    __tablename__ = 'budget_lines'
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False, index=True)
    code = db.Column(db.String(100), nullable=False)
    chapter = db.Column(db.String(200), default='General', nullable=False)
    description = db.Column(db.Text, nullable=False)
    unit = db.Column(db.String(40), nullable=False)
    quantity = db.Column(db.Numeric(24, 8), nullable=False)
    unit_price = db.Column(db.Numeric(24, 8), nullable=False)
    social_rate = db.Column(db.Numeric(14, 8), default=0, nullable=False)
    kind = db.Column(db.String(30), default='basico', nullable=False)
    icc_eligible = db.Column(db.Boolean, default=True, nullable=False)
    __table_args__ = (db.UniqueConstraint('contract_id', 'code', name='uq_budget_code'),)


class Schedule(Entity, db.Model):
    __tablename__ = 'schedules'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), default='borrador', nullable=False)
    activities = db.Column(db.JSON, default=list, nullable=False)
    reason = db.Column(db.Text, default='')
    __table_args__ = (db.UniqueConstraint('work_id', 'version', name='uq_schedule_version'),)


class Record(Entity, db.Model):
    """Versioned operational records; each kind has its own service transitions."""
    __tablename__ = 'work_records'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(250), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    due_date = db.Column(db.Date)
    date = db.Column(db.Date)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    data = db.Column(db.JSON, default=dict, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)


class Document(Entity, db.Model):
    __tablename__ = 'documents'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    group_id = db.Column(db.String(36), default=lambda: str(uuid4()), nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    name = db.Column(db.String(250), nullable=False)
    kind = db.Column(db.String(60), default='documento', nullable=False)
    stage = db.Column(db.String(30), nullable=False)
    classification = db.Column(db.String(30), default='interno', nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    record_id = db.Column(db.Integer, db.ForeignKey('work_records.id'))
    storage_key = db.Column(db.String(160), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    mime = db.Column(db.String(160), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    pages = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(40), default='cargado', nullable=False)
    ingestion = db.Column(db.String(30), default='pendiente', nullable=False)
    ingestion_error = db.Column(db.String(250))
    __table_args__ = (db.UniqueConstraint('group_id', 'version', name='uq_document_version'),)


class Annotation(Entity, db.Model):
    __tablename__ = 'annotations'
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    page = db.Column(db.Integer, nullable=False)
    x = db.Column(db.Numeric(10, 6), nullable=False)
    y = db.Column(db.Numeric(10, 6), nullable=False)
    text = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class Certificate(Entity, db.Model):
    __tablename__ = 'certificates'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)
    period = db.Column(db.String(7), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(40), default='borrador', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    revision = db.Column(db.Integer, default=1, nullable=False)
    input = db.Column(db.JSON, nullable=False)
    calculation = db.Column(db.JSON, nullable=False)
    approved_snapshot = db.Column(db.JSON)
    invoice_id = db.Column(db.Integer, db.ForeignKey('documents.id'))
    invoice_number = db.Column(db.String(100))
    certificate_document_id = db.Column(db.Integer, db.ForeignKey('documents.id'))
    payment_document_id = db.Column(db.Integer, db.ForeignKey('documents.id'))
    initial_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    final_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    idempotency_key = db.Column(db.String(100), unique=True, nullable=False)
    __table_args__ = (db.UniqueConstraint('work_id', 'period', name='uq_certificate_period'),)


class CertificateRevision(Entity, db.Model):
    __tablename__ = 'certificate_revisions'
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('certificate_id', 'revision', name='uq_certificate_revision'),)


class Rectification(Entity, db.Model):
    __tablename__ = 'rectifications'
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), nullable=False)
    status = db.Column(db.String(30), default='solicitada', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))


class Payment(Entity, db.Model):
    __tablename__ = 'payments'
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), unique=True, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(40), default='expediente', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    amount = db.Column(db.Numeric(24, 2), nullable=False)
    confirmation = db.Column(db.JSON)
    demo = db.Column(db.Boolean, default=True, nullable=False)


class PaymentAttempt(Entity, db.Model):
    __tablename__ = 'payment_attempts'
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, index=True)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(30), default='pendiente', nullable=False)
    amount = db.Column(db.Numeric(24, 2), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    payment_version = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    resolved_at = db.Column(db.DateTime)
    reason = db.Column(db.String(250), default='', nullable=False)
    receipt_id = db.Column(db.Integer, db.ForeignKey('documents.id'))


class CheckoutSession(Entity, db.Model):
    __tablename__ = 'checkout_sessions'
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    payment_version = db.Column(db.Integer, nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    amount = db.Column(db.Numeric(24, 2), nullable=False)
    status = db.Column(db.String(30), default='created', nullable=False)
    account = db.Column(db.String(40))
    process_after = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempt_id = db.Column(db.Integer, db.ForeignKey('payment_attempts.id'), unique=True)
    result_code = db.Column(db.String(50))
    result_message = db.Column(db.String(250))
    closing_balance = db.Column(db.Numeric(24, 2))


class DemoPaymentRun(Entity, db.Model):
    """Isolated, resumable presentation using the normal certificate/payment services."""
    __tablename__ = 'demo_payment_runs'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), unique=True, nullable=False)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    idempotency_key = db.Column(db.String(100), unique=True, nullable=False)
    step = db.Column(db.String(40), default='presentar', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    events = db.Column(db.JSON, default=list, nullable=False)


class Procedure(Entity, db.Model):
    __tablename__ = 'procedures'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    title = db.Column(db.String(250), nullable=False)
    kind = db.Column(db.String(60), default='revision_documental', nullable=False)
    status = db.Column(db.String(30), default='borrador', nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'))
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'))
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    due_date = db.Column(db.Date)
    data = db.Column(db.JSON, default=dict, nullable=False)


class Notification(Entity, db.Model):
    __tablename__ = 'notifications'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False)
    event_key = db.Column(db.String(140), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    resource = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.Integer, nullable=False)
    read_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('user_id', 'event_key', name='uq_notification_event'),)


class CompanyRepresentative(Entity, db.Model):
    __tablename__ = 'company_representatives'
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    status = db.Column(db.String(30), default='pendiente', nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    validated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    evidence_id = db.Column(db.Integer, db.ForeignKey('company_documents.id'))


class CompanyDocument(Entity, db.Model):
    __tablename__ = 'company_documents'
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    group_id = db.Column(db.String(36), default=lambda: str(uuid4()), nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    name = db.Column(db.String(250), nullable=False)
    kind = db.Column(db.String(60), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    storage_key = db.Column(db.String(160), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    mime = db.Column(db.String(160), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='cargado', nullable=False)
    __table_args__ = (db.UniqueConstraint('group_id', 'version', name='uq_company_document_version'),)


class History(Entity, db.Model):
    __tablename__ = 'business_history'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False, index=True)
    resource = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    previous = db.Column(db.String(40))
    target = db.Column(db.String(40))
    details = db.Column(db.JSON, default=dict, nullable=False)


class AuthSession(Entity, db.Model):
    __tablename__ = 'auth_sessions'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    jti = db.Column(db.String(64), unique=True, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)


class Chunk(Entity, db.Model):
    __tablename__ = 'document_chunks'
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False, index=True)
    page = db.Column(db.Integer, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)


class ChatTurn(Entity, db.Model):
    __tablename__ = 'chat_turns'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(30), default='pendiente', nullable=False)
    question = db.Column('query',db.Text, nullable=False)
    answer = db.Column(db.Text)
    sources = db.Column(db.JSON, default=list, nullable=False)
    error_code = db.Column(db.String(60))


class ImportBatch(Entity, db.Model):
    __tablename__ = 'import_batches'
    work_id = db.Column(db.Integer, db.ForeignKey('interventions.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'))
    kind = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(30), default='previsualizacion', nullable=False)
    preview = db.Column(db.JSON, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)


class CatalogEntry(Entity, db.Model):
    __tablename__ = 'catalog_entries'
    kind = db.Column(db.String(40), nullable=False)
    code = db.Column(db.String(120), nullable=False)
    label = db.Column(db.String(250), nullable=False)
    data = db.Column(db.JSON, default=dict, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    __table_args__ = (db.UniqueConstraint('kind', 'code', name='uq_catalog_code'),)
