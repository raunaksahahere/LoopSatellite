from datetime import date as Date

from sqlalchemy import Date as SADate
from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Observation(Base):
    """One satellite pass over one pond.

    `mndwi_value` is the pond-mean MNDWI; `water_area_m2` is the thresholded
    water surface area (MNDWI >= 0.1), which is what the statistics actually run on.
    `quality_weight` in [0, 1] downweights cloudy / partially masked passes.
    """

    __tablename__ = "observation"
    __table_args__ = (UniqueConstraint("pond_id", "date", "source", name="uq_obs_pond_date_src"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pond_id: Mapped[str] = mapped_column(
        ForeignKey("pond.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[Date] = mapped_column(SADate, index=True)
    mndwi_value: Mapped[float | None] = mapped_column(Float)
    water_area_m2: Mapped[float | None] = mapped_column(Float)
    pixel_count: Mapped[int | None] = mapped_column(Integer)
    quality_weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(32), default="S2")  # S2 | L8 | L9 …

    pond: Mapped["Pond"] = relationship(back_populates="observations")  # noqa: F821
