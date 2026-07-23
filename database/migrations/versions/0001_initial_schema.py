"""Initial Swarm AI QA relational schema.

Revision ID: 0001_initial_schema
Revises: None
"""

from alembic import op

from database.models import metadata


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial hackathon snapshot. Future schema changes must use new revisions.
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
