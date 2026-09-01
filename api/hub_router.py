# api/hub_router.py
import asyncio
import logging
import os
import time
import hashlib
import httpx
import random
from datetime import date, datetime, timezone, timedelta
from typing import List, Dict, Optional, Literal
from fastapi import APIRouter, Body, Depends, HTTPException, status, Request, Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .database import get_db
from . import schemas, crud, models
from .depthsight_api import limiter, get_limit_value, APP_VERSION
from .plans import plans_config

import hmac

from .wallet_auth import (
    verify_ownership_signature,
    ownership_message_hash,
    OWNERSHIP_PURPOSE_BIND,
    OWNERSHIP_PURPOSE_REVOKE,
    OWNERSHIP_AUTH_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

HUB_ADMIN_API_KEY = os.getenv("HUB_ADMIN_API_KEY")


def sign_admin_name(author_name: str, key: Optional[str]) -> str:
    if not key or not author_name:
        return author_name
    sig = hmac.new(key.encode(), author_name.encode(), hashlib.sha256).hexdigest()[:12]
    return f"{author_name}[a:{sig}]"


def verify_and_clean_admin_name(
    author_name: str, key: Optional[str]
) -> tuple[str, bool]:
    if not author_name:
        return "", False
    if not key:
        return author_name, False

    if "[a:" in author_name and author_name.endswith("]"):
        parts = author_name.rsplit("[a:", 1)
        if len(parts) == 2:
            original_name, sig_part = parts
            sig = sig_part[:-1]
            expected_sig = hmac.new(
                key.encode(), original_name.encode(), hashlib.sha256
            ).hexdigest()[:12]
            if hmac.compare_digest(sig, expected_sig):
                return original_name, True

    return author_name, False


def make_topic_response(topic: models.HubTopic) -> schemas.HubTopicResponse:
    clean_name, is_admin = verify_and_clean_admin_name(
        topic.author_name, HUB_ADMIN_API_KEY
    )
    res = schemas.HubTopicResponse.model_validate(topic)
    res.author_name = clean_name
    res.is_admin = is_admin
    return res


def make_topic_create_response(
    topic: models.HubTopic,
) -> schemas.HubTopicCreateResponse:
    clean_name, is_admin = verify_and_clean_admin_name(
        topic.author_name, HUB_ADMIN_API_KEY
    )
    res = schemas.HubTopicCreateResponse.model_validate(topic)
    res.author_name = clean_name
    res.is_admin = is_admin
    return res


def make_comment_response(comment: models.HubComment) -> schemas.HubCommentResponse:
    clean_name, is_admin = verify_and_clean_admin_name(
        comment.author_name, HUB_ADMIN_API_KEY
    )
    res = schemas.HubCommentResponse.model_validate(comment)
    res.author_name = clean_name
    res.is_admin = is_admin
    return res


def make_news_comment_response(
    comment: models.HubNewsComment,
) -> schemas.HubNewsCommentResponse:
    clean_name, is_admin = verify_and_clean_admin_name(
        comment.author_name, HUB_ADMIN_API_KEY
    )
    res = schemas.HubNewsCommentResponse.model_validate(comment)
    res.author_name = clean_name
    res.is_admin = is_admin
    return res


router = APIRouter(prefix="/api/v1/hub", tags=["Federation Hub"])


@router.get("/strategies", response_model=List[schemas.HubTopicResponse])
async def get_hub_strategies(db: AsyncSession = Depends(get_db)):
    """
    Returns a list of verified free strategy templates from DB (with seeding fallback).
    """
    try:
        strategies = await crud.get_hub_strategies(db)
        return [make_topic_response(s) for s in strategies]
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
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = select(models.HubNewsItem).filter(models.HubNewsItem.id == news_id)
        res = await db.execute(stmt)
        if not res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="News item not found."
            )

        admin_key = None
        if authorization and authorization.startswith("Bearer "):
            admin_key = authorization.split(" ")[1]

        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            comment.author_name = sign_admin_name(
                comment.author_name, HUB_ADMIN_API_KEY
            )

        new_comment = await crud.create_hub_news_comment(
            db, news_id=news_id, comment_data=comment
        )
        await db.commit()
        await db.refresh(new_comment)
        return make_news_comment_response(new_comment)
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
        return [make_news_comment_response(c) for c in comments]
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
        # IP is not stored to respect complete user privacy
        await crud.create_hub_feedback(db, feedback_data=feedback, ip_address=None)

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
        return [make_topic_response(t) for t in topics]
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
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Publishes a new topic (strategy idea or discussion) to the Hub.
    """
    try:
        admin_key = None
        if authorization and authorization.startswith("Bearer "):
            admin_key = authorization.split(" ")[1]

        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            topic.author_name = sign_admin_name(topic.author_name, HUB_ADMIN_API_KEY)

        new_topic = await crud.create_hub_topic(db, topic_data=topic)
        await db.commit()
        await db.refresh(new_topic)
        return make_topic_create_response(new_topic)
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
        return make_topic_response(updated_topic)
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
        return [make_comment_response(c) for c in comments]
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
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Adds a new comment to a specific Hub topic.
    """
    try:
        admin_key = None
        if authorization and authorization.startswith("Bearer "):
            admin_key = authorization.split(" ")[1]

        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            comment.author_name = sign_admin_name(
                comment.author_name, HUB_ADMIN_API_KEY
            )

        new_comment = await crud.create_hub_comment(
            db, topic_id=topic_id, comment_data=comment
        )
        await db.commit()
        await db.refresh(new_comment)
        return make_comment_response(new_comment)
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


def get_client_ip(request: Request) -> Optional[str]:
    if not request:
        return None
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Use the LAST entry: the reverse proxy appends the actual peer
        # address, while client-supplied entries can be freely spoofed.
        parts = [p.strip() for p in forwarded_for.split(",")]
        for p in reversed(parts):
            if (
                p
                and p not in ("127.0.0.1", "localhost", "::1")
                and not (
                    p.startswith("192.168.")
                    or p.startswith("10.")
                    or p.startswith("172.16.")
                )
            ):
                return p
        return parts[-1]

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host
    return None


_cached_master_geo = None


async def get_master_hub_geo(request: Optional[Request] = None):
    global _cached_master_geo

    env_lat = os.getenv("HUB_LATITUDE")
    env_lon = os.getenv("HUB_LONGITUDE")
    if env_lat and env_lon:
        try:
            return {
                "lat": float(env_lat),
                "lon": float(env_lon),
                "city": os.getenv("HUB_CITY", "Central Hub"),
                "country": os.getenv("HUB_COUNTRY", ""),
            }
        except ValueError:
            pass

    if _cached_master_geo:
        return _cached_master_geo

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get("http://ip-api.com/json/")
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "success":
                    _cached_master_geo = {
                        "lat": data.get("lat", 50.1109),
                        "lon": data.get("lon", 8.6821),
                        "city": data.get("city", "Frankfurt"),
                        "country": data.get("countryName")
                        or data.get("country", "Germany"),
                    }
                    return _cached_master_geo
    except Exception as e:
        logger.warning(f"Failed to auto-geolocate master hub IP: {e}")

    return {
        "lat": 50.1109,
        "lon": 8.6821,
        "city": "Frankfurt",
        "country": "Germany",
    }


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


async def _resolve_referrer_node(
    db: AsyncSession, referrer_code: Optional[str]
) -> Optional[str]:
    """Resolve a referrer_code (node or user level) to a node_uuid, or None."""
    if not referrer_code:
        return None
    referrer_stmt = select(models.HubNode).where(
        models.HubNode.node_referral_code == referrer_code
    )
    referrer_res = await db.execute(referrer_stmt)
    referrer_node = referrer_res.scalars().first()
    if referrer_node:
        return referrer_node.node_uuid

    user_stmt = select(models.User).where(models.User.referral_code == referrer_code)
    user_res = await db.execute(user_stmt)
    ref_user = user_res.scalars().first()
    if not ref_user:
        return None

    u_node_stmt = select(models.HubNode).where(
        models.HubNode.node_referral_code == ref_user.referral_code
    )
    u_node_res = await db.execute(u_node_stmt)
    u_node = u_node_res.scalars().first()
    return u_node.node_uuid if u_node else None


async def _bind_referrer_once(
    db: AsyncSession, node: models.HubNode, referrer_code: Optional[str]
) -> None:
    """
    One-time referrer binding with self/cycle protection.

    A node can be linked to a referrer exactly once. Rebinding to a different
    referrer is rejected, and referral cycles / self-referrals are forbidden.
    """
    if not referrer_code:
        return
    if node.node_referral_code and node.node_referral_code == referrer_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A node cannot refer itself.",
        )

    target_uuid = await _resolve_referrer_node(db, referrer_code)
    if not target_uuid:
        return  # unknown code: keep node unlinked (legacy behaviour)

    if target_uuid == node.node_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A node cannot refer itself.",
        )

    if node.referrer_node_uuid:
        if node.referrer_node_uuid != target_uuid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Node is already linked to a referrer and cannot be re-linked.",
            )
        return  # already linked to the same referrer: idempotent

    # Walk up the referrer chain from the target to detect cycles
    # (shared guard also used by the local-node binding paths in config.py).
    if await crud.referrer_link_creates_cycle(db, node.node_uuid, target_uuid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referral cycle detected.",
        )

    node.referrer_node_uuid = target_uuid


async def _upsert_server_config(
    db: AsyncSession, node_uuid: str, share_percent: float
) -> None:
    """Store/refresh the reward-share config of a mining server node."""
    if not share_percent or not (0.0 < share_percent <= 100.0):
        return
    stmt = select(models.HubServerConfig).where(
        models.HubServerConfig.node_uuid == node_uuid
    )
    res = await db.execute(stmt)
    cfg = res.scalars().first()
    if cfg:
        cfg.user_reward_share_percent = share_percent
    else:
        db.add(
            models.HubServerConfig(
                node_uuid=node_uuid,
                user_reward_share_percent=share_percent,
            )
        )


