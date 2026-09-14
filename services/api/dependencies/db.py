"""Request-scoped DB session: commits on a clean return, rolls back on any exception —
so a route never has to remember to call `session.commit()` itself, and a failed
request never leaves a half-applied write (spec §4 rule 12: writes idempotent where
practical; this is the "never partially committed" half of that).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import get_sessionmaker


async def get_db_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
