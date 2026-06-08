# api/hub_router.py
import logging
import os
import hashlib
import httpx
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .database import get_db
from . import schemas, crud, models
from .depthsight_api import limiter, get_limit_value, APP_VERSION

logger = logging.getLogger(__name__)

HUB_ADMIN_API_KEY = os.getenv("HUB_ADMIN_API_KEY")

router = APIRouter(prefix="/api/v1/hub", tags=["Federation Hub"])


@router.get("/strategies", response_model=List[schemas.HubTopicResponse])
async def get_hub_strategies(db: AsyncSession = Depends(get_db)):
    """
    Returns a list of verified free strategy templates from DB (with seeding fallback).
    """
    try:
        strategies = await crud.get_hub_strategies(db)
        return strategies
    except Exception as e:
        logger.error(f"Error getting verified strategies: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve strategies.",
        )


@router.post(
    "/strategies",
    response_model=schemas.HubTopicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_hub_strategy(
    strategy: schemas.HubStrategy,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to publish a new verified strategy preset.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to publish verified strategies.",
        )

    try:
        new_strat = await crud.create_hub_strategy(db, strategy_data=strategy)
        await db.commit()
        await db.refresh(new_strat)
        return new_strat
    except Exception as e:
        logger.error(f"Error publishing verified strategy: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish strategy.",
        )


@router.delete("/strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hub_strategy(
    strategy_id: str,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to delete a verified strategy preset.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete verified strategies.",
        )

    try:
        await crud.delete_hub_strategy(db, strategy_id=strategy_id)
        await db.commit()
        return
    except Exception as e:
        logger.error(f"Error deleting verified strategy: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete strategy.",
        )


@router.get("/news", response_model=List[schemas.HubNewsResponse])
async def get_hub_news(db: AsyncSession = Depends(get_db)):
    """
    Returns a list of latest news and releases from DB (with seeding fallback).
    """
    try:
        news = await crud.get_hub_news(db)
        return news
    except Exception as e:
        logger.error(f"Error getting hub news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve news.",
        )


@router.post(
    "/news", response_model=schemas.HubNewsResponse, status_code=status.HTTP_201_CREATED
)
async def post_hub_news(
    news_item: schemas.HubNews,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to publish a new platform news update.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to publish news.",
        )

    try:
        new_news = await crud.create_hub_news(db, news_data=news_item)
        await db.commit()
        await db.refresh(new_news)
        return new_news
    except Exception as e:
        logger.error(f"Error publishing news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish news.",
        )


@router.delete("/news/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hub_news(
    news_id: int,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to delete a platform news update.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete news.",
        )

    try:
        await crud.delete_hub_news(db, news_id=news_id)
        await db.commit()
        return
    except Exception as e:
        logger.error(f"Error deleting news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete news.",
        )


@router.post("/news/{news_id}/like", response_model=schemas.HubNewsResponse)
async def like_news_item(news_id: int, db: AsyncSession = Depends(get_db)):
    try:
        updated = await crud.like_hub_news(db, news_id=news_id)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="News item not found."
            )
        await db.commit()
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error liking news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to like news item.",
        )


@router.post("/news/{news_id}/pin", response_model=schemas.HubNewsResponse)
async def pin_news_item(
    news_id: int,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to pin news.",
        )

    try:
        updated = await crud.pin_hub_news(db, news_id=news_id, pin=True)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="News item not found."
            )
        await db.commit()
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pinning news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pin news item.",
        )


@router.post("/news/{news_id}/unpin", response_model=schemas.HubNewsResponse)
async def unpin_news_item(
    news_id: int,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to unpin news.",
        )

    try:
        updated = await crud.pin_hub_news(db, news_id=news_id, pin=False)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="News item not found."
            )
        await db.commit()
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unpinning news: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unpin news item.",
        )


@router.post(
    "/news/{news_id}/comments",
    response_model=schemas.HubNewsCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_news_comment(
    news_id: int,
    comment: schemas.HubNewsCommentCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = select(models.HubNewsItem).filter(models.HubNewsItem.id == news_id)
        res = await db.execute(stmt)
        if not res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="News item not found."
            )
        new_comment = await crud.create_hub_news_comment(
            db, news_id=news_id, comment_data=comment
        )
        await db.commit()
        await db.refresh(new_comment)
        return new_comment
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error posting news comment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to post comment.",
        )


@router.get(
    "/news/{news_id}/comments", response_model=List[schemas.HubNewsCommentResponse]
)
async def get_news_comments(news_id: int, db: AsyncSession = Depends(get_db)):
    try:
        comments = await crud.get_hub_news_comments(db, news_id=news_id)
        return comments
    except Exception as e:
        logger.error(f"Error retrieving news comments: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve comments.",
        )


