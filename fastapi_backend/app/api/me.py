from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.auth import get_current_identity
from app.api.deps import SessionDep
from app.core.firebase import FirebaseIdentityProvider, VerifiedIdentity
from app.repositories.me import MeRepository
from app.repositories.me_preferences import PreferencesRepository
from app.services.me import MeService, UserNotFound
from app.services.me_preferences import PreferencesService

CurrentIdentityDep = Annotated[VerifiedIdentity, Depends(get_current_identity)]


def get_me_service(identity: CurrentIdentityDep, session: SessionDep) -> MeService:
    return MeService(MeRepository(session), session, FirebaseIdentityProvider())


MeServiceDep = Annotated[MeService, Depends(get_me_service)]


def get_preferences_service(
    identity: CurrentIdentityDep, session: SessionDep
) -> PreferencesService:
    return PreferencesService(PreferencesRepository(session), session)


PreferencesServiceDep = Annotated[PreferencesService, Depends(get_preferences_service)]


async def get_current_user_id(
    identity: CurrentIdentityDep, service: MeServiceDep
) -> str:
    try:
        return (await service.get_profile(identity.uid)).id
    except UserNotFound:
        raise HTTPException(404, "User not found") from None


CurrentUserIdDep = Annotated[str, Depends(get_current_user_id)]