async def _verify_wallet_ownership(
    db: AsyncSession,
    node: Optional[models.HubNode],
    wallet_address: Optional[str],
    signature: Optional[str],
    message: Optional[str],
    purpose: str = OWNERSHIP_PURPOSE_BIND,
) -> bool:
    """
    Verifies a wallet ownership signature against the node's bound wallet and
    consumes it (single-use replay protection).

    For wallet-bound nodes the EVM wallet is the ownership credential: the node
    secret stored server-side is only a write-only telemetry credential. Without
    a valid wallet signature the node secret cannot rotate, a referrer cannot be
    bound and a wallet node cannot be created (prevents pre-registration hijack).

    A verified message is claimed exactly once via used_ownership_messages: a
    resubmission of the same signed blob is rejected even within its TTL. The
    claim lives in the current transaction — if the authorized state change is
    rolled back, the signature becomes usable again.
    """
    addr = (node.wallet_address if node else None) or wallet_address
    if not addr or not signature or not message:
        return False
    if not verify_ownership_signature(addr, signature, message, purpose=purpose):
        return False
    return await crud.claim_ownership_message(
        db,
        ownership_message_hash(message),
        int(time.time()) + OWNERSHIP_AUTH_TTL_SECONDS,
    )


# Serialises node registration within one hub process: two concurrent binds of
# the SAME node_uuid would otherwise both pass the existence check and race to
# INSERT (UNIQUE violation -> 500). Cross-process races are still covered by
# the unique constraint and converted to a 409 below.
_register_node_lock = asyncio.Lock()


@router.post("/nodes/register", status_code=status.HTTP_201_CREATED)
async def register_hub_node(
    node_in: schemas.HubNodeRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    async with _register_node_lock:
        return await _register_hub_node_impl(node_in, request, db)


async def _register_hub_node_impl(
    node_in: schemas.HubNodeRegister,
    request: Request,
    db: AsyncSession,
):
    try:
        from sqlalchemy import update

        stmt = select(models.HubNode).where(
            models.HubNode.node_uuid == node_in.node_uuid
        )
        res = await db.execute(stmt)
        existing = res.scalars().first()

        secret_hash = hashlib.sha256(node_in.node_secret.encode()).hexdigest()
        ip = get_client_ip(request)

        geo = await geolocate_ip(ip)
        if not geo:
            geo = get_random_test_coordinates()

        import secrets

        wallet_addr = (node_in.wallet_address or "").strip().lower() or None
        allow_sensitive = True
        allow_referrer = True

        if existing:
            existing_wallet = (existing.wallet_address or "").strip().lower() or None
            if existing_wallet:
                # Wallet-bound node: the EVM wallet is the ownership credential and the
                # node secret is only a write-only telemetry credential. The wallet can
                # never be rebound to a different address.
                if wallet_addr and wallet_addr != existing_wallet:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Wallet address of a bound node cannot be changed.",
                    )
                owner_ok = await _verify_wallet_ownership(
                    db, existing, None, node_in.owner_signature, node_in.owner_message
                )
                if owner_ok:
                    # Full ownership update: rotate the telemetry secret.
                    existing.secret_hash = secret_hash
                else:
                    # Metadata-only update by the holder of the current telemetry secret.
                    if existing.secret_hash and existing.secret_hash != secret_hash:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Telemetry secret rotation requires a valid wallet ownership signature. Connect the wallet to update this node.",
                        )
                # Sensitive changes (referrer, mining flags) require wallet ownership.
                allow_sensitive = owner_ok
                allow_referrer = owner_ok
            elif wallet_addr:
                # Legacy node being claimed by a wallet: must prove wallet ownership so a
                # node that a user runs can't be claimed by an unrelated wallet.
                if not await _verify_wallet_ownership(
                    db,
                    None,
                    wallet_addr,
                    node_in.owner_signature,
                    node_in.owner_message,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Binding a wallet to an existing node requires a valid wallet ownership signature.",
                    )
                existing.wallet_address = wallet_addr
                existing.secret_hash = secret_hash
            else:
                # Legacy node without a wallet: the node secret remains the ownership
                # credential and is never overwritten by a different value, otherwise
                # anyone could hijack a node by re-registering its UUID.
                if existing.secret_hash:
                    if existing.secret_hash != secret_hash:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Node is already registered with a different secret. Provide the original node secret to update it.",
                        )
                else:
                    existing.secret_hash = secret_hash
            db_node = existing
        else:
            # virtual-* node UUIDs are reserved for platform-created virtual nodes and must
            # not be claimable via the public registration endpoint.
            if node_in.node_uuid.startswith("virtual-"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="virtual-* node UUIDs are reserved for platform virtual nodes.",
                )
            # A wallet-derived node requires proof of wallet ownership at creation,
            # otherwise an attacker could pre-register a victim's wallet address and
            # later hijack the resulting referral/reward records.
            if wallet_addr and not await _verify_wallet_ownership(
                db, None, wallet_addr, node_in.owner_signature, node_in.owner_message
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Creating a wallet node requires a valid wallet ownership signature.",
                )
            # Transfer-safe adoption: if no node matches by the (deterministic)
            # node_uuid but another node already carries this wallet address (e.g. a
            # node created by an older build under a random uuid), adopt it under the
            # deterministic uuid instead of creating a duplicate wallet node. The
            # owner signature was verified above, so only the wallet holder can do this.
            adopted = None
            if wallet_addr:
                adopt_stmt = select(models.HubNode).where(
                    models.HubNode.wallet_address == wallet_addr
                )
                adopt_res = await db.execute(adopt_stmt)
                adopted = adopt_res.scalars().first()

            # Fall back to adopting a legacy (pre-wallet) node owned by the same
            # account: one registered under a random uuid WITHOUT a wallet_address.
            # Without this the wallet would get a brand-new node with a fresh referral
            # code while all mining history (telemetry, ledger, total_mined, referral
            # links) stays orphaned on the old uuid.
            if not adopted and wallet_addr:
                owner_user_id = await _find_user_id_by_wallet(db, wallet_addr)
                if owner_user_id:
                    legacy_uuid = await _resolve_user_node(db, owner_user_id)
                    if legacy_uuid and legacy_uuid != node_in.node_uuid:
                        legacy_res = await db.execute(
                            select(models.HubNode).where(
                                models.HubNode.node_uuid == legacy_uuid
                            )
                        )
                        legacy = legacy_res.scalars().first()
                        if legacy and not (legacy.wallet_address or "").strip():
                            adopted = legacy

            if adopted:
                adopted_old_uuid = adopted.node_uuid
                if adopted_old_uuid == node_in.node_uuid:
                    # Already at the deterministic uuid: just rotate the telemetry secret.
                    db_node = adopted
                    db_node.secret_hash = secret_hash
                else:
                    # Adopt FK-safely: create the deterministic node as a copy of the
                    # legacy node, re-key the mining history and referral links onto it,
                    # then drop the legacy row. (An in-place uuid rename would violate
                    # FK constraints on telemetry / ledger / server-config child rows.)
                    adopted_ref = adopted.node_referral_code
                    adopted.node_referral_code = None
                    adopted.wallet_address = None
                    await db.flush()
                    db_node = models.HubNode(
                        node_uuid=node_in.node_uuid,
                        name=adopted.name,
                        secret_hash=secret_hash,
                        node_referral_code=adopted_ref,
                        referrer_node_uuid=adopted.referrer_node_uuid,
                        total_mined=adopted.total_mined or 0.0,
                        has_welcome_bonus=adopted.has_welcome_bonus or False,
                        weex_uid=adopted.weex_uid,
                        okx_uid=getattr(adopted, "okx_uid", None),
                        wallet_address=wallet_addr or adopted.wallet_address,
                        is_operator=adopted.is_operator or False,
                        is_mining_server=adopted.is_mining_server or False,
                    )
                    db.add(db_node)
                    await db.flush()
                    # Re-point any referrer links that referenced the old uuid so the
                    # adopted node keeps its downstream referral structure intact.
                    await db.execute(
                        update(models.HubNode)
                        .where(models.HubNode.referrer_node_uuid == adopted_old_uuid)
                        .values(referrer_node_uuid=node_in.node_uuid)
                    )
                    # Re-key the mining history so telemetry and ledger entries follow
                    # the adopted node to its deterministic uuid instead of staying
                    # orphaned on the legacy uuid.
                    await db.execute(
                        update(models.HubTelemetryReport)
                        .where(models.HubTelemetryReport.node_uuid == adopted_old_uuid)
                        .values(node_uuid=node_in.node_uuid)
                    )
                    # Re-point per-server commission history too: reports mined
                    # THROUGH the adopted (mining-server) node must keep paying
                    # it at its new uuid. Without this, deleting the legacy row
                    # violates the source_node_uuid FK on PostgreSQL and aborts
                    # the whole registration.
                    await db.execute(
                        update(models.HubTelemetryReport)
                        .where(
                            models.HubTelemetryReport.source_node_uuid
                            == adopted_old_uuid
                        )
                        .values(source_node_uuid=node_in.node_uuid)
                    )
                    await db.execute(
                        update(models.MiningLedger)
                        .where(models.MiningLedger.node_uuid == adopted_old_uuid)
                        .values(node_uuid=node_in.node_uuid)
                    )
                    await db.execute(
                        update(models.HubServerConfig)
                        .where(models.HubServerConfig.node_uuid == adopted_old_uuid)
                        .values(node_uuid=node_in.node_uuid)
                    )
                    await db.delete(adopted)
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
                    weex_uid=node_in.weex_uid,
                    bybit_uid=node_in.bybit_uid,
                    okx_uid=node_in.okx_uid,
                    public_domain=node_in.public_domain,
                    wallet_address=wallet_addr,
                )
                db.add(db_node)

        db_node.name = node_in.name
        db_node.ip_address = ip
        db_node.latitude = geo["lat"]
        db_node.longitude = geo["lon"]
        db_node.city = geo["city"]
        db_node.country = geo["country"]
        db_node.version = node_in.version or "1.0.0"
        db_node.last_ping = datetime.now(timezone.utc)
        if node_in.weex_uid:
            db_node.weex_uid = node_in.weex_uid
        if node_in.okx_uid:
            db_node.okx_uid = node_in.okx_uid
        if node_in.public_domain:
            db_node.public_domain = node_in.public_domain

        if not db_node.node_referral_code:
            db_node.node_referral_code = f"DSN-REF-{node_in.node_uuid[:6].upper()}-{secrets.token_hex(3)[:4].upper()}"

        if allow_sensitive and node_in.is_mining_server:
            db_node.is_mining_server = True

        # Binding/changing the Bybit UID is an ownership-sensitive operation:
        # it anchors broker verification to a specific exchange account, so it
        # requires a valid wallet ownership signature (allow_sensitive).
        if allow_sensitive and node_in.bybit_uid:
            db_node.bybit_uid = node_in.bybit_uid

        if allow_referrer:
            ref_code = node_in.referrer_code
            if not ref_code and not db_node.referrer_node_uuid:
                # Platform-chain fallback: when the activation payload carries
                # no explicit referrer code (e.g. re-activation after a reset),
                # derive the referrer from the wallet owner's platform
                # referral relationship instead of silently leaving the node
                # unlinked (which zeroes the inviter's referral bonus).
                owner_id = await _resolve_wallet_node_owner(db, db_node.node_uuid)
                if owner_id:
                    owner = (
                        (
                            await db.execute(
                                select(models.User).where(models.User.id == owner_id)
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if owner and owner.referred_by_user_id:
                        inviter = (
                            (
                                await db.execute(
                                    select(models.User).where(
                                        models.User.id == owner.referred_by_user_id
                                    )
                                )
                            )
                            .scalars()
                            .first()
                        )
                        if inviter and inviter.referral_code:
                            # Skip if this code resolves back to THIS node
                            # (self-referral would abort registration inside
                            # _bind_referrer_once with a 400).
                            target_node = await _resolve_referrer_node(
                                db, inviter.referral_code
                            )
                            if target_node and target_node != db_node.node_uuid:
                                ref_code = inviter.referral_code

            if ref_code:
                await _bind_referrer_once(db, db_node, ref_code)

        # The reward-share percentage only affects the node's own commission and is
        # also carried by ping (which has no owner signature), so it stays ungated.
        if node_in.user_reward_share_percent is not None:
            await _upsert_server_config(
                db, db_node.node_uuid, node_in.user_reward_share_percent
            )

        if node_in.public_plans is not None:
            db_node.public_plans = node_in.public_plans

        try:
            await db.commit()
        except IntegrityError as ie:
            await db.rollback()
            logger.warning(
                f"Concurrent registration race for node {node_in.node_uuid}: {ie}"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent registration detected. Retry with current state.",
            )
        return {
            "status": "success",
            "message": "Node registered successfully",
            "node_referral_code": db_node.node_referral_code,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering hub node: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register node.",
        )


@router.post("/nodes/revoke-telemetry", status_code=status.HTTP_200_OK)
async def revoke_node_telemetry(
    payload: schemas.HubNodeRevokeTelemetry,
    db: AsyncSession = Depends(get_db),
):
    """
    Revokes the telemetry credential of a wallet-bound node.

    Only the wallet owner can revoke. After revocation the node secret is cleared
    and the node can no longer submit telemetry until the owner re-keys it through
    a wallet-signed registration.
    """
    node_uuid = (payload.node_uuid or "").strip()
    if not node_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing node_uuid.",
        )
    stmt = select(models.HubNode).where(models.HubNode.node_uuid == node_uuid)
    res = await db.execute(stmt)
    node = res.scalars().first()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found.",
        )
    if not node.wallet_address:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only wallet-bound nodes support telemetry revocation.",
        )
    if not await _verify_wallet_ownership(
        db,
        node,
        None,
        payload.owner_signature,
        payload.owner_message,
        purpose=OWNERSHIP_PURPOSE_REVOKE,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid wallet ownership signature.",
        )
    node.secret_hash = ""
    await db.commit()
    return {
        "status": "success",
        "message": "Node telemetry revoked. Re-register with a wallet signature to restore.",
    }


