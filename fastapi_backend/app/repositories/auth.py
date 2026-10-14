from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.core.firebase import VerifiedIdentity
from app.models.platform.user import LoginHistory, User
from app.repositories.base import BaseRepository


class AuthRepository(BaseRepository):
    async def sync_user(
        self,
        identity: VerifiedIdentity,
        logged_in_at: datetime,
        *,
        touch_login: bool = True,
    ) -> str:
        # Concurrent first logins converge by UID. A conflicting email never links another UID.
        statement = insert(User).values(
            firebase_uid=identity.uid,
            email=identity.email,
            email_verified=identity.email_verified,
            display_name=identity.name,
            last_login_at=logged_in_at,
        )
        upsert = statement.on_conflict_do_update(
            index_elements=[User.firebase_uid],
            set_={
                "email": identity.email,
                "email_verified": identity.email_verified,
                # A session refresh is not a sign-in (KAN-163): keep last_login_at.
                **({"last_login_at": logged_in_at} if touch_login else {}),
                "updated_at": func.now(),
            },
        ).returning(User.id)
        result = await self._session.execute(upsert)
        return str(result.scalar_one())

    async def record_login(self, user_id: str, ip: str, user_agent: str | None) -> None:
        self._session.add(
            LoginHistory(user_id=user_id, ip_address=ip, user_agent=user_agent)
        )
        await self._session.flush()
