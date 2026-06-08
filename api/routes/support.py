import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import select

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..dependencies import require_admin_role


logger = logging.getLogger(__name__)

support_router = APIRouter(
    prefix="/api/v1/support", tags=["Support"], dependencies=[Depends(get_current_user)]
)

admin_support_router = APIRouter(
    prefix="/api/v1/admin/support",
    tags=["Admin Support"],
    dependencies=[Depends(require_admin_role)],
)


@support_router.post(
    "/ticket", response_model=schemas.SupportTicket, status_code=status.HTTP_201_CREATED
)
async def create_support_ticket(
    ticket_in: schemas.SupportTicketCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    db_ticket = models.SupportTicket(
        user_id=current_user.id,
        subject=ticket_in.subject,
        category=ticket_in.category,
        description=ticket_in.description,
        context=ticket_in.context,
        screenshot=ticket_in.screenshot,
    )
    db.add(db_ticket)
    await db.commit()
    await db.refresh(db_ticket)

    logger.info(
        "SUPPORT TICKET created: %s from user %s", db_ticket.id, current_user.email
    )
    return db_ticket


@support_router.get("/tickets", response_model=List[schemas.SupportTicket])
async def get_user_tickets(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.SupportTicket)
        .options(joinedload(models.SupportTicket.messages))
        .where(models.SupportTicket.user_id == current_user.id)
        .order_by(models.SupportTicket.created_at.desc())
    )
    return result.scalars().unique().all()


@admin_support_router.get("/tickets", response_model=List[schemas.AdminSupportTicket])
async def admin_get_all_tickets(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(models.SupportTicket).options(
        joinedload(models.SupportTicket.user), joinedload(models.SupportTicket.messages)
    )

    if status:
        query = query.where(models.SupportTicket.status == status)
    if category:
        query = query.where(models.SupportTicket.category == category)

    query = (
        query.order_by(models.SupportTicket.created_at.desc()).offset(skip).limit(limit)
    )
    result = await db.execute(query)
    tickets = result.scalars().unique().all()

    response = []
    for ticket in tickets:
        ticket_data = schemas.AdminSupportTicket.model_validate(ticket)

        is_anonymous = False
        contact_email = None
        if ticket.context and isinstance(ticket.context, dict):
            is_anonymous = ticket.context.get("is_anonymous", False)
            contact_email = ticket.context.get("contact_email")

        if is_anonymous:
            ticket_data.user_email = contact_email if contact_email else "Anonymous"
        else:
            ticket_data.user_email = ticket.user.email if ticket.user else "Unknown"

        response.append(ticket_data)

    return response


@admin_support_router.patch(
    "/tickets/{ticket_id}", response_model=schemas.SupportTicket
)
async def admin_update_ticket(
    ticket_id: str,
    ticket_update: schemas.SupportTicketUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
    )
    db_ticket = result.scalar_one_or_none()

    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket_update.status:
        db_ticket.status = ticket_update.status
    if ticket_update.category:
        db_ticket.category = ticket_update.category

    await db.commit()
    await db.refresh(db_ticket)
    return db_ticket


@support_router.get(
    "/tickets/{ticket_id}/messages",
    response_model=List[schemas.SupportTicketMessageResponse],
)
async def get_ticket_messages(
    ticket_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role != "admin" and ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view messages for this ticket.",
        )

    msg_result = await db.execute(
        select(models.SupportTicketMessage)
        .where(models.SupportTicketMessage.ticket_id == ticket_id)
        .order_by(models.SupportTicketMessage.created_at.asc())
    )
    return msg_result.scalars().all()


@support_router.post(
    "/tickets/{ticket_id}/messages",
    response_model=schemas.SupportTicketMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket_message(
    ticket_id: str,
    msg_in: schemas.SupportTicketMessageCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role != "admin" and ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to reply to this ticket."
        )

    is_admin = current_user.role == "admin"
    sender_name = (
        current_user.username if not is_admin else f"Support ({current_user.username})"
    )
    if msg_in.sender_name:
        sender_name = msg_in.sender_name

    db_msg = models.SupportTicketMessage(
        ticket_id=ticket_id,
        sender_name=sender_name,
        text=msg_in.text,
        image=msg_in.image,
        is_admin=is_admin,
    )
    db.add(db_msg)

    if is_admin:
        ticket.status = "IN_PROGRESS"
    else:
        ticket.status = "OPEN"

    await db.commit()
    await db.refresh(db_msg)
    return db_msg