@router.post("/nodes/ping", status_code=status.HTTP_200_OK)
async def ping_hub_node(
    ping_in: schemas.HubNodePing,
    request: Request,
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
        if ping_in.public_domain:
            node.public_domain = ping_in.public_domain

        if ping_in.user_reward_share_percent is not None:
            await _upsert_server_config(
                db, node.node_uuid, ping_in.user_reward_share_percent
            )

        if ping_in.public_plans is not None:
            node.public_plans = ping_in.public_plans

        if ping_in.referrer_code and not node.referrer_node_uuid:
            try:
                await _bind_referrer_once(db, node, ping_in.referrer_code)
            except Exception as ref_err:
                logger.warning(
                    f"Could not bind referrer {ping_in.referrer_code} on ping for node {node.node_uuid}: {ref_err}"
                )

        # Auto-update IP and geolocation if server IP changed or coords missing
        client_ip = get_client_ip(request)
        if client_ip and (client_ip != node.ip_address or node.latitude is None):
            geo = await geolocate_ip(client_ip)
            if geo:
                node.ip_address = client_ip
                node.latitude = geo["lat"]
                node.longitude = geo["lon"]
                node.city = geo["city"]
                node.country = geo["country"]

        await db.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing heartbeat ping: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process heartbeat.",
        )


@router.get("/nodes", response_model=List[schemas.HubNodeResponse])
async def get_active_nodes(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stmt = select(models.HubNode).where(
            models.HubNode.last_ping >= cutoff, models.HubNode.is_banned.is_(False)
        )
        res = await db.execute(stmt)
        nodes = res.scalars().all()

        # Fetch server configs for reward share
        cfg_stmt = select(models.HubServerConfig)
        cfg_res = await db.execute(cfg_stmt)
        server_configs = {
            c.node_uuid: c.user_reward_share_percent for c in cfg_res.scalars().all()
        }

        # Active miners count per source node (last 24 hours)
        from sqlalchemy import func

        miner_stmt = (
            select(
                models.HubTelemetryReport.source_node_uuid,
                func.count(func.distinct(models.HubTelemetryReport.node_uuid)),
            )
            .where(
                models.HubTelemetryReport.created_at
                >= datetime.now(timezone.utc) - timedelta(days=1)
            )
            .group_by(models.HubTelemetryReport.source_node_uuid)
        )
        miner_res = await db.execute(miner_stmt)
        active_miners_map = {row[0]: row[1] for row in miner_res.all()}

        # Total mined tokens from MiningLedger per node (fallback for accumulated balances)
        ledger_stmt = select(
            models.MiningLedger.node_uuid,
            func.sum(models.MiningLedger.total_reward),
        ).group_by(models.MiningLedger.node_uuid)
        ledger_res = await db.execute(ledger_stmt)
        ledger_mined_map = {
            row[0]: float(row[1] or 0.0) for row in ledger_res.all() if row[0]
        }

        # Resolve server total mined for Central Master Hub across all miners on this server
        all_mined_stmt = select(func.sum(models.HubNode.total_mined))
        all_mined_res = await db.execute(all_mined_stmt)
        master_mined = float(all_mined_res.scalar() or 0.0)
        if master_mined == 0.0:
            ledger_total_stmt = select(func.sum(models.MiningLedger.total_reward))
            ledger_total_res = await db.execute(ledger_total_stmt)
            master_mined = float(ledger_total_res.scalar() or 0.0)

        # Total active miners on master server
        master_active_miners = len(active_miners_map)
        if master_active_miners == 0:
            master_active_miners = 1

        response_nodes = []

        master_geo = await get_master_hub_geo(request)
        master_domain = os.getenv("PUBLIC_DOMAIN") or "app.depthsight.pro"
        await plans_config.load_from_db(db)
        master_plans = plans_config.get_full_config().get("plans", {})

        response_nodes.append(
            schemas.HubNodeResponse(
                name="Central Master Hub",
                latitude=master_geo["lat"],
                longitude=master_geo["lon"],
                city=master_geo["city"],
                country=master_geo["country"],
                latency_ms=0.0,
                version=APP_VERSION,
                is_master=True,
                user_reward_share_percent=75.0,
                public_domain=master_domain,
                uptime_percent=99.99,
                active_miners=master_active_miners,
                total_mined=master_mined,
                is_mining_server=True,
                created_at=datetime(2025, 6, 1, tzinfo=timezone.utc).isoformat(),
                public_plans=master_plans,
            )
        )

        for n in nodes:
            # Simple uptime estimate: 99.5% if currently online
            last_ping_utc = (
                n.last_ping.replace(tzinfo=timezone.utc)
                if (n.last_ping and n.last_ping.tzinfo is None)
                else n.last_ping
            )
            uptime = 99.5 if last_ping_utc and last_ping_utc >= cutoff else 95.0
            created_str = n.created_at.isoformat() if n.created_at else None

            # Calculate total mined & active miners per node
            node_mined = n.total_mined or ledger_mined_map.get(n.node_uuid, 0.0)
            node_miners = active_miners_map.get(n.node_uuid, 0)
            if node_miners == 0 and last_ping_utc and last_ping_utc >= cutoff:
                node_miners = 1

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
                    user_reward_share_percent=server_configs.get(
                        n.node_uuid, 75.0 if n.is_mining_server else None
                    ),
                    public_domain=n.public_domain,
                    uptime_percent=uptime,
                    active_miners=node_miners,
                    total_mined=node_mined,
                    is_mining_server=n.is_mining_server,
                    created_at=created_str,
                    public_plans=n.public_plans,
                )
            )

        return response_nodes
    except Exception as e:
        logger.error(f"Error retrieving active nodes: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve network status.",
        )