@router.post(
    "/feedback", response_model=Dict[str, str], status_code=status.HTTP_201_CREATED
)
@limiter.limit(get_limit_value("hub_feedback"))
async def post_hub_feedback(
    feedback: schemas.HubFeedbackCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receives feedback or bug reports, stores them in the database,
    and creates a corresponding admin support ticket.
    """
    try:
        ip = request.client.host if request.client else None
        await crud.create_hub_feedback(db, feedback_data=feedback, ip_address=ip)

        # Find an admin or any user to associate with the support ticket (since user_id is required)
        from sqlalchemy.future import select
        from . import models

        stmt_admin = select(models.User).filter(models.User.role == "admin").limit(1)
        res_admin = await db.execute(stmt_admin)
        assoc_user = res_admin.scalars().first()

        if not assoc_user:
            stmt_any = select(models.User).order_by(models.User.id.asc()).limit(1)
            res_any = await db.execute(stmt_any)
            assoc_user = res_any.scalars().first()

        if assoc_user:
            email_info = (
                f"\n\nSender Email: {feedback.contact_email}"
                if feedback.contact_email
                else ""
            )
            ticket_context = {
                "is_anonymous": True,
                "contact_email": feedback.contact_email,
            }
            db_ticket = models.SupportTicket(
                user_id=assoc_user.id,
                subject=f"[Hub Feedback] {feedback.category.upper()}",
                category=feedback.category,
                description=f"{feedback.text}{email_info}",
                status="OPEN",
                context=ticket_context,
            )
            db.add(db_ticket)

        await db.commit()

        ticket_id = None
        if assoc_user:
            await db.refresh(db_ticket)
            ticket_id = str(db_ticket.id)

        response_data = {
            "status": "success",
            "message": "Feedback submitted successfully.",
        }
        if ticket_id:
            response_data["ticket_id"] = ticket_id

        return response_data
    except Exception as e:
        logger.error(f"Error saving hub feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback.",
        )


@router.get("/topics", response_model=List[schemas.HubTopicResponse])
async def get_hub_topics(
    type: Literal["strategy", "discussion"] = "strategy",
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves all topics from the Hub filtered by type ('strategy' or 'discussion').
    """
    try:
        topics = await crud.get_hub_topics(db, topic_type=type)
        return topics
    except Exception as e:
        logger.error(f"Error retrieving hub topics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve topics.",
        )


@router.post(
    "/topics",
    response_model=schemas.HubTopicCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(get_limit_value("hub_topics"))
async def post_hub_topic(
    request: Request,
    topic: schemas.HubTopicCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Publishes a new topic (strategy idea or discussion) to the Hub.
    """
    try:
        new_topic = await crud.create_hub_topic(db, topic_data=topic)
        await db.commit()
        await db.refresh(new_topic)
        return new_topic
    except Exception as e:
        logger.error(f"Error creating hub topic: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish topic.",
        )


@router.post("/topics/{topic_id}/like", response_model=schemas.HubTopicResponse)
@limiter.limit(get_limit_value("hub_like"))
async def like_hub_topic(
    request: Request,
    topic_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Increments upvotes count for a topic.
    """
    try:
        updated_topic = await crud.like_hub_topic(db, topic_id=topic_id)
        if not updated_topic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found."
            )
        await db.commit()
        await db.refresh(updated_topic)
        return updated_topic
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error liking topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update likes count.",
        )


@router.get(
    "/topics/{topic_id}/comments", response_model=List[schemas.HubCommentResponse]
)
async def get_hub_comments(topic_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves comments for a specific Hub topic.
    """
    try:
        comments = await crud.get_hub_comments(db, topic_id=topic_id)
        return comments
    except Exception as e:
        logger.error(
            f"Error retrieving comments for topic {topic_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve comments.",
        )


@router.post(
    "/topics/{topic_id}/comments",
    response_model=schemas.HubCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(get_limit_value("hub_comments"))
async def post_hub_comment(
    request: Request,
    topic_id: str,
    comment: schemas.HubCommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Adds a new comment to a specific Hub topic.
    """
    try:
        new_comment = await crud.create_hub_comment(
            db, topic_id=topic_id, comment_data=comment
        )
        await db.commit()
        await db.refresh(new_comment)
        return new_comment
    except Exception as e:
        logger.error(f"Error creating comment for topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit comment.",
        )


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hub_topic(
    topic_id: str,
    delete_token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a topic from the Federation Hub.
    Requires either the topic's delete_token or the central hub admin API key.
    """
    try:
        from sqlalchemy.future import select
        from . import models

        stmt = select(models.HubTopic).filter(models.HubTopic.id == topic_id)
        result = await db.execute(stmt)
        topic = result.scalars().first()
        if not topic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found."
            )

        authorized = False

        if HUB_ADMIN_API_KEY:
            admin_key = None
            if authorization and authorization.startswith("Bearer "):
                admin_key = authorization.split(" ")[1]
            elif delete_token == HUB_ADMIN_API_KEY:
                admin_key = delete_token

            if admin_key == HUB_ADMIN_API_KEY:
                authorized = True

        if not authorized and delete_token and topic.delete_token:
            if delete_token == topic.delete_token:
                authorized = True

        if not authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this topic.",
            )

        await crud.delete_hub_topic(db, topic_id=topic_id)
        await db.commit()
        return
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete topic.",
        )


@router.post("/topics/{topic_id}/verify", response_model=schemas.HubTopicResponse)
async def verify_topic(
    topic_id: str,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to verify a community strategy topic, adding it to presets.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to verify topics.",
        )

    try:
        updated = await crud.verify_hub_topic(db, topic_id=topic_id)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found."
            )
        await db.commit()
        await db.refresh(updated)
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify topic.",
        )


@router.post("/topics/{topic_id}/unverify", response_model=schemas.HubTopicResponse)
async def unverify_topic(
    topic_id: str,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows Admin to unverify a strategy topic, removing it from presets.
    """
    admin_key = None
    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]

    if not HUB_ADMIN_API_KEY or admin_key != HUB_ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to unverify topics.",
        )

    try:
        updated = await crud.unverify_hub_topic(db, topic_id=topic_id)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found."
            )
        await db.commit()
        await db.refresh(updated)
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unverifying topic {topic_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unverify topic.",
        )


