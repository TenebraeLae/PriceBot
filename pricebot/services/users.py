from sqlalchemy.exc import IntegrityError

from pricebot.db.models import User


async def upsert_user(
    session,
    telegram_id: int,
    username: str | None = None,
) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, username=username, status="active")
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            user = await session.get(User, telegram_id)
            if user is None:
                raise
    if username is not None and user.username != username:
        user.username = username
    return user
