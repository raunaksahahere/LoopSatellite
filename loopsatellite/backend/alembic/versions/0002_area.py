"""areas submitted at runtime (the slow path)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "area",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("center_lat", sa.Float(), nullable=False),
        sa.Column("center_lon", sa.Float(), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=False),
        sa.Column("geojson", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("progress", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("pond_count", sa.Integer(), server_default="0"),
        sa.Column("anomaly_count", sa.Integer(), server_default="0"),
        sa.Column("requested_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_area_status", "area", ["status"])


def downgrade() -> None:
    op.drop_table("area")