async def _verify_node_credentials(
    db: AsyncSession,
    x_node_uuid: Optional[str],
    x_node_secret: Optional[str],
) -> models.HubNode:
    if not x_node_uuid or not x_node_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing node credentials headers.",
        )

    stmt = select(models.HubNode).where(models.HubNode.node_uuid == x_node_uuid)
    res = await db.execute(stmt)
    node = res.scalars().first()

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Node not registered."
        )

    if node.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Node is banned."
        )

    secret_hash = hashlib.sha256(x_node_secret.encode()).hexdigest()
    # An empty secret_hash means the telemetry credential was revoked (or never
    # provisioned). It must NEVER be auto-assigned here: anyone who knows only
    # the node_uuid could otherwise hijack the node by presenting an arbitrary
    # secret. Recovery goes through a wallet-signed registration instead.
    if not node.secret_hash or node.secret_hash != secret_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid node credentials.",
        )

    return node


@router.get("/mining/config", response_model=schemas.MiningConfigPublic)
async def get_mining_config(db: AsyncSession = Depends(get_db)):
    cfg = await _get_active_mining_config(db)
    return schemas.MiningConfigPublic(
        is_mining_enabled=cfg.is_mining_enabled,
        eligible_exchanges=cfg.eligible_exchanges,
        min_trade_duration_sec=cfg.min_trade_duration_sec,
        min_price_movement_percent=cfg.min_price_movement_percent,
        referral_mining_boost=cfg.referral_mining_boost,
        daily_emission_base=cfg.daily_emission_base,
        rebate_rates=cfg.rebate_rates or {},
    )


@router.post("/mining/config", status_code=status.HTTP_200_OK)
async def update_mining_config(
    payload: schemas.MiningConfigUpdate,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    admin_key = None
    is_authorized = False

    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]
        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            is_authorized = True
        else:
            # Check if token belongs to an admin user
            try:
                from .auth import get_current_user_from_token

                user = await get_current_user_from_token(admin_key, db)
                if user and user.role == "admin":
                    is_authorized = True
            except Exception:
                pass

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to configure mining settings.",
        )

    cfg = await _get_active_mining_config(db)

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(cfg, field, val)

    await db.commit()
    await db.refresh(cfg)
    return {
        "status": "success",
        "message": "Mining configuration updated successfully.",
    }


@router.get("/mining/status", response_model=schemas.MiningStatusResponse)
async def get_mining_status(
    x_node_uuid: Optional[str] = Header(None, alias="X-Node-UUID"),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
    db: AsyncSession = Depends(get_db),
):
    node = await _verify_node_credentials(db, x_node_uuid, x_node_secret)
    cfg = await _get_active_mining_config(db)

    from datetime import timezone
    import datetime as dt
    from sqlalchemy.sql import func

    today = dt.datetime.now(timezone.utc).date()

    # 1. Emission calculation with halving support
    days_since_launch = 0
    if cfg.launch_date:
        days_since_launch = max((today - cfg.launch_date).days, 0)
    halvings = days_since_launch // cfg.halving_interval_days
    daily_emission = cfg.daily_emission_base / (2**halvings)

    # 2. Today's total estimated rebates across all eligible trades
    today_start = dt.datetime.combine(today, dt.time.min, tzinfo=timezone.utc)
    stmt_rebates = select(
        func.sum(models.HubTelemetryReport.estimated_rebate_usdt)
    ).where(
        models.HubTelemetryReport.created_at >= today_start,
        models.HubTelemetryReport.is_mining_eligible.is_(True),
    )
    res_rebates = await db.execute(stmt_rebates)
    epoch_total_rebates = float(res_rebates.scalar() or 0.0)

    # 3. Participating nodes today
    stmt_nodes = select(
        func.count(func.distinct(models.HubTelemetryReport.node_uuid))
    ).where(
        models.HubTelemetryReport.created_at >= today_start,
        models.HubTelemetryReport.is_mining_eligible.is_(True),
    )
    res_nodes = await db.execute(stmt_nodes)
    participating_nodes = int(res_nodes.scalar() or 0)

    # 4. Your total mined (sum of ledger)
    stmt_total_mined = select(func.sum(models.MiningLedger.total_reward)).where(
        models.MiningLedger.node_uuid == node.node_uuid
    )
    res_total_mined = await db.execute(stmt_total_mined)
    your_total_mined = float(res_total_mined.scalar() or 0.0)

    # 4b. Volume stats for the node (used by local nodes to mirror hub display)
    stmt_vol = select(func.sum(models.HubTelemetryReport.trade_volume_usdt)).where(
        models.HubTelemetryReport.node_uuid == node.node_uuid,
        models.HubTelemetryReport.is_mining_eligible.is_(True),
    )
    res_vol = await db.execute(stmt_vol)
    your_total_volume = float(res_vol.scalar() or 0.0)

    stmt_server_vol = select(
        func.sum(models.HubTelemetryReport.trade_volume_usdt)
    ).where(models.HubTelemetryReport.is_mining_eligible.is_(True))
    res_server_vol = await db.execute(stmt_server_vol)
    server_total_volume = float(res_server_vol.scalar() or 0.0)

    stmt_epoch_rebates = select(
        func.sum(models.HubTelemetryReport.estimated_rebate_usdt)
    ).where(
        models.HubTelemetryReport.node_uuid == node.node_uuid,
        models.HubTelemetryReport.created_at >= today_start,
        models.HubTelemetryReport.is_mining_eligible.is_(True),
    )
    res_epoch_rebates = await db.execute(stmt_epoch_rebates)
    your_epoch_rebates = float(res_epoch_rebates.scalar() or 0.0)

    your_volume_share = (
        your_total_volume / server_total_volume if server_total_volume > 0.0 else 0.0
    )

    # 5. Live estimate of expected daily reward for today
    today_reports_stmt = select(models.HubTelemetryReport).where(
        models.HubTelemetryReport.created_at >= today_start,
        models.HubTelemetryReport.is_mining_eligible.is_(True),
    )
    today_reports_res = await db.execute(today_reports_stmt)
    today_reports = today_reports_res.scalars().all()

    your_epoch_reward = await estimate_live_epoch_reward(
        db, cfg, daily_emission, node.node_uuid, today_reports
    )

    return schemas.MiningStatusResponse(
        is_mining_enabled=cfg.is_mining_enabled,
        eligible_exchanges=cfg.eligible_exchanges,
        rebate_rates=cfg.rebate_rates or {},
        current_epoch_date=today.isoformat(),
        daily_emission=daily_emission,
        your_total_mined=your_total_mined,
        your_epoch_reward=your_epoch_reward,
        epoch_total_rebates=epoch_total_rebates,
        participating_nodes=participating_nodes,
        node_referral_code=node.node_referral_code,
        referrer_node_uuid=node.referrer_node_uuid,
        has_welcome_bonus=node.has_welcome_bonus,
        total_operator_fee_collected=cfg.total_operator_fee_collected or 0.0,
        your_total_volume=your_total_volume,
        server_total_volume=server_total_volume,
        your_epoch_rebates=your_epoch_rebates,
        your_volume_share=your_volume_share,
    )


