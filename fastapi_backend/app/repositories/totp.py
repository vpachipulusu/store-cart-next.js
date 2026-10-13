from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.user import User


@dataclass(frozen=True)
class TotpState:
    user_id: str
    enabled: bool
    ciphertext: str | None


class TotpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_user(self, uid: str) -> TotpState | None:
        result = await self.session.execute(
            select(User.id, User.two_factor_enabled, User.two_factor_secret)
            .where(User.firebase_uid == uid)
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            return None
        return TotpState(row.id, row.two_factor_enabled, row.two_factor_secret)

    async def set_state(
        self, user_id: str, enabled: bool, ciphertext: str | None
    ) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(two_factor_enabled=enabled, two_factor_secret=ciphertext)
        )
