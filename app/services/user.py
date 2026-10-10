from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import User


async def add_or_update_user(
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    language_code: str | None,
    is_premium: bool | None,
    session: AsyncSession,
) -> None:
    try:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))

        if user is None:
            user = User(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                is_premium=is_premium,
            )
            session.add(user)
        else:
            # обновляем только то, что может измениться
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.language_code = language_code
            user.is_premium = is_premium

        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise
