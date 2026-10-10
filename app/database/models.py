from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Boolean, DateTime, text
from datetime import datetime

from app.database.database import Base


class User(Base):
    __tablename__ = 'users'

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, undex=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_premium: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reg_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now() AT TIME ZONE 'Europe/Moscow'"))


def __repr__(self) -> str:
    return f"<User tg_id={self.tg_id} username={self.username}>"
