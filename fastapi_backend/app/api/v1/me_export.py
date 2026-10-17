"""``POST /v1/me/export``: the caller downloads their own personal data (KAN-120)."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.me import CurrentIdentityDep
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    client_ip,
    limit_by_subject,
)
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.rate_limit import EXPORT_POLICY
from app.repositories.audit import AuditRepository
from app.repositories.me_export import MeExportRepository
from app.services.me_export import ExportNotAvailable, MeExportService

router = APIRouter(
    prefix="/v1/me",
    tags=["me"],
    dependencies=[Depends(require_internal_key)],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    },
)


class ExportProfile(BaseModel):
    id: str
    email: str
    email_verified: bool
    two_factor_enabled: bool
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    location: str | None
    website: str | None
    phone_number: str | None
    last_login_at: datetime | None
    created_at: datetime


class ExportSettings(BaseModel):
    theme: str
    email_notifications: bool
    language: str
    timezone: str


class ExportMembership(BaseModel):
    organization_id: str
    organization_name: str
    organization_slug: str
    role: str
    joined_at: datetime
    subscription_tier: str
    subscription_status: str
    subscription_current_period_end: datetime | None
    subscription_cancel_at_period_end: bool


class ExportLogin(BaseModel):
    id: str
    ip_address: str | None
    user_agent: str | None
    location: str | None
    login_at: datetime
    successful: bool


class ExportNotification(BaseModel):
    id: str
    type: str
    title: str
    message: str
    read: bool
    link: str | None
    organization_id: str | None
    store_id: str | None
    created_at: datetime


class ExportData(BaseModel):
    exported_at: datetime
    profile: ExportProfile
    settings: ExportSettings
    memberships: list[ExportMembership]
    login_history: list[ExportLogin]
    notifications: list[ExportNotification]
    # True when a list was cut at the per-list cap (1000 newest rows kept).
    truncated: bool


class ExportResponse(BaseModel):
    success: Literal[True] = True
    data: ExportData


def get_export_service(session: SessionDep) -> MeExportService:
    return MeExportService(
        MeExportRepository(session), AuditRepository(session), session
    )


ExportServiceDep = Annotated[MeExportService, Depends(get_export_service)]


@router.post(
    "/export",
    response_model=ExportResponse,
    summary="Download my personal data",
    dependencies=[Depends(limit_by_subject(EXPORT_POLICY, current_subject))],
)
async def export_my_data(
    request: Request,
    response: Response,
    identity: CurrentIdentityDep,
    service: ExportServiceDep,
) -> ExportResponse:
    """Everything stored about the caller: profile, settings, memberships (with the
    organisation's subscription), login history and notifications. Secrets, tokens and
    other users' data are never included. Rate limited; each call is audit logged."""
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(UTC)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="storecart-export-{now:%Y%m%d}.json"'
    )
    try:
        export = await service.export(
            identity.uid,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
        )
    except ExportNotAvailable:
        raise HTTPException(404, "User not found") from None
    return ExportResponse(data=ExportData(exported_at=now, **asdict(export)))
