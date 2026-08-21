"""initial schema: pond, observation, anomaly, verification

Revision ID: 0001
Revises:
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pond",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("ward", sa.String(64)),
        sa.Column("mouza", sa.String(255)),
        sa.Column("geojson", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("centroid_lon", sa.Float()),
        sa.Column("centroid_lat", sa.Float()),
        sa.Column("baseline_area_m2", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pond_ward", "pond", ["ward"])
    op.create_index("ix_pond_mouza", "pond", ["mouza"])

    op.create_table(
        "observation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pond_id", sa.String(64), sa.ForeignKey("pond.id", ondelete="CASCADE")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("mndwi_value", sa.Float()),
        sa.Column("water_area_m2", sa.Float()),
        sa.Column("pixel_count", sa.Integer()),
        sa.Column("quality_weight", sa.Float(), server_default="1.0"),
        sa.Column("source", sa.String(32), server_default="S2"),
        sa.UniqueConstraint("pond_id", "date", "source", name="uq_obs_pond_date_src"),
    )
    op.create_index("ix_observation_pond_id", "observation", ["pond_id"])
    op.create_index("ix_observation_date", "observation", ["date"])

    op.create_table(
        "anomaly",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("pond_id", sa.String(64), sa.ForeignKey("pond.id", ondelete="CASCADE")),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("detected_on", sa.Date(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_band", sa.String(16), nullable=False),
        sa.Column("loss_pct", sa.Float(), nullable=False),
        sa.Column("baseline_area_m2", sa.Float()),
        sa.Column("observed_area_m2", sa.Float()),
        sa.Column("residual_z", sa.Float()),
        sa.Column("recovered", sa.Boolean(), server_default=sa.false()),
        sa.Column("conversion_signal", sa.String(32)),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_anomaly_pond_id", "anomaly", ["pond_id"])
    op.create_index("ix_anomaly_detected_on", "anomaly", ["detected_on"])
    op.create_index("ix_anomaly_status", "anomaly", ["status"])

    op.create_table(
        "verification",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("anomaly_id", sa.String(64), sa.ForeignKey("anomaly.id", ondelete="CASCADE")),
        sa.Column("officer_note", sa.Text()),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("officer_name", sa.String(255)),
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_verification_anomaly_id", "verification", ["anomaly_id"])


def downgrade() -> None:
    op.drop_table("verification")
    op.drop_table("anomaly")
    op.drop_table("observation")
    op.drop_table("pond")
