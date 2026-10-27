"""Hosted sandbox checkout sessions.

Revision ID: c18a903be442
Revises: b89103fa124e
"""
from alembic import op
import sqlalchemy as sa

revision = 'c18a903be442'
down_revision = 'b89103fa124e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('checkout_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('public_id', sa.String(36), unique=True, nullable=False),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('payment_version', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('amount', sa.Numeric(24, 2), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('account', sa.String(40)),
        sa.Column('process_after', sa.DateTime()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempt_id', sa.Integer(), sa.ForeignKey('payment_attempts.id'), unique=True),
        sa.Column('result_code', sa.String(50)),
        sa.Column('result_message', sa.String(250)),
        sa.Column('closing_balance', sa.Numeric(24, 2)),
    )
    op.create_index('ix_checkout_sessions_payment_id', 'checkout_sessions', ['payment_id'])


def downgrade():
    op.drop_table('checkout_sessions')