async def get_mining_referrals_impl(
    db: AsyncSession,
    authorization: Optional[str] = None,
    x_node_uuid: Optional[str] = None,
    current_user_obj: Optional[models.User] = None,
) -> schemas.MiningReferralsResponse:
    try:
        if (
            not current_user_obj
            and authorization
            and authorization.startswith("Bearer ")
        ):
            token = authorization.split(" ")[1]
            try:
                from .auth import get_current_user_from_token

                current_user_obj = await get_current_user_from_token(token, db)
            except Exception as auth_err:
                logger.warning(f"Error extracting user in referrals: {auth_err}")

        from sqlalchemy import func

        # 1. Fetch User-level referrals
        ref_users = []
        if current_user_obj:
            stmt_user_refs = select(models.User).where(
                models.User.referred_by_user_id == current_user_obj.id
            )
            res_u_refs = await db.execute(stmt_user_refs)
            ref_users = res_u_refs.scalars().all()

        # 2. Fetch Node-level referrals
        ref_nodes = []
        possible_node_uuids = []
        if x_node_uuid:
            possible_node_uuids.append(x_node_uuid)

        if current_user_obj:
            if current_user_obj.referral_code:
                stmt_u_node = select(models.HubNode.node_uuid).where(
                    models.HubNode.node_referral_code == current_user_obj.referral_code
                )
                res_u_node = await db.execute(stmt_u_node)
                for nu in res_u_node.scalars().all():
                    if nu not in possible_node_uuids:
                        possible_node_uuids.append(nu)

            config = await crud.get_config_model(db, current_user_obj.id)
            if config and config.exchange_settings:
                settings = dict(config.exchange_settings)
                for ex_key in ("bybit", "okx", "weex", "binance", None):
                    d = settings.get(ex_key) if ex_key else settings
                    if isinstance(d, dict):
                        w_uuid = d.get("mining_node_uuid")
                        if w_uuid and w_uuid not in possible_node_uuids:
                            possible_node_uuids.append(w_uuid)
                        w_addr = d.get("wallet_address")
                        if w_addr:
                            import uuid as _uuid

                            w_node_uuid = str(
                                _uuid.uuid5(
                                    _uuid.NAMESPACE_DNS, f"evm:{w_addr.lower()}"
                                )
                            )
                            if w_node_uuid not in possible_node_uuids:
                                possible_node_uuids.append(w_node_uuid)

        if possible_node_uuids:
            stmt_node_refs = select(models.HubNode).where(
                models.HubNode.referrer_node_uuid.in_(possible_node_uuids)
            )
            res_node_refs = await db.execute(stmt_node_refs)
            ref_nodes = res_node_refs.scalars().all()

        seen_ids = set()
        items = []
        total_volume_sum = 0.0
        total_rewards_sum = 0.0
        active_count = 0
        now_utc = datetime.now(timezone.utc)

        # Process Referred Users
        for u in ref_users:
            seen_ids.add(str(u.id))
            user_display_name = u.username or (
                u.email.split("@")[0] if u.email else f"User-{u.id}"
            )

            stmt_user_hub_node = select(models.HubNode).where(
                models.HubNode.node_referral_code == u.referral_code
            )
            res_user_hub_node = await db.execute(stmt_user_hub_node)
            u_hub_node = res_user_hub_node.scalars().first()

            vol = 0.0
            mined_depth = 0.0
            bonus = 0.0
            has_welcome = False
            is_active = False

            if u_hub_node:
                seen_ids.add(u_hub_node.node_uuid)
                mined_depth = u_hub_node.total_mined or 0.0
                has_welcome = u_hub_node.has_welcome_bonus

                stmt_vol = select(
                    func.sum(models.HubTelemetryReport.trade_volume_usdt)
                ).where(
                    models.HubTelemetryReport.node_uuid == u_hub_node.node_uuid,
                    # Mirror the invitee's own "Your Total Volume" semantics:
                    # count only gate-passing (mining-eligible) trades.
                    models.HubTelemetryReport.is_mining_eligible.is_(True),
                )
                res_vol = await db.execute(stmt_vol)
                vol = float(res_vol.scalar() or 0.0)

                if possible_node_uuids:
                    stmt_bonus = select(
                        func.sum(models.MiningLedger.referral_bonus)
                    ).where(models.MiningLedger.node_uuid.in_(possible_node_uuids))
                    res_bonus = await db.execute(stmt_bonus)
                    bonus = float(res_bonus.scalar() or 0.0)

                stmt_cfg = select(models.AppConfig.is_mining_enabled).where(
                    models.AppConfig.user_id == u.id
                )
                res_cfg = await db.execute(stmt_cfg)
                is_mining_enabled = res_cfg.scalar() or False
                if is_mining_enabled:
                    is_active = True
                elif u_hub_node.last_ping:
                    ping_dt = u_hub_node.last_ping
                    if ping_dt.tzinfo is None:
                        ping_dt = ping_dt.replace(tzinfo=timezone.utc)
                    if (now_utc - ping_dt).total_seconds() < 600:
                        is_active = True

            if is_active:
                active_count += 1
            total_volume_sum += vol
            total_rewards_sum += bonus

            items.append(
                schemas.MiningReferralItem(
                    id=str(u.id),
                    name=user_display_name,
                    created_at=u.created_at.isoformat()
                    if u.created_at
                    else now_utc.isoformat(),
                    trade_volume_usdt=vol,
                    total_mined_depth=mined_depth,
                    referral_bonus_earned=bonus,
                    has_welcome_bonus=has_welcome,
                    status="active" if is_active else "idle",
                )
            )

        # Process Referred Nodes (not already processed)
        for r_node in ref_nodes:
            if r_node.node_uuid in seen_ids:
                continue
            seen_ids.add(r_node.node_uuid)

            stmt_vol = select(
                func.sum(models.HubTelemetryReport.trade_volume_usdt)
            ).where(
                models.HubTelemetryReport.node_uuid == r_node.node_uuid,
                # Eligible-only, consistent with the invitee's own volume card.
                models.HubTelemetryReport.is_mining_eligible.is_(True),
            )
            res_vol = await db.execute(stmt_vol)
            vol = float(res_vol.scalar() or 0.0)

            bonus = 0.0
            if possible_node_uuids:
                stmt_bonus = select(func.sum(models.MiningLedger.referral_bonus)).where(
                    models.MiningLedger.node_uuid.in_(possible_node_uuids)
                )
                res_bonus = await db.execute(stmt_bonus)
                bonus = float(res_bonus.scalar() or 0.0)

            is_active = False
            if r_node.last_ping:
                ping_dt = r_node.last_ping
                if ping_dt.tzinfo is None:
                    ping_dt = ping_dt.replace(tzinfo=timezone.utc)
                if (now_utc - ping_dt).total_seconds() < 600:
                    is_active = True

            if is_active:
                active_count += 1

            total_volume_sum += vol
            total_rewards_sum += bonus

            items.append(
                schemas.MiningReferralItem(
                    id=r_node.node_uuid,
                    name=r_node.name or f"Node-{r_node.node_uuid[:8]}",
                    created_at=r_node.created_at.isoformat()
                    if r_node.created_at
                    else now_utc.isoformat(),
                    trade_volume_usdt=vol,
                    total_mined_depth=r_node.total_mined or 0.0,
                    referral_bonus_earned=bonus,
                    has_welcome_bonus=r_node.has_welcome_bonus,
                    status="active" if is_active else "idle",
                )
            )

        return schemas.MiningReferralsResponse(
            total_invited=len(items),
            active_referrals=active_count,
            total_referral_rewards_depth=total_rewards_sum,
            total_referral_volume_usdt=total_volume_sum,
            referrals=items,
        )
    except Exception as e:
        logger.error(f"Error in get_mining_referrals_impl: {e}", exc_info=True)
        return schemas.MiningReferralsResponse(
            total_invited=0,
            active_referrals=0,
            total_referral_rewards_depth=0.0,
            total_referral_volume_usdt=0.0,
            referrals=[],
        )


@router.get("/mining/referrals", response_model=schemas.MiningReferralsResponse)
async def get_mining_referrals(
    authorization: Optional[str] = Header(None),
    x_node_uuid: Optional[str] = Header(None),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
    db: AsyncSession = Depends(get_db),
):
    # Resolve the authenticated user (if any) so they can see their own referrals.
    current_user_obj = None
    if authorization and authorization.startswith("Bearer "):
        try:
            from .auth import get_current_user_from_token

            token = authorization.split(" ")[1]
            current_user_obj = await get_current_user_from_token(token, db)
        except Exception as auth_err:
            logger.warning(f"Error extracting user in referrals: {auth_err}")

    # Node-scoped access requires valid node credentials. Without this, anyone
    # could read another node's referral list by spoofing X-Node-UUID. An
    # authenticated user querying their own node gets it via their referral code.
    if x_node_uuid:
        await _verify_node_credentials(db, x_node_uuid, x_node_secret)

    return await get_mining_referrals_impl(
        db=db,
        authorization=authorization,
        x_node_uuid=x_node_uuid,
        current_user_obj=current_user_obj,
    )


async def _verify_node_signature(
    db: AsyncSession,
    x_node_uuid: Optional[str],
    x_node_secret: Optional[str],
    x_node_signature: Optional[str],
    body_bytes: bytes,
    x_timestamp: Optional[str] = None,
) -> models.HubNode:
    if not x_node_uuid or not x_node_secret or not x_node_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing node credentials or signature headers.",
        )

    # Replay protection: when the client provides a request timestamp, reject
    # anything outside a 5-minute window. Absent header -> legacy behaviour
    # (older bots stay compatible; they are identified by the warning log).
    if x_timestamp:
        try:
            ts_ms = int(x_timestamp)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed X-Timestamp header.",
            )
        drift_ms = abs(int(time.time() * 1000) - ts_ms)
        if drift_ms > 300_000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stale request timestamp (possible replay).",
            )
    else:
        logger.debug("Telemetry request without X-Timestamp (legacy client).")

    stmt = select(models.HubNode).where(models.HubNode.node_uuid == x_node_uuid)
    res = await db.execute(stmt)
    node = res.scalars().first()

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Node not registered."
        )

    if node.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Node is banned."
        )

    # Verify secret. The node must have completed registration (secret_hash set).
    # We NEVER auto-assign a secret from the caller: that would let anyone claim a node
    # by simply presenting a fresh secret.
    secret_hash = hashlib.sha256(x_node_secret.encode()).hexdigest()
    if not node.secret_hash or node.secret_hash != secret_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid node credentials.",
        )

    # Verify HMAC-SHA256 signature of body_bytes using x_node_secret as key.
    # The raw secret must be provided because the hub only stores its sha256 hash,
    # which cannot be used to compute an HMAC. This is a deliberate trade-off: the
    # secret travels over TLS, but is never persisted server-side.
    expected_sig = hmac.new(
        x_node_secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(x_node_signature, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature. Telemetry payload may have been tampered.",
        )

    return node


def _node_owner_keys(node: Optional[models.HubNode]) -> set:
    """
    Returns a set of stable "owner" keys for a node.

    These are used to decide whether telemetry may be attributed to a node:
    a node may only attribute trades to itself or to another node owned by the
    same account (same user referral code, same Weex UID or same bound EVM wallet).
    """
    keys = set()
    if not node:
        return keys
    if node.node_referral_code:
        keys.add(f"ref:{node.node_referral_code}")
    if node.weex_uid:
        keys.add(f"weex:{node.weex_uid}")
    if node.wallet_address:
        keys.add(f"wallet:{node.wallet_address.strip().lower()}")
    return keys


async def _verify_attribution(
    db: AsyncSession,
    auth_node: models.HubNode,
    attribution_node_uuid: Optional[str],
) -> str:
    """
    Verifies that a telemetry report may be attributed to the given node.

    A node may attribute telemetry only to:
      * itself, or
      * a node owned by the same account (referral code / Weex UID / EVM wallet).

    Prevents clients from spoofing attribution to arbitrary other nodes.
    """
    if not attribution_node_uuid:
        return auth_node.node_uuid
    if attribution_node_uuid == auth_node.node_uuid:
        return attribution_node_uuid

    target_stmt = select(models.HubNode).where(
        models.HubNode.node_uuid == attribution_node_uuid
    )
    target_res = await db.execute(target_stmt)
    target_node = target_res.scalars().first()
    if target_node is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Attribution node is not registered.",
        )

    auth_keys = _node_owner_keys(auth_node)
    target_keys = _node_owner_keys(target_node)
    if auth_keys and auth_keys.intersection(target_keys):
        return attribution_node_uuid

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Attribution to another user's node is not allowed.",
    )


async def _verify_source_server(
    db: AsyncSession, source_node_uuid: Optional[str]
) -> Optional[str]:
    """Only nodes flagged as mining servers may act as a telemetry source."""
    if not source_node_uuid:
        return None
    stmt = select(models.HubNode).where(models.HubNode.node_uuid == source_node_uuid)
    res = await db.execute(stmt)
    node = res.scalars().first()
    if node is None or not node.is_mining_server:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Source server node is not a registered mining server.",
        )
    return source_node_uuid


async def _get_active_mining_config(db: AsyncSession) -> Optional[models.MiningConfig]:
    stmt = select(models.MiningConfig).limit(1)
    res = await db.execute(stmt)
    cfg = res.scalars().first()
    if not cfg:
        # Create default config
        cfg = models.MiningConfig(
            is_mining_enabled=False,
            eligible_exchanges=[
                "weex",
                "weex_futures",
                "weex_spot",
                "okx",
                "okx_futures",
                "okx_spot",
                "bybit",
                "bybit_futures",
                "bybit_spot",
            ],
            daily_emission_base=547945.21,
            halving_interval_days=365,
            min_trade_duration_sec=30,
            min_trade_pnl_abs=0.0,
            referral_mining_boost=0.10,
            rebate_rates={
                "weex_futures": 0.60,
                "weex_spot": 0.45,
                "weex": 0.60,
                "okx_futures": 0.30,
                "okx_spot": 0.30,
                "okx": 0.30,
                "bybit_futures": 0.50,
                "bybit_spot": 0.50,
                "bybit": 0.50,
                "binance_futures": 0.25,
            },
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


async def _find_user_id_by_wallet(
    db: AsyncSession, wallet_addr: Optional[str]
) -> Optional[int]:
    """Return the user_id whose AppConfig has this wallet bound as their mining wallet.

    Mirrors ``_resolve_wallet_node_owner`` but resolves by the wallet address stored
    in ``exchange_settings.weex.wallet_address`` (written by /node/wallet/verify),
    so a legacy account can be linked to a wallet even before a HubNode carries it.
    """
    if not wallet_addr:
        return None
    clean = wallet_addr.strip().lower()
    cfg_res = await db.execute(
        select(models.AppConfig).where(models.AppConfig.exchange_settings.isnot(None))
    )
    for cfg in cfg_res.scalars().all():
        weex = (cfg.exchange_settings or {}).get("weex") or {}
        bound = (weex.get("wallet_address") or "").strip().lower()
        if bound == clean:
            return cfg.user_id
    return None


async def _resolve_user_wallet_node(db: AsyncSession, user_id: int) -> Optional[str]:
    """Return the user's wallet-bound mining node UUID if it exists as a HubNode.

    The node identity is read from the user's AppConfig (exchange_settings.weex),
    which is what the wallet activation flow writes.
    """
    cfg_res = await db.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == user_id)
    )
    cfg = cfg_res.scalars().first()
    if not cfg or not cfg.exchange_settings:
        return None
    weex = (cfg.exchange_settings or {}).get("weex") or {}
    wallet_uuid = weex.get("mining_node_uuid")
    if not wallet_uuid:
        return None
    node_res = await db.execute(
        select(models.HubNode.node_uuid).where(models.HubNode.node_uuid == wallet_uuid)
    )
    if node_res.scalar():
        return wallet_uuid
    return None


async def _resolve_wallet_node_owner(
    db: AsyncSession, node_id: Optional[str]
) -> Optional[int]:
    """Return the user_id who owns the given wallet mining node.

    Inverse of ``_resolve_user_wallet_node``: scans AppConfig rows whose
    exchange_settings.weex.mining_node_uuid matches the node. Used because
    wallet-registered nodes carry a generated DSN-REF-* code that does not
    match ``User.referral_code``.
    """
    if not node_id:
        return None
    cfg_res = await db.execute(
        select(models.AppConfig).where(models.AppConfig.exchange_settings.isnot(None))
    )
    for cfg in cfg_res.scalars().all():
        weex = (cfg.exchange_settings or {}).get("weex") or {}
        if weex.get("mining_node_uuid") == node_id:
            return cfg.user_id
    return None


async def _resolve_user_node(db: AsyncSession, user_id: int) -> Optional[str]:
    """Resolve a user's mining node UUID (wallet node first, then referral-code link)."""
    wallet_uuid = await _resolve_user_wallet_node(db, user_id)
    if wallet_uuid:
        return wallet_uuid

    user_res = await db.execute(select(models.User).where(models.User.id == user_id))
    user = user_res.scalars().first()
    if user and user.referral_code:
        hn_res = await db.execute(
            select(models.HubNode.node_uuid)
            .where(models.HubNode.node_referral_code == user.referral_code)
            .limit(1)
        )
        real_uuid = hn_res.scalar()
        if real_uuid:
            return real_uuid

    return None


async def _resolve_mining_referrer(
    db: AsyncSession, node_id: Optional[str]
) -> Optional[str]:
    """
    Resolve the referrer node_uuid for a mining node, mirroring the daily epoch
    processor (tasks.py) so the live estimate credits the exact same nodes.

    Priority: the node's explicit referrer link, then the owner user's own
    referral relationship resolved to the referrer's mining node.

    Parity rules with tasks._resolve_referrer: self-references and banned
    referrer nodes yield None so the live estimate never exceeds the payout.
    """
    if not node_id:
        return None

    async def _valid_ref(candidate_uuid: Optional[str]) -> Optional[str]:
        if not candidate_uuid or candidate_uuid == node_id:
            return None
        b_res = await db.execute(
            select(models.HubNode.is_banned).where(
                models.HubNode.node_uuid == candidate_uuid
            )
        )
        if b_res.scalar():
            return None
        return candidate_uuid

    n_res = await db.execute(
        select(models.HubNode.referrer_node_uuid).where(
            models.HubNode.node_uuid == node_id
        )
    )
    ref_uuid = n_res.scalar()
    if ref_uuid:
        return await _valid_ref(ref_uuid)

    owner_user_id = await _resolve_wallet_node_owner(db, node_id)
    if not owner_user_id:
        code_res = await db.execute(
            select(models.HubNode.node_referral_code).where(
                models.HubNode.node_uuid == node_id
            )
        )
        code = code_res.scalar()
        if code:
            u_res = await db.execute(
                select(models.User).where(models.User.referral_code == code)
            )
            u = u_res.scalars().first()
            if u:
                owner_user_id = u.id

    if not owner_user_id:
        return None

    owner_res = await db.execute(
        select(models.User).where(models.User.id == owner_user_id)
    )
    owner = owner_res.scalars().first()
    if not owner or not owner.referred_by_user_id:
        return None

    return await _valid_ref(await _resolve_user_node(db, owner.referred_by_user_id))


async def _load_mining_share_config(
    db: AsyncSession,
):
    """
    Return (default_user_share, server_shares) mirroring tasks.py: the default
    share comes from NodeMiningConfig (safe fallback 75%), plus per-server
    shares registered via HubServerConfig.
    """
    node_cfg_res = await db.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    node_config_obj = node_cfg_res.scalar_one_or_none()
    if node_config_obj and node_config_obj.user_reward_share_percent > 0.0:
        share_pct = node_config_obj.user_reward_share_percent / 100.0
    else:
        share_pct = 0.75

    server_cfg_stmt = select(models.HubServerConfig)
    server_cfg_res = await db.execute(server_cfg_stmt)
    server_shares = {}
    for s_cfg in server_cfg_res.scalars().all():
        if s_cfg.user_reward_share_percent and s_cfg.user_reward_share_percent > 0.0:
            server_shares[s_cfg.node_uuid] = s_cfg.user_reward_share_percent / 100.0
    return share_pct, server_shares


async def _resolve_operator_root_id(db: AsyncSession) -> Optional[str]:
    """
    Resolve the hub operator root node (fee recipient for reports without a
    source server), mirroring tasks.py.

    Priority:
      1. A node explicitly flagged is_operator (manual override).
      2. The first admin (by registration) who bound a wallet mining node.
    """
    op_stmt = select(models.HubNode).where(models.HubNode.is_operator.is_(True))
    op_res = await db.execute(op_stmt)
    op_node = op_res.scalars().first()
    if op_node:
        return op_node.node_uuid

    admin_stmt = (
        select(models.User)
        .where(models.User.role == "admin")
        .order_by(models.User.id.asc())
    )
    admin_res = await db.execute(admin_stmt)
    for admin_user in admin_res.scalars().all():
        wallet_uuid = await _resolve_user_wallet_node(db, admin_user.id)
        if wallet_uuid:
            return wallet_uuid
    return None


async def estimate_live_epoch_reward(
    db: AsyncSession,
    cfg,
    daily_emission: float,
    target_node_uuid: Optional[str],
    reports,
) -> float:
    """
    Live estimate of today's mining reward for a node, matching the daily
    MiningLedger calculation: (gross base reward - node commission) + referral
    bonus. Welcome bonus is a one-time milestone grant and is excluded.

    Commission mirrors tasks.py: per report, the node keeps server_share of the
    gross base reward (default share from NodeMiningConfig / per-server from
    HubServerConfig); the rest is the operator/server commission. Referral
    bonuses are emission-pool bonuses and are NOT subject to commission.
    """
    if not reports or not target_node_uuid:
        return 0.0

    node_rebates = {}
    for rep in reports:
        nid = rep.node_uuid
        if not nid:
            continue
        node_rebates[nid] = node_rebates.get(nid, 0.0) + (
            rep.estimated_rebate_usdt or 0.0
        )
    if not node_rebates:
        return 0.0

    base_pts = {}
    ref_pts = {}
    total_pts = 0.0
    for nid, base_r in node_rebates.items():
        base_pts[nid] = base_pts.get(nid, 0.0) + base_r
        total_pts += base_r
        ref_uuid = await _resolve_mining_referrer(db, nid)
        if ref_uuid:
            rp = base_r * cfg.referral_mining_boost
            ref_pts[ref_uuid] = ref_pts.get(ref_uuid, 0.0) + rp
            total_pts += rp

    if total_pts <= 0:
        return 0.0

    token_per_pt = daily_emission / total_pts
    gross_base = base_pts.get(target_node_uuid, 0.0) * token_per_pt
    referral_bonus = ref_pts.get(target_node_uuid, 0.0) * token_per_pt
    if gross_base <= 0 and referral_bonus <= 0:
        return 0.0

    share_pct, server_shares = await _load_mining_share_config(db)

    target_total = node_rebates.get(target_node_uuid, 0.0)
    net_base = 0.0
    for rep in reports:
        if rep.node_uuid != target_node_uuid:
            continue
        rb = rep.estimated_rebate_usdt or 0.0
        if target_total <= 0 or rb <= 0:
            continue
        report_ratio = rb / target_total
        gross = gross_base * report_ratio
        server_share = server_shares.get(rep.source_node_uuid, share_pct)
        net_base += gross * server_share

    return net_base + referral_bonus


