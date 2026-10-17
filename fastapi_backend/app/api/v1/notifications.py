"""In-app notifications for the signed-in user (KAN-40).

Every route acts on the caller's own rows only: the user id comes from the verified
session, never from the request. Someone else's notification answers the same 404 as a
missing one. The optional ``organization_id`` / ``store_id`` filters only narrow the
caller's own notifications; they grant no access to an organisation or store.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.me import CurrentUserIdDep
from app.api.rate_limit import RATE_LIMIT_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.notifications import NotificationScope, NotificationsRepository
from app.services.notifications import NotificationNotFound, NotificationsService

router = APIRouter(
    prefix="/v1/notifications",
    tags=["notifications"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in"},
        403: {"model": ErrorResponse, "description": "Email not verified"},
        404: {
            "model": ErrorResponse,
            "description": "User, or the notification (missing or not yours), not found",
        },
        503: {"model": ErrorResponse},
        **RATE_LIMIT_RESPONSES,
    },
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_OFFSET = 10_000
ID_PATTERN = r"^[A-Za-z0-9_-]+$"


def get_notifications_service(session: SessionDep) -> NotificationsService:
    return NotificationsService(NotificationsRepository(session), session)


NotificationsServiceDep = Annotated[
    NotificationsService, Depends(get_notifications_service)
]
OrganizationIdFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        pattern=ID_PATTERN,
        description="Only your notifications for this organisation (includes its stores).",
    ),
]
StoreIdFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        pattern=ID_PATTERN,
        description="Only your notifications for this store.",
    ),
]
NotificationIdPath = Annotated[
    str, Path(min_length=1, max_length=128, pattern=ID_PATTERN)
]


class NotificationItem(BaseModel):
    id: str
    type: str
    title: str
    message: str
    read: bool
    link: str | None
    organization_id: str | None
    store_id: str | None
    created_at: datetime


class NotificationListData(BaseModel):
    notifications: list[NotificationItem]
    total_count: int = Field(
        description="Matches for the filters, including `unread_only` (for paging)."
    )
    unread_count: int = Field(
        description="Unread matches for the organisation/store filters, ignoring `unread_only`."
    )


class NotificationListResponse(BaseModel):
    success: Literal[True] = True
    data: NotificationListData


class NotificationResponse(BaseModel):
    success: Literal[True] = True
    data: NotificationItem


class MarkAllReadData(BaseModel):
    updated_count: int


class MarkAllReadResponse(BaseModel):
    success: Literal[True] = True
    data: MarkAllReadData


class DeletedResponse(BaseModel):
    success: Literal[True] = True


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    response: Response,
    user_id: CurrentUserIdDep,
    service: NotificationsServiceDep,
    organization_id: OrganizationIdFilter = None,
    store_id: StoreIdFilter = None,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> NotificationListResponse:
    response.headers["Cache-Control"] = "no-store"
    page = await service.list_notifications(
        user_id,
        NotificationScope(organization_id, store_id),
        unread_only,
        limit,
        offset,
    )
    return NotificationListResponse(
        data=NotificationListData(
            notifications=[NotificationItem(**asdict(n)) for n in page.notifications],
            total_count=page.total_count,
            unread_count=page.unread_count,
        )
    )


@router.post("/read-all", response_model=MarkAllReadResponse)
async def mark_all_notifications_read(
    response: Response,
    user_id: CurrentUserIdDep,
    service: NotificationsServiceDep,
    organization_id: OrganizationIdFilter = None,
    store_id: StoreIdFilter = None,
) -> MarkAllReadResponse:
    response.headers["Cache-Control"] = "no-store"
    updated = await service.mark_all_read(
        user_id, NotificationScope(organization_id, store_id)
    )
    return MarkAllReadResponse(data=MarkAllReadData(updated_count=updated))


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: NotificationIdPath,
    response: Response,
    user_id: CurrentUserIdDep,
    service: NotificationsServiceDep,
) -> NotificationResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        notification = await service.mark_read(user_id, notification_id)
    except NotificationNotFound:
        raise HTTPException(404, "Notification not found") from None
    return NotificationResponse(data=NotificationItem(**asdict(notification)))


@router.delete("/{notification_id}", response_model=DeletedResponse)
async def delete_notification(
    notification_id: NotificationIdPath,
    response: Response,
    user_id: CurrentUserIdDep,
    service: NotificationsServiceDep,
) -> DeletedResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        await service.delete(user_id, notification_id)
    except NotificationNotFound:
        raise HTTPException(404, "Notification not found") from None
    return DeletedResponse()
