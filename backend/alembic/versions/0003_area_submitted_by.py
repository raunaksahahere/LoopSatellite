"""record which signed-in user submitted an area, so the Earth Engine cap can count

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

`requested_by` already existed, but it is a display name the client typed into
the request body — unverified, editable, and useless as a key to count against.
`submitted_by` is the Clerk user id off the token. Nullable because every row
written before Clerk has no id to backfill with, and inventing one would be worse
than an honest null.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("area", sa.Column("submitted_by", sa.String(255), nullable=True))
    # The quota query is "this user, last 24 hours", so the index carries both.
    op.create_index(
        "ix_area_submitted_by_created_at", "area", ["submitted_by", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_area_submitted_by_created_at", table_name="area")
    op.drop_column("area", "submitted_by")
