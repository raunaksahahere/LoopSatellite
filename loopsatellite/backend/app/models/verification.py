from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# The officer's verdict on a flagged anomaly. This is the only write path in the MVP.
OUTCOMES = ("confirmed", "seasonal", "unclear", "already_actioned")


class Verification(Base):
    __tablename__ = "verification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(
        ForeignKey("anomaly.id", ondelete="CASCADE"), index=True
    )
    officer_note: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(32))
    officer_name: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    anomaly: Mapped["Anomaly"] = relationship(back_populates="verifications")  # noqa: F821
