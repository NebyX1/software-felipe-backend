"""Persist isolated guided payment presentations.

Revision ID: b89103fa124e
Revises: 7c30aef721f5
"""
from alembic import op
import sqlalchemy as sa

revision = 'b89103fa124e'
down_revision = '7c30aef721f5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('demo_payment_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('work_id', sa.Integer(), sa.ForeignKey('interventions.id'), nullable=False, unique=True),
        sa.Column('certificate_id', sa.Integer(), sa.ForeignKey('certificates.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=False, unique=True),
        sa.Column('step', sa.String(40), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('events', sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table('demo_payment_runs')
