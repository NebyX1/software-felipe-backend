"""Persist first-install initialization without reseeding operator changes."""
from alembic import op
import sqlalchemy as sa

revision = 'd42f81b670ce'
down_revision = 'c18a903be442'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('demo_installations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('seed_version', sa.String(40), unique=True, nullable=False),
        sa.Column('state', sa.String(20), nullable=False))


def downgrade():
    op.drop_table('demo_installations')
