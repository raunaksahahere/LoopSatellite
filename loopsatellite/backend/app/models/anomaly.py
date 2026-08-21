from datetime import date as Date
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy import Date as SADate
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Anomaly(Base):
    """A water-loss event flagged by the statistics — never by an LLM.

    Produced by Seasonal-Hybrid ESD over the STL residual of the pond's water-area
    series (see data_pipeline/05_stl_esd_flagging.py). `confidence` is a
    deterministic score derived from residual magnitude, persistence and
    non-recovery — not a model output.
    """

    __tablename__ = "anomaly"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pond_id: Mapped[str] = mapped_column(
        ForeignKey("pond.id", ondelete="CASCADE"), index=True
    )
    window_start: Mapped[Date] = mapped_column(SADate)
    window_end: Mapped[Date] = mapped_column(SADate)
    detected_on: Mapped[Date] = mapped_column(SADate, index=True)

    confidence: Mapped[float] = mapped_column(Float)  # 0..1, deterministic
    confidence_band: Mapped[str] = mapped_column(String(16))  # high | medium | low
    loss_pct: Mapped[float] = mapped_column(Float)  # % below seasonal expectation
    baseline_area_m2: Mapped[float | None] = mapped_column(Float)
    observed_area_m2: Mapped[float | None] = mapped_column(Float)
    residual_z: Mapped[float | None] = mapped_column(Float)  # STL residual z-score
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    conversion_signal: Mapped[str | None] = mapped_column(String(32))  # built_up | bare | none
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    pond: Mapped["Pond"] = relationship(back_populates="anomalies")  # noqa: F821
    verifications: Mapped[list["Verification"]] = relationship(  # noqa: F821
        back_populates="anomaly", cascade="all, delete-orphan"
    )