def score_trade_with_reason(
    report: schemas.TelemetryReportCreate, config: models.MiningConfig
) -> tuple[float, Optional[str]]:
    """
    Quality gate + weight. Returns (score, reject_reason).

    score == 0 means the trade is not mining-eligible and reject_reason holds
    a human-readable cause suitable for UI display (stored on the report as
    verification_error until/unless the broker verifier overrides it).
    """
    # 1. Must be a LIVE trade
    if report.trade_mode != "LIVE":
        return 0.0, "trade is not LIVE"

    # 2. Minimum hold time (anti-wash trading). A MISSING duration is treated
    # as a failure too — otherwise bots could bypass the gate by omitting it.
    if (
        not report.trade_duration_sec
        or report.trade_duration_sec < config.min_trade_duration_sec
    ):
        if not report.trade_duration_sec:
            return (
                0.0,
                f"missing trade duration (min {config.min_trade_duration_sec}s)",
            )
        return (
            0.0,
            f"hold time {report.trade_duration_sec}s < min "
            f"{config.min_trade_duration_sec}s",
        )

    # 3. Must have valid entry/exit prices
    if (
        not report.entry_price
        or not report.exit_price
        or report.entry_price <= 0
        or report.exit_price <= 0
    ):
        return 0.0, "invalid entry/exit prices"

    # 4. Minimum absolute price movement (anti-instant-exit): flat trades that
    # open and close at ~the same price do not qualify for mining.
    if config.min_price_movement_percent and config.min_price_movement_percent > 0:
        movement_percent = (
            abs(report.exit_price - report.entry_price) / report.entry_price * 100
        )
        if movement_percent < config.min_price_movement_percent:
            return (
                0.0,
                f"price movement {movement_percent:.3f}% < min "
                f"{config.min_price_movement_percent}%",
            )

    # Weight: longer duration gets a higher score up to 1.0 (cap at 1h)
    score = 1.0
    if report.trade_duration_sec:
        duration_factor = min(report.trade_duration_sec / 3600, 1.0)
        score *= 0.5 + 0.5 * duration_factor

    return round(score, 4), None


def _score_trade(
    report: schemas.TelemetryReportCreate, config: models.MiningConfig
) -> float:
    """
    Quality gate + weight for mining-eligible trades. Returns 0.0-1.0.

    A score of 0 makes the trade non-eligible (hard gate). The gates are:
    LIVE trade, minimum hold time (missing duration fails too), valid prices
    and minimum absolute price movement. The remaining 0.5-1.0 value weights
    longer-held trades; it is stored on the report but does NOT change payout
    size — rewards are proportional to verified rebate within the node.
    """
    score, _ = score_trade_with_reason(report, config)
    return score


def _estimate_rebate(
    report: schemas.TelemetryReportCreate, config: models.MiningConfig
) -> float:
    """
    Calculates estimated rebate in USDT based on volume and exchange rates.
    """
    if not report.trade_volume_usdt or report.trade_volume_usdt <= 0:
        return 0.0

    # Assume 0.05% average trading fee rate
    fee_rate = 0.0005

    exchange_key = report.exchange_id or "weex"
    market_key = report.market_type or "futures"

    lookup_key = f"{exchange_key}_{market_key}"
    rebate_rate = config.rebate_rates.get(lookup_key)
    if rebate_rate is None:
        rebate_rate = config.rebate_rates.get(exchange_key, 0.60)

    estimated_rebate = report.trade_volume_usdt * fee_rate * rebate_rate
    return round(estimated_rebate, 6)


