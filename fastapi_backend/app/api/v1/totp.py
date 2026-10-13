from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr

from app.api.auth import auth_error, get_current_identity, require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    RateLimitSubject,
    limit_by_subject,
)
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.firebase import (
    AuthenticationFailed,
    FirebaseIdentityProvider,
    IdentityProviderUnavailable,
    VerifiedIdentity,
)
from app.core.rate_limit import AUTH_POLICY
from app.core.totp import TotpCodec, TotpUnavailable
from app.repositories.totp import TotpRepository
from app.services.totp import (
    InvalidTotpCode,
    TotpConflict,
    TotpService,
    TotpUserMissing,
)

IdentityDep = Annotated[VerifiedIdentity, Depends(get_current_identity)]


def get_totp_service(_identity: IdentityDep, session: SessionDep) -> TotpService:
    key = settings.TOTP_ENCRYPTION_KEY
    try:
        codec = TotpCodec(key.get_secret_value() if key else None)
    except TotpUnavailable:
        raise HTTPException(
            503, "Service temporarily unavailable", {"Retry-After": "5"}
        ) from None
    return TotpService(
        FirebaseIdentityProvider(), TotpRepository(session), session, codec
    )


TotpServiceDep = Annotated[TotpService, Depends(get_totp_service)]


async def current_subject(identity: IdentityDep) -> RateLimitSubject:
    return RateLimitSubject("user", identity.uid)


router = APIRouter(
    prefix="/v1/me/totp",
    tags=["totp"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(AUTH_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)


class EnrollmentRequest(BaseModel):
    id_token: SecretStr = Field(min_length=1, max_length=16384)


class VerificationRequest(BaseModel):
    token: SecretStr = Field(min_length=6, max_length=6)


class DisableRequest(EnrollmentRequest, VerificationRequest):
    pass


class EnrollmentData(BaseModel):
    secret: str
    uri: str


class EnrollmentResponse(BaseModel):
    success: Literal[True] = True
    data: EnrollmentData


class TotpChangedResponse(BaseModel):
    success: Literal[True] = True


def totp_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (AuthenticationFailed, IdentityProviderUnavailable)):
        return auth_error(exc)
    if isinstance(exc, TotpUnavailable):
        return HTTPException(
            503, "Service temporarily unavailable", {"Retry-After": "5"}
        )
    if isinstance(exc, TotpUserMissing):
        return HTTPException(404, "User not found")
    if isinstance(exc, InvalidTotpCode):
        return HTTPException(400, "Invalid verification code")
    return HTTPException(409, "TOTP state conflict")


TOTP_ERRORS = (
    AuthenticationFailed,
    IdentityProviderUnavailable,
    TotpUnavailable,
    TotpUserMissing,
    InvalidTotpCode,
    TotpConflict,
)


@router.post("/enroll", response_model=EnrollmentResponse)
async def enroll(
    body: EnrollmentRequest,
    response: Response,
    identity: IdentityDep,
    service: TotpServiceDep,
) -> EnrollmentResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        enrollment = await service.enroll(identity, body.id_token.get_secret_value())
    except TOTP_ERRORS as exc:
        raise totp_error(exc) from None
    return EnrollmentResponse(
        data=EnrollmentData(secret=enrollment.secret, uri=enrollment.uri)
    )


@router.post("/verify", response_model=TotpChangedResponse)
async def verify(
    body: VerificationRequest,
    response: Response,
    identity: IdentityDep,
    service: TotpServiceDep,
) -> TotpChangedResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        await service.confirm(identity, body.token.get_secret_value())
    except TOTP_ERRORS as exc:
        raise totp_error(exc) from None
    return TotpChangedResponse()


@router.post("/disable", response_model=TotpChangedResponse)
async def disable(
    body: DisableRequest,
    response: Response,
    identity: IdentityDep,
    service: TotpServiceDep,
) -> TotpChangedResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        await service.disable(
            identity, body.id_token.get_secret_value(), body.token.get_secret_value()
        )
    except TOTP_ERRORS as exc:
        raise totp_error(exc) from None
    return TotpChangedResponse()