@router.get(
    "/tickets/{ticket_id}/status", response_model=schemas.SupportTicketStatusResponse
)
async def get_hub_ticket_status(ticket_id: str, db: AsyncSession = Depends(get_db)):
    """
    Returns public details (status, subject, category) of a support ticket.
    Authenticated by knowing the unguessable ticket_id UUID.
    """
    try:
        from sqlalchemy.future import select
        from . import models

        result = await db.execute(
            select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found.")
        return ticket
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticket status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve ticket status.",
        )


@router.patch(
    "/tickets/{ticket_id}/status", response_model=schemas.SupportTicketStatusResponse
)
async def update_hub_ticket_status(
    ticket_id: str, status_in: Dict[str, str], db: AsyncSession = Depends(get_db)
):
    """
    Allows a remote user to update their support ticket status (e.g. close it).
    """
    try:
        from sqlalchemy.future import select
        from . import models

        result = await db.execute(
            select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found.")

        new_status = status_in.get("status")
        if new_status:
            if new_status not in ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]:
                raise HTTPException(status_code=400, detail="Invalid status.")
            ticket.status = new_status
            await db.commit()
            await db.refresh(ticket)
        return ticket
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating ticket status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update ticket status.",
        )


@router.get(
    "/tickets/{ticket_id}/messages",
    response_model=List[schemas.SupportTicketMessageResponse],
)
async def get_hub_ticket_messages(ticket_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves message history for a hub support ticket.
    """
    try:
        from sqlalchemy.future import select
        from . import models

        result = await db.execute(
            select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found.")

        msg_result = await db.execute(
            select(models.SupportTicketMessage)
            .where(models.SupportTicketMessage.ticket_id == ticket_id)
            .order_by(models.SupportTicketMessage.created_at.asc())
        )
        return msg_result.scalars().all()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticket messages: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve ticket messages.",
        )


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=schemas.SupportTicketMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(get_limit_value("hub_messages"))
async def post_hub_ticket_message(
    request: Request,
    ticket_id: str,
    msg_in: schemas.SupportTicketMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Appends a user reply to a hub support ticket.
    """
    try:
        from sqlalchemy.future import select
        from . import models

        result = await db.execute(
            select(models.SupportTicket).where(models.SupportTicket.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found.")

        sender_name = msg_in.sender_name or "User"
        db_msg = models.SupportTicketMessage(
            ticket_id=ticket_id,
            sender_name=sender_name,
            text=msg_in.text,
            image=msg_in.image,
            is_admin=False,
        )
        db.add(db_msg)

        # Automatically reopen/set to OPEN when user replies
        ticket.status = "OPEN"

        await db.commit()
        await db.refresh(db_msg)
        return db_msg
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error posting ticket message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message.",
        )


async def geolocate_ip(ip: str):
    if (
        not ip
        or ip in ("127.0.0.1", "localhost", "::1")
        or ip.startswith("192.168.")
        or ip.startswith("10.")
        or ip.startswith("172.16.")
    ):
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"http://ip-api.com/json/{ip}")
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "success":
                    return {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": data.get("city"),
                        "country": data.get("countryName") or data.get("country"),
                    }
    except Exception as e:
        logger.error(f"Error geolocating IP {ip}: {e}")
    return None


def get_random_test_coordinates():
    cities = [
        {"city": "Frankfurt", "country": "Germany", "lat": 50.11, "lon": 8.68},
        {"city": "New York", "country": "USA", "lat": 40.71, "lon": -74.00},
        {"city": "Singapore", "country": "Singapore", "lat": 1.35, "lon": 103.82},
        {"city": "London", "country": "UK", "lat": 51.50, "lon": -0.12},
        {"city": "Tokyo", "country": "Japan", "lat": 35.67, "lon": 139.65},
        {"city": "Sydney", "country": "Australia", "lat": -33.86, "lon": 151.20},
    ]
    city = random.choice(cities)
    return {
        "lat": city["lat"] + random.uniform(-1.0, 1.0),
        "lon": city["lon"] + random.uniform(-1.0, 1.0),
        "city": city["city"],
        "country": city["country"],
    }


@router.post("/nodes/register", status_code=status.HTTP_201_CREATED)
async def register_hub_node(
    node_in: schemas.HubNodeRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = select(models.HubNode).where(
            models.HubNode.node_uuid == node_in.node_uuid
        )
        res = await db.execute(stmt)
        existing = res.scalars().first()

        secret_hash = hashlib.sha256(node_in.node_secret.encode()).hexdigest()
        ip = request.client.host if request.client else None

        geo = await geolocate_ip(ip)
        if not geo:
            geo = get_random_test_coordinates()

        if existing:
            existing.name = node_in.name
            existing.secret_hash = secret_hash
            existing.ip_address = ip
            existing.latitude = geo["lat"]
            existing.longitude = geo["lon"]
            existing.city = geo["city"]
            existing.country = geo["country"]
            existing.version = node_in.version or "1.0.0"
            existing.last_ping = datetime.now(timezone.utc)
            db_node = existing
        else:
            db_node = models.HubNode(
                node_uuid=node_in.node_uuid,
                name=node_in.name,
                secret_hash=secret_hash,
                ip_address=ip,
                latitude=geo["lat"],
                longitude=geo["lon"],
                city=geo["city"],
                country=geo["country"],
                version=node_in.version or "1.0.0",
                last_ping=datetime.now(timezone.utc),
                latency_ms=0.0,
                is_banned=False,
            )
            db.add(db_node)

        await db.commit()
        return {"status": "success", "message": "Node registered successfully"}
    except Exception as e:
        logger.error(f"Error registering hub node: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register node.",
        )


@router.post("/nodes/ping", status_code=status.HTTP_200_OK)
async def ping_hub_node(
    ping_in: schemas.HubNodePing,
    x_node_uuid: Optional[str] = Header(None, alias="X-Node-UUID"),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_uuid or not x_node_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing node credentials headers.",
        )

    try:
        stmt = select(models.HubNode).where(models.HubNode.node_uuid == x_node_uuid)
        res = await db.execute(stmt)
        node = res.scalars().first()

        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Node not registered."
            )

        secret_hash = hashlib.sha256(x_node_secret.encode()).hexdigest()
        if node.secret_hash != secret_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid node credentials.",
            )

        if node.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Node is banned."
            )

        node.last_ping = datetime.now(timezone.utc)
        node.latency_ms = ping_in.latency_ms
        if ping_in.version:
            node.version = ping_in.version
        await db.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling node ping: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process heartbeat.",
        )


@router.get("/nodes", response_model=List[schemas.HubNodeResponse])
async def get_active_nodes(db: AsyncSession = Depends(get_db)):
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stmt = select(models.HubNode).where(
            models.HubNode.last_ping >= cutoff, models.HubNode.is_banned.is_(False)
        )
        res = await db.execute(stmt)
        nodes = res.scalars().all()

        response_nodes = []

        response_nodes.append(
            schemas.HubNodeResponse(
                name="Central Master Hub",
                latitude=50.1109,
                longitude=8.6821,
                city="Frankfurt",
                country="Germany",
                latency_ms=0.0,
                version=APP_VERSION,
                is_master=True,
            )
        )

        for n in nodes:
            response_nodes.append(
                schemas.HubNodeResponse(
                    name=n.name,
                    latitude=n.latitude,
                    longitude=n.longitude,
                    city=n.city,
                    country=n.country,
                    latency_ms=n.latency_ms,
                    version=n.version or "1.0.0",
                    is_master=False,
                )
            )

        return response_nodes
    except Exception as e:
        logger.error(f"Error retrieving active nodes: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve network status.",
        )