@router.get("/mining/node-trades")
async def get_node_trades(
    page: int = 1,
    limit: int = 20,
    status_filter: Optional[str] = None,
    exchange: Optional[str] = None,
    search: Optional[str] = None,
    scope: Optional[str] = "all",
    x_node_uuid: Optional[str] = Header(None, alias="X-Node-UUID"),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Returns paginated telemetry trade reports for the authenticated node."""
    from sqlalchemy import func, or_
    import math

    node = await _verify_node_credentials(db, x_node_uuid, x_node_secret)

    # The node sees its own telemetry plus that of directly referred nodes
    # (referrer_node_uuid points back at this node), matching what the hub's
    # user-facing trades view shows.
    my_node_uuids = [node.node_uuid]
    ref_node_uuids = []
    ref_nodes_stmt = select(models.HubNode.node_uuid).where(
        models.HubNode.referrer_node_uuid == node.node_uuid
    )
    ref_nodes_res = await db.execute(ref_nodes_stmt)
    for nuuid in ref_nodes_res.scalars().all():
        if nuuid not in ref_node_uuids and nuuid not in my_node_uuids:
            ref_node_uuids.append(nuuid)

    stmt = select(models.HubTelemetryReport)
    if scope and scope.lower() == "my":
        filters = [models.HubTelemetryReport.node_uuid.in_(my_node_uuids)]
    elif scope and scope.lower() == "referrals":
        filters = [models.HubTelemetryReport.node_uuid.in_(ref_node_uuids or ["none"])]
    else:
        all_uuids = list(set(my_node_uuids + ref_node_uuids))
        filters = [models.HubTelemetryReport.node_uuid.in_(all_uuids)]

    if status_filter and status_filter.upper() != "ALL":
        filters.append(
            models.HubTelemetryReport.verification_status == status_filter.upper()
        )

    if exchange and exchange.lower() != "all":
        filters.append(
            func.lower(models.HubTelemetryReport.exchange_id) == exchange.lower()
        )

    if search:
        search_pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                models.HubTelemetryReport.symbol.ilike(search_pattern),
                models.HubTelemetryReport.broker_trade_id.ilike(search_pattern),
            )
        )

    if filters:
        stmt = stmt.where(*filters)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_res = await db.execute(count_stmt)
    total_count = count_res.scalar() or 0

    offset = (page - 1) * limit
    stmt = (
        stmt.order_by(models.HubTelemetryReport.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    reports = res.scalars().all()

    # Resolve a friendly display name for each telemetry's actual node, mirroring
    # the hub's user-facing trades view: the account that owns the referral code,
    # else the node name.
    report_node_uuids = {r.node_uuid for r in reports if r.node_uuid}
    name_map = {}
    if report_node_uuids:
        owner_stmt = (
            select(models.HubNode.node_uuid, models.User.username, models.User.email)
            .join(
                models.User,
                models.User.referral_code == models.HubNode.node_referral_code,
            )
            .where(models.HubNode.node_uuid.in_(report_node_uuids))
        )
        owner_res = await db.execute(owner_stmt)
        for nuuid, uname, uemail in owner_res.all():
            name_map[nuuid] = uname or (uemail.split("@")[0] if uemail else nuuid)

        for nuuid in report_node_uuids:
            if nuuid in name_map:
                continue
            hn_res = await db.execute(
                select(models.HubNode).where(models.HubNode.node_uuid == nuuid)
            )
            hn = hn_res.scalars().first()
            if hn and hn.name:
                name_map[nuuid] = hn.name
            else:
                name_map[nuuid] = nuuid

    items = []
    for r in reports:
        is_own = bool(r.node_uuid == node.node_uuid)
        items.append(
            {
                "id": str(r.id),
                "userId": None,
                "username": name_map.get(r.node_uuid, r.node_uuid or ""),
                "nodeUuid": r.node_uuid or "",
                "isOwnTrade": is_own,
                "symbol": r.symbol,
                "direction": r.direction,
                "exchangeId": r.exchange_id,
                "marketType": r.market_type,
                "tradeVolumeUsdt": r.trade_volume_usdt or 0.0,
                "brokerTradeId": r.broker_trade_id or "",
                "entryBrokerTradeIds": r.entry_broker_trade_ids or [],
                "closeBrokerTradeIds": r.close_broker_trade_ids or [],
                "verificationStatus": r.verification_status or "PENDING",
                "verificationError": r.verification_error,
                "verifiedVolumeUsdt": r.verified_volume_usdt,
                "isMiningEligible": bool(r.is_mining_eligible),
                "score": r.score,
                "rewardTokens": r.reward_tokens or 0.0,
                "createdAt": r.created_at.isoformat() if r.created_at else "",
            }
        )

    total_pages = math.ceil(total_count / limit) if limit > 0 else 1

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "totalPages": total_pages,
        "items": items,
    }


@router.post("/telemetry/report", status_code=status.HTTP_201_CREATED)
async def post_telemetry_report(
    request: Request,
    report: schemas.TelemetryReportCreate,
    x_node_uuid: Optional[str] = Header(None, alias="X-Node-UUID"),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
    x_node_signature: Optional[str] = Header(None, alias="X-Node-Signature"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    db: AsyncSession = Depends(get_db),
):
    """
    Submits authenticated anonymous trade telemetry data from a node.
    """
    body_bytes = await request.body()
    auth_node = await _verify_node_signature(
        db,
        x_node_uuid,
        x_node_secret,
        x_node_signature,
        body_bytes,
        x_timestamp=x_timestamp,
    )

    # Attribution is client-controlled; verify it resolves to the authenticated
    # node itself or to a node owned by the same account.
    resolved_attribution = await _verify_attribution(
        db, auth_node, report.attribution_node_uuid
    )

    # The source server is client-controlled too; only nodes flagged as mining
    # servers may be used (commission for this trade routes to that server).
    resolved_source = await _verify_source_server(db, report.source_node_uuid)

    mining_cfg = await _get_active_mining_config(db)
    is_mining_eligible = False
    score = 0.0
    estimated_rebate = 0.0
    gate_reason = None

    if mining_cfg and mining_cfg.is_mining_enabled:
        lookup_key = (
            f"{report.exchange_id}_{report.market_type}"
            if report.market_type
            else (report.exchange_id or "")
        )
        is_eligible_exchange = (
            report.exchange_id in mining_cfg.eligible_exchanges
        ) or (lookup_key in mining_cfg.eligible_exchanges)

        if is_eligible_exchange:
            score, gate_reason = score_trade_with_reason(report, mining_cfg)
            if score > 0.0:
                is_mining_eligible = True
                estimated_rebate = _estimate_rebate(report, mining_cfg)

    try:
        blocks_data = [
            {"type": b.type, "params": b.params} for b in report.strategy_blocks
        ]

        exch_lower = (report.exchange_id or "").lower()
        verifiable_exchanges = {"weex", "bybit", "okx"}
        initial_v_status = (
            "PENDING" if exch_lower in verifiable_exchanges else "SKIPPED"
        )

        db_report = None
        if report.broker_trade_id:
            existing_stmt = select(models.HubTelemetryReport).where(
                models.HubTelemetryReport.broker_trade_id == report.broker_trade_id
            )
            existing_res = await db.execute(existing_stmt)
            db_report = existing_res.scalar_one_or_none()

        if db_report:
            if db_report.node_uuid and db_report.node_uuid != resolved_attribution:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Trade with this broker_trade_id already exists for another node.",
                )
            # Once a report has been broker-verified and/or attributed to an epoch
            # (and paid from it), its data is frozen: a resubmission must never be
            # able to overwrite verified volume/rebate with unverified client-side
            # values (verification would NOT re-run on the new numbers).
            if (
                db_report.verification_status not in ("LOCAL_ONLY", "PENDING")
                or db_report.epoch_date is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Trade already verified/attribution; resubmission rejected.",
                )
            # Update existing LOCAL_ONLY/PENDING report
            db_report.symbol = report.symbol
            db_report.direction = report.direction
            db_report.entry_price = report.entry_price
            db_report.exit_price = report.exit_price
            db_report.pnl_percent = report.pnl_percent
            db_report.trade_duration_sec = report.trade_duration_sec
            db_report.exit_reason = report.exit_reason
            db_report.trade_mode = report.trade_mode
            db_report.timeframe = report.timeframe
            db_report.max_floating_profit = report.max_floating_profit
            db_report.max_floating_loss = report.max_floating_loss
            db_report.strategy_blocks = blocks_data
            db_report.market_context = report.market_context.model_dump()
            db_report.node_uuid = resolved_attribution
            db_report.source_node_uuid = resolved_source
            db_report.exchange_id = report.exchange_id
            db_report.market_type = report.market_type
            db_report.entry_broker_trade_ids = report.entry_broker_trade_ids
            db_report.close_broker_trade_ids = report.close_broker_trade_ids
            db_report.trade_volume_usdt = report.trade_volume_usdt
            db_report.score = score
            db_report.is_verified = initial_v_status == "SKIPPED"

            # Only upgrade status from LOCAL_ONLY to PENDING/SKIPPED
            if db_report.verification_status == "LOCAL_ONLY":
                db_report.verification_status = initial_v_status

            db_report.is_mining_eligible = is_mining_eligible
            db_report.estimated_rebate_usdt = estimated_rebate
            db_report.verification_error = gate_reason
        else:
            # Create new report
            db_report = models.HubTelemetryReport(
                symbol=report.symbol,
                direction=report.direction,
                entry_price=report.entry_price,
                exit_price=report.exit_price,
                pnl_percent=report.pnl_percent,
                trade_duration_sec=report.trade_duration_sec,
                exit_reason=report.exit_reason,
                trade_mode=report.trade_mode,
                timeframe=report.timeframe,
                max_floating_profit=report.max_floating_profit,
                max_floating_loss=report.max_floating_loss,
                strategy_blocks=blocks_data,
                market_context=report.market_context.model_dump(),
                node_uuid=resolved_attribution,
                source_node_uuid=resolved_source,
                exchange_id=report.exchange_id,
                market_type=report.market_type,
                broker_trade_id=report.broker_trade_id,
                entry_broker_trade_ids=report.entry_broker_trade_ids,
                close_broker_trade_ids=report.close_broker_trade_ids,
                trade_volume_usdt=report.trade_volume_usdt,
                score=score,
                is_verified=(initial_v_status == "SKIPPED"),
                verification_status=initial_v_status,
                is_mining_eligible=is_mining_eligible,
                estimated_rebate_usdt=estimated_rebate,
                verification_error=gate_reason,
            )
            db.add(db_report)

        await db.commit()
        return {
            "status": "success",
            "message": "Telemetry report submitted successfully.",
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.error(f"Error submitting telemetry report: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit telemetry report.",
        )


@router.get("/telemetry/insights", response_model=List[schemas.TelemetryInsightItem])
async def get_telemetry_insights(
    symbol: Optional[str] = None, days: int = 30, db: AsyncSession = Depends(get_db)
):
    """
    Aggregates trade telemetry data to return Swarm Intelligence insights.
    """
    try:
        time_limit = datetime.now(timezone.utc) - timedelta(days=days)
        query = select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.created_at >= time_limit
        )
        if symbol:
            query = query.where(models.HubTelemetryReport.symbol == symbol)

        result = await db.execute(query)
        reports = result.scalars().all()

        from collections import defaultdict

        combos = defaultdict(list)
        for r in reports:
            block_types = sorted(
                [b.get("type") for b in r.strategy_blocks if b.get("type")]
            )
            if not block_types:
                continue
            combo_key = " + ".join(block_types)
            combos[combo_key].append(r)

        insights = []
        for combo_key, r_list in combos.items():
            total_trades = len(r_list)
            if total_trades < 5:  # Require at least 5 trades to show insights
                continue

            winning_trades = sum(1 for r in r_list if (r.pnl_percent or 0) > 0)
            win_rate = (winning_trades / total_trades) * 100
            avg_pnl = sum(r.pnl_percent or 0.0 for r in r_list) / total_trades

            exit_reasons = defaultdict(int)
            for r in r_list:
                if r.exit_reason:
                    exit_reasons[r.exit_reason] += 1
            best_exits = sorted(
                exit_reasons.keys(), key=lambda k: exit_reasons[k], reverse=True
            )[:3]

            insights.append(
                schemas.TelemetryInsightItem(
                    combo_key=combo_key,
                    win_rate=round(win_rate, 2),
                    total_trades=total_trades,
                    avg_pnl_percent=round(avg_pnl, 4),
                    best_exit_reasons=best_exits,
                )
            )

        insights.sort(key=lambda x: x.win_rate, reverse=True)
        return insights
    except Exception as e:
        logger.error(f"Error calculating telemetry insights: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve swarm intelligence insights.",
        )


@router.post("/mining/process-epoch", status_code=status.HTTP_200_OK)
async def trigger_mining_epoch(
    authorization: Optional[str] = Header(None),
    epoch_date: Optional[str] = Body(default=None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin-only endpoint to manually trigger mining epoch processing.
    Verifies PENDING trades and distributes token rewards.

    `epoch_date` is an optional ISO date (YYYY-MM-DD) to process instead of
    yesterday (UTC). Only completed past days are accepted — today and the
    future are rejected to avoid finalizing a day that is not fully over.
    """
    admin_key = None
    is_authorized = False

    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]
        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            is_authorized = True
        else:
            try:
                from .auth import get_current_user_from_token

                user = await get_current_user_from_token(admin_key, db)
                if user and user.role == "admin":
                    is_authorized = True
            except Exception:
                pass

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to trigger mining epoch.",
        )

    force_date = None
    if epoch_date:
        try:
            force_date = date.fromisoformat(epoch_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid epoch_date format. Expected YYYY-MM-DD.",
            )
        if force_date >= datetime.now(timezone.utc).date():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="epoch_date must be a completed past day (before today UTC).",
            )
    else:
        lag_days = int(os.getenv("MINING_EPOCH_LAG_DAYS", "1"))
        force_date = datetime.now(timezone.utc).date() - timedelta(days=lag_days)

    try:
        from tasks import _async_process_mining_epoch

        await _async_process_mining_epoch(force_yesterday_date=force_date)
        return {"status": "success", "message": "Mining epoch processed successfully."}
    except Exception as e:
        logger.error(f"Error processing mining epoch: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process mining epoch: {e}",
        )


@router.post(
    "/nodes/designate-operator",
    status_code=status.HTTP_200_OK,
)
async def designate_operator_node(
    payload: schemas.HubNodeRegister,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin-only endpoint that explicitly marks a HubNode as the operator (root)
    node. Operator fees are credited to this node, never to an arbitrary first
    row of the table. Uses the same node secret as proof of ownership of the
    node being designated.
    """
    admin_key = None
    is_authorized = False

    if authorization and authorization.startswith("Bearer "):
        admin_key = authorization.split(" ")[1]
        if HUB_ADMIN_API_KEY and admin_key == HUB_ADMIN_API_KEY:
            is_authorized = True
        else:
            try:
                from .auth import get_current_user_from_token

                user = await get_current_user_from_token(admin_key, db)
                if user and user.role == "admin":
                    is_authorized = True
            except Exception:
                pass

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to designate operator node.",
        )

    try:
        secret_hash = hashlib.sha256(payload.node_secret.encode()).hexdigest()
        stmt = select(models.HubNode).where(
            models.HubNode.node_uuid == payload.node_uuid
        )
        res = await db.execute(stmt)
        node = res.scalars().first()
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Node not registered.",
            )
        if node.secret_hash and node.secret_hash != secret_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid node secret. Must provide the node's own secret.",
            )
        node.is_operator = True
        await db.commit()
        return {
            "status": "success",
            "message": f"Node {payload.node_uuid} is now the operator node.",
            "operator_node_uuid": node.node_uuid,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error designating operator node: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to designate operator node.",
        )
