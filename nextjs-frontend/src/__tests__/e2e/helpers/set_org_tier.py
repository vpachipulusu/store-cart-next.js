"""Sets an organisation's subscription tier for local e2e (KAN-254).

A real Pro tier needs a Stripe checkout and webhook; the "New store" spec only needs the plan's store limit, so it
writes the tier the webhook would write, in the backend's own platform database. It is not part of the app.

Only for a local throwaway e2e database. Never run it against staging or production: it bypasses Stripe and
changes what a business is billed for.

Usage (from fastapi_backend/, with the same environment as uvicorn):
    PYTHONPATH=. uv run python <this file> <organization_id> <tier>
"""

import asyncio
import sys

from sqlalchemy import update

from app.core.database import async_session_maker
from app.models.platform import Organization


async def main(organization_id: str, tier: str) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(subscription_tier=tier)
        )
        if result.rowcount != 1:
            raise SystemExit(f"organisation {organization_id} not found")
        await session.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: set_org_tier.py <organization_id> <tier>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
