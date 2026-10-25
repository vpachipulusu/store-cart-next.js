"""Team members and invitations API (KAN-62).

Every route needs the internal service key and a verified session and is rate limited
by subject; creating an invitation has its own, fail-closed budget (it sends an email).
Members and invitations are listed and created only by an OWNER or ADMIN of the
organisation in the path (STAFF 403, non-member 404). The accept link is in the create
response only; list responses never carry a token or its hash. Accept is a POST with the
token in the body, so a link prefetcher cannot spend it. Responses are ``no-store``.
"""

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_email_sender
from app.api.me import CurrentIdentityDep, CurrentUserIdDep
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY, INVITATION_POLICY
from app.models.platform.membership import MembershipRole
from app.repositories.invitations import InvitationRecord, InvitationsRepository
from app.repositories.organizations import OrganizationsRepository
from app.services.email import EmailSender
from app.services.invitations import (
    MAX_EMAIL_LENGTH,
    AlreadyMember,
    InvalidEmail,
    InvalidInvitationRole,
    InvitationAlreadyPending,
    InvitationEmailMismatch,
    InvitationInvalid,
    InvitationsService,
    InvitationsUnavailable,
    TooManyPendingInvitations,
)
from app.services.organizations import OrganizationNotFound, OrgForbidden
from app.services.plan_limits import StaffLimitReached

logger = logging.getLogger(__name__)

COMMON_RESPONSES: dict[int | str, dict[str, object]] = {
    **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}

router = APIRouter(
    prefix="/v1/organizations/{organization_id}",
    tags=["organization-team"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={**COMMON_RESPONSES, 503: {"model": ErrorResponse}},
)

accept_router = APIRouter(
    prefix="/v1/invitations",
    tags=["invitations"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={**COMMON_RESPONSES, 410: {"model": ErrorResponse}},
)

OrganizationId = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class MemberData(BaseModel):
    user_id: str
    email: str
    display_name: str | None
    role: MembershipRole
    joined_at: datetime


class MemberListResponse(BaseModel):
    success: Literal[True] = True
    data: list[MemberData]


class InvitationData(BaseModel):
    id: str
    email: str
    role: MembershipRole
    expires_at: datetime
    created_at: datetime


class InvitationListResponse(BaseModel):
    success: Literal[True] = True
    data: list[InvitationData]


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=MAX_EMAIL_LENGTH)
    # OWNER is not invitable: ownership is never handed out by link.
    role: Literal[MembershipRole.ADMIN, MembershipRole.STAFF]


class CreatedInvitationData(InvitationData):
    # The only place the link appears: copy it now, it is never shown again.
    accept_url: str
    email_sent: bool


class CreatedInvitationResponse(BaseModel):
    success: Literal[True] = True
    data: CreatedInvitationData


class AcceptInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class AcceptedInvitationData(BaseModel):
    organization_id: str
    role: MembershipRole


class AcceptedInvitationResponse(BaseModel):
    success: Literal[True] = True
    data: AcceptedInvitationData


def get_invitations_service(
    session: SessionDep,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> InvitationsService:
    return InvitationsService(
        InvitationsRepository(session),
        OrganizationsRepository(session),
        session,
        sender,
        settings.app_public_url,
    )


ServiceDep = Annotated[InvitationsService, Depends(get_invitations_service)]

HANDLED = (
    OrganizationNotFound,
    OrgForbidden,
    InvalidInvitationRole,
    InvalidEmail,
    AlreadyMember,
    InvitationAlreadyPending,
    TooManyPendingInvitations,
    StaffLimitReached,
    InvitationInvalid,
    InvitationEmailMismatch,
    InvitationsUnavailable,
)

MESSAGES: dict[type[Exception], tuple[int, str]] = {
    OrganizationNotFound: (404, "Organization not found"),
    OrgForbidden: (403, "Forbidden"),
    InvalidInvitationRole: (422, "Role cannot be invited"),
    InvalidEmail: (422, "Invalid email address"),
    AlreadyMember: (409, "Already a member of this organization"),
    InvitationAlreadyPending: (409, "An invitation is already pending for this email"),
    TooManyPendingInvitations: (409, "Too many pending invitations"),
    InvitationInvalid: (410, "This invitation is invalid or has expired"),
    InvitationEmailMismatch: (
        403,
        "This invitation was sent to a different email address",
    ),
    InvitationsUnavailable: (503, "Service temporarily unavailable"),
}


def http_error(exc: Exception) -> HTTPException:
    """A fixed message per error; the plan limit message names the plan."""
    if isinstance(exc, StaffLimitReached):
        error = HTTPException(409, str(exc))
    else:
        status, message = MESSAGES[type(exc)]
        error = HTTPException(status, message)
    # Class and status only: never the email, the token or the link.
    logger.info(
        "team request refused: cause=%s status=%s",
        type(exc).__name__,
        error.status_code,
    )
    return error


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def request_id_of(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def invitation_data(invitation: InvitationRecord) -> InvitationData:
    return InvitationData(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.get("/members", response_model=MemberListResponse)
async def list_members(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> MemberListResponse:
    no_store(response)
    try:
        members = await service.list_members(organization_id, user_id)
    except HANDLED as exc:
        raise http_error(exc) from None
    return MemberListResponse(
        data=[MemberData.model_validate(m, from_attributes=True) for m in members]
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> InvitationListResponse:
    """Pending, unexpired invitations. Never includes a token or a link."""
    no_store(response)
    try:
        invitations = await service.list_invitations(organization_id, user_id)
    except HANDLED as exc:
        raise http_error(exc) from None
    return InvitationListResponse(data=[invitation_data(i) for i in invitations])


@router.post(
    "/invitations",
    response_model=CreatedInvitationResponse,
    status_code=201,
    dependencies=[Depends(limit_by_subject(INVITATION_POLICY, current_subject))],
)
async def create_invitation(
    organization_id: OrganizationId,
    body: CreateInvitationRequest,
    request: Request,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> CreatedInvitationResponse:
    """Invite by email as ADMIN or STAFF (OWNER or ADMIN only, within the plan limit).

    The accept link is returned here once and emailed; ``email_sent`` is false when the
    email could not be sent (the invitation exists and the link still works).
    """
    no_store(response)
    try:
        created = await service.create_invitation(
            organization_id,
            user_id,
            email=body.email,
            role=MembershipRole(body.role),
            request_id=request_id_of(request),
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    base = invitation_data(created.invitation)
    return CreatedInvitationResponse(
        data=CreatedInvitationData(
            **base.model_dump(),
            accept_url=created.accept_url,
            email_sent=created.email_sent,
        )
    )


@accept_router.post("/accept", response_model=AcceptedInvitationResponse)
async def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    response: Response,
    identity: CurrentIdentityDep,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> AcceptedInvitationResponse:
    """Join the organisation; the signed-in verified email must match the invitation."""
    no_store(response)
    try:
        accepted = await service.accept(
            body.token, user_id, identity.email, request_id=request_id_of(request)
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return AcceptedInvitationResponse(
        data=AcceptedInvitationData(
            organization_id=accepted.organization_id, role=accepted.role
        )
    )
