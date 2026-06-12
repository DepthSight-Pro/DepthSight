# tests/test_hub_api.py
import pytest
from httpx import AsyncClient
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    """
    Dynamically registers the hub router on the app if it was not loaded on startup
    due to IS_CENTRAL_HUB being False by default.
    """
    has_hub = any(route.path.startswith("/api/v1/hub") for route in app.routes)
    if not has_hub:
        app.include_router(hub_router)


async def test_get_hub_strategies(test_client: AsyncClient):
    """
    Test retrieving strategy templates from the Hub.
    """
    response = await test_client.get("/api/v1/hub/strategies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Genetic Scalper"
    assert "strategy_json" in data[0]
    assert data[0]["strategy_json"]["strategy_name"] == "GeneticScalp"


async def test_get_hub_news(test_client: AsyncClient):
    """
    Test retrieving news and updates from the Hub.
    """
    response = await test_client.get("/api/v1/hub/news")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert "title" in data[0]
    assert "text" in data[0]


async def test_post_hub_feedback(test_client: AsyncClient, db_session: AsyncSession):
    """
    Test submitting feedback and verifying it is saved in the database,
    along with a corresponding support ticket linked to the admin user.
    """
    # Create a mock admin user
    mock_admin = models.User(
        username="admin_tester",
        email="admin_tester@example.com",
        hashed_password="fakehashpassword",
        role="admin",
        plan="pro",
        xp=0,
        level=1,
    )
    db_session.add(mock_admin)
    await db_session.commit()

    payload = {
        "category": "bug",
        "text": "This is a test feedback message about a bug.",
        "contact_email": "tester@example.com",
    }
    response = await test_client.post("/api/v1/hub/feedback", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "success"

    # Query DB to check if feedback was stored
    result = await db_session.execute(
        select(models.HubFeedback).filter(
            models.HubFeedback.contact_email == "tester@example.com"
        )
    )
    feedback_in_db = result.scalars().first()
    assert feedback_in_db is not None
    assert feedback_in_db.category == "bug"
    assert feedback_in_db.text == "This is a test feedback message about a bug."
    assert feedback_in_db.contact_email == "tester@example.com"

    # Query DB to check if corresponding SupportTicket was created
    ticket_result = await db_session.execute(
        select(models.SupportTicket).filter(
            models.SupportTicket.user_id == mock_admin.id
        )
    )
    ticket_in_db = ticket_result.scalars().first()
    assert ticket_in_db is not None
    assert ticket_in_db.subject == "[Hub Feedback] BUG"
    assert ticket_in_db.category == "bug"
    assert "This is a test feedback message about a bug." in ticket_in_db.description
    assert "tester@example.com" in ticket_in_db.description


async def test_create_and_get_hub_topics(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Test creating both strategy and discussion topics, and then retrieving them.
    """
    strategy_payload = {
        "topic_type": "strategy",
        "title": "EMA Cross Strategy",
        "description": "A strategy using 9 and 21 EMA crossover.",
        "author_name": "QuantTrader",
        "symbol": "BTCUSDT",
        "period_start": "2026-01-01",
        "period_end": "2026-06-01",
        "kpis": {
            "total_pnl": 15.6,
            "win_rate": 0.58,
            "max_drawdown": 0.05,
            "sharpe_ratio": 1.8,
            "trades": 42,
        },
        "equity_curve": [[1767225600000, 10000], [1767312000000, 10156]],
        "strategy_json": {"strategy_name": "EmaCross", "symbol": "BTCUSDT"},
    }
    response = await test_client.post("/api/v1/hub/topics", json=strategy_payload)
    assert response.status_code == 201
    strategy_data = response.json()
    assert strategy_data["title"] == "EMA Cross Strategy"
    assert strategy_data["author_name"] == "QuantTrader"
    assert strategy_data["kpis"]["total_pnl"] == 15.6

    discussion_payload = {
        "topic_type": "discussion",
        "title": "Market Sentiment Thread",
        "description": "What do you think about the current market direction?",
        "author_name": "BullishJohn",
    }
    response = await test_client.post("/api/v1/hub/topics", json=discussion_payload)
    assert response.status_code == 201
    discussion_data = response.json()
    assert discussion_data["title"] == "Market Sentiment Thread"

    # Fetch strategy topics
    response = await test_client.get("/api/v1/hub/topics?type=strategy")
    assert response.status_code == 200
    topics = response.json()
    assert any(t["id"] == strategy_data["id"] for t in topics)

    # Fetch discussion topics
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    assert response.status_code == 200
    topics = response.json()
    assert any(t["id"] == discussion_data["id"] for t in topics)


async def test_like_hub_topic(test_client: AsyncClient, db_session: AsyncSession):
    """
    Test liking a topic increases its likes_count.
    """
    topic_payload = {
        "topic_type": "discussion",
        "title": "Like Test",
        "description": "Testing upvote counts.",
        "author_name": "Tester",
    }
    response = await test_client.post("/api/v1/hub/topics", json=topic_payload)
    topic_id = response.json()["id"]

    # Initial like count is 0
    assert response.json()["likes_count"] == 0

    # Like the topic
    response = await test_client.post(f"/api/v1/hub/topics/{topic_id}/like")
    assert response.status_code == 200
    assert response.json()["likes_count"] == 1

    # Like the topic again
    response = await test_client.post(f"/api/v1/hub/topics/{topic_id}/like")
    assert response.status_code == 200
    assert response.json()["likes_count"] == 2


async def test_create_and_get_comments(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Test creating comments for a topic and fetching the comment thread.
    """
    topic_payload = {
        "topic_type": "discussion",
        "title": "Comment Thread Test",
        "description": "Testing comments retrieval.",
        "author_name": "CommentTester",
    }
    response = await test_client.post("/api/v1/hub/topics", json=topic_payload)
    topic_id = response.json()["id"]

    comment_payload = {"author_name": "ReplyUser", "text": "This is a great idea!"}
    response = await test_client.post(
        f"/api/v1/hub/topics/{topic_id}/comments", json=comment_payload
    )
    assert response.status_code == 201
    comment_data = response.json()
    assert comment_data["author_name"] == "ReplyUser"
    assert comment_data["text"] == "This is a great idea!"
    assert comment_data["topic_id"] == topic_id

    # Retrieve comment thread
    response = await test_client.get(f"/api/v1/hub/topics/{topic_id}/comments")
    assert response.status_code == 200
    comments_list = response.json()
    assert len(comments_list) == 1
    assert comments_list[0]["text"] == "This is a great idea!"

    # Verify that comments_count is populated on the topic list
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    assert response.status_code == 200
    topics = response.json()
    matched_topic = next(t for t in topics if t["id"] == topic_id)
    assert matched_topic["comments_count"] == 1


async def test_delete_hub_topic(
    test_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """
    Test creating a topic, verifying delete_token behaves correctly,
    and deleting the topic as owner and as admin.
    """
    # 1. Create a topic
    payload = {
        "topic_type": "discussion",
        "title": "To Be Deleted",
        "description": "This topic will be deleted.",
        "author_name": "Ghost",
    }
    response = await test_client.post("/api/v1/hub/topics", json=payload)
    assert response.status_code == 201
    creation_data = response.json()
    assert "delete_token" in creation_data
    delete_token = creation_data["delete_token"]
    topic_id = creation_data["id"]

    # 2. Get topics list and verify delete_token is NOT leaked
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    assert response.status_code == 200
    topics = response.json()
    matched = next(t for t in topics if t["id"] == topic_id)
    assert "delete_token" not in matched

    # 3. Attempt deletion without token
    response = await test_client.delete(f"/api/v1/hub/topics/{topic_id}")
    assert response.status_code == 403

    # 4. Attempt deletion with wrong token
    response = await test_client.delete(
        f"/api/v1/hub/topics/{topic_id}?delete_token=wrong-token"
    )
    assert response.status_code == 403

    # 5. Delete with correct token
    response = await test_client.delete(
        f"/api/v1/hub/topics/{topic_id}?delete_token={delete_token}"
    )
    assert response.status_code == 204

    # Verify topic is gone
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    topics = response.json()
    assert not any(t["id"] == topic_id for t in topics)

    # 6. Test Admin deletion using monkeypatched HUB_ADMIN_API_KEY
    from api import hub_router

    monkeypatch.setattr(hub_router, "HUB_ADMIN_API_KEY", "super-secret-admin-key")

    # Create another topic
    response = await test_client.post("/api/v1/hub/topics", json=payload)
    assert response.status_code == 201
    topic_id_2 = response.json()["id"]

    # Delete using admin key via header
    headers = {"Authorization": "Bearer super-secret-admin-key"}
    response = await test_client.delete(
        f"/api/v1/hub/topics/{topic_id_2}", headers=headers
    )
    assert response.status_code == 204

    # Verify it is gone
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    topics = response.json()
    assert not any(t["id"] == topic_id_2 for t in topics)


async def test_admin_manage_presets_and_news(
    test_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """
    Test that verified strategies and news items are dynamically returned,
    that they are seeded on empty state, and that only admin can add/delete them.
    """
    # 1. Verify GET routes seed database and return results
    response = await test_client.get("/api/v1/hub/strategies")
    assert response.status_code == 200
    strats = response.json()
    assert len(strats) >= 3
    assert strats[0]["name"] == "Genetic Scalper"

    response = await test_client.get("/api/v1/hub/news")
    assert response.status_code == 200
    news = response.json()
    assert len(news) >= 3
    assert news[-1]["title"] == "DepthSight Federation Hub Phase 1 Released"

    # Set admin key
    from api import hub_router

    monkeypatch.setattr(hub_router, "HUB_ADMIN_API_KEY", "super-secret-admin-key")
    headers = {"Authorization": "Bearer super-secret-admin-key"}

    # 2. Test publishing news as non-admin vs admin
    news_payload = {
        "title": "New Update 2.0",
        "date": "2026-06-04",
        "text": "This is a new test update.",
    }
    response = await test_client.post("/api/v1/hub/news", json=news_payload)
    assert response.status_code == 403

    response = await test_client.post(
        "/api/v1/hub/news", json=news_payload, headers=headers
    )
    assert response.status_code == 201
    created_news = response.json()
    assert created_news["title"] == "New Update 2.0"
    news_id = created_news["id"]

    # Verify news list contains the new update
    response = await test_client.get("/api/v1/hub/news")
    assert any(item["id"] == news_id for item in response.json())

    # 3. Test deleting news as non-admin vs admin
    response = await test_client.delete(f"/api/v1/hub/news/{news_id}")
    assert response.status_code == 403

    response = await test_client.delete(f"/api/v1/hub/news/{news_id}", headers=headers)
    assert response.status_code == 204

    # Verify news is deleted
    response = await test_client.get("/api/v1/hub/news")
    assert not any(item["id"] == news_id for item in response.json())

    # 4. Test publishing strategy template as non-admin vs admin
    strategy_payload = {
        "name": "Super Strategy",
        "author": "Tester",
        "tags": ["Test"],
        "description": "Test template.",
        "strategy_json": {"test": True},
    }
    response = await test_client.post("/api/v1/hub/strategies", json=strategy_payload)
    assert response.status_code == 403

    response = await test_client.post(
        "/api/v1/hub/strategies", json=strategy_payload, headers=headers
    )
    assert response.status_code == 201
    created_strat = response.json()
    strat_id = created_strat["id"]

    # Verify strategies list contains the new strategy
    response = await test_client.get("/api/v1/hub/strategies")
    assert any(s["id"] == strat_id for s in response.json())

    # 5. Test deleting strategy as non-admin vs admin
    response = await test_client.delete(f"/api/v1/hub/strategies/{strat_id}")
    assert response.status_code == 403

    response = await test_client.delete(
        f"/api/v1/hub/strategies/{strat_id}", headers=headers
    )
    assert response.status_code == 204

    # Verify strategy is deleted
    response = await test_client.get("/api/v1/hub/strategies")
    assert not any(s["id"] == strat_id for s in response.json())


async def test_hub_ticket_chat(test_client: AsyncClient, db_session: AsyncSession):
    """
    Test the complete ticket chat flow for a remote hub user.
    """
    # 1. Create a mock user
    mock_user = models.User(
        username="support_user",
        email="support_user@example.com",
        hashed_password="fakehashpassword",
        role="admin",
        plan="pro",
        xp=0,
        level=1,
    )
    db_session.add(mock_user)
    await db_session.commit()

    # 2. Submit feedback via Hub endpoint
    payload = {
        "category": "bug",
        "text": "Hub chat ticket test.",
        "contact_email": "user@remote.com",
    }
    response = await test_client.post("/api/v1/hub/feedback", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert "ticket_id" in data
    ticket_id = data["ticket_id"]
    assert ticket_id is not None

    # 3. Retrieve status of the ticket from Hub endpoint
    status_res = await test_client.get(f"/api/v1/hub/tickets/{ticket_id}/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "OPEN"
    assert status_data["category"] == "bug"

    # 4. Post reply from the remote user via Hub endpoint
    msg_payload = {"text": "Hello, any update on this?", "senderName": "RemoteUser"}
    msg_res = await test_client.post(
        f"/api/v1/hub/tickets/{ticket_id}/messages", json=msg_payload
    )
    assert msg_res.status_code == 201
    msg_data = msg_res.json()
    assert msg_data["text"] == "Hello, any update on this?"
    assert msg_data["senderName"] == "RemoteUser"
    assert msg_data["isAdmin"] is False

    # 5. Fetch message list from Hub endpoint
    list_res = await test_client.get(f"/api/v1/hub/tickets/{ticket_id}/messages")
    assert list_res.status_code == 200
    messages = list_res.json()
    assert len(messages) == 1
    assert messages[0]["text"] == "Hello, any update on this?"

    # 6. Update ticket status (e.g. resolve/close it) from Hub endpoint
    update_res = await test_client.patch(
        f"/api/v1/hub/tickets/{ticket_id}/status", json={"status": "CLOSED"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "CLOSED"


async def test_hub_node_lifecycle(test_client: AsyncClient, db_session: AsyncSession):
    """
    Test registering a node, pinging it, and retrieving active nodes.
    """
    # 1. Register a new node
    reg_payload = {
        "node_uuid": "test-node-uuid-12345",
        "name": "Test Federated Node",
        "node_secret": "my-super-secret-key-123",
        "version": "1.2.3",
    }
    response = await test_client.post("/api/v1/hub/nodes/register", json=reg_payload)
    assert response.status_code == 201
    assert response.json()["status"] == "success"

    # 2. Ping the node
    headers = {
        "X-Node-UUID": "test-node-uuid-12345",
        "X-Node-Secret": "my-super-secret-key-123",
    }
    ping_payload = {"latency_ms": 25.4, "version": "1.2.4"}
    ping_res = await test_client.post(
        "/api/v1/hub/nodes/ping", json=ping_payload, headers=headers
    )
    assert ping_res.status_code == 200
    assert ping_res.json()["status"] == "success"

    # 3. Retrieve active nodes
    nodes_res = await test_client.get("/api/v1/hub/nodes")
    assert nodes_res.status_code == 200
    nodes_list = nodes_res.json()

    # It must contain the Central Master Hub (Frankfurt) and our test node
    assert len(nodes_list) >= 2

    master_node = next((n for n in nodes_list if n["is_master"]), None)
    assert master_node is not None
    assert master_node["name"] == "Central Master Hub"

    test_node = next(
        (n for n in nodes_list if n["name"] == "Test Federated Node"), None
    )
    assert test_node is not None
    assert test_node["latency_ms"] == 25.4
    assert test_node["version"] == "1.2.4"
    assert test_node["is_master"] is False


async def test_hub_news_interactions(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Test liking and commenting on a news item.
    """
    # 1. Fetch news to get a valid news id
    response = await test_client.get("/api/v1/hub/news")
    assert response.status_code == 200
    news_list = response.json()
    assert len(news_list) >= 1

    # Verify sorting: the first news item (index 0) should be the latest added,
    # which has the highest ID/date (seeding adds them in order, so highest id should be at the top)
    assert news_list[0]["id"] > news_list[-1]["id"]

    news_id = news_list[0]["id"]

    # 2. Like the news item
    like_res = await test_client.post(f"/api/v1/hub/news/{news_id}/like")
    assert like_res.status_code == 200
    assert like_res.json()["likes_count"] == 1

    # 3. Post a comment on the news item
    comment_payload = {
        "author_name": "NewsCommenter",
        "text": "This is a great update!",
    }
    comment_res = await test_client.post(
        f"/api/v1/hub/news/{news_id}/comments", json=comment_payload
    )
    assert comment_res.status_code == 201
    assert comment_res.json()["author_name"] == "NewsCommenter"
    assert comment_res.json()["text"] == "This is a great update!"
    assert comment_res.json()["news_id"] == news_id

    # 4. Retrieve comments for the news item
    get_comments_res = await test_client.get(f"/api/v1/hub/news/{news_id}/comments")
    assert get_comments_res.status_code == 200
    comments_list = get_comments_res.json()
    assert len(comments_list) == 1
    assert comments_list[0]["text"] == "This is a great update!"

    # 5. Fetch news again and verify counts are updated
    news_res_2 = await test_client.get("/api/v1/hub/news")
    target_news = next((n for n in news_res_2.json() if n["id"] == news_id), None)
    assert target_news is not None
    assert target_news["likes_count"] == 1
    assert target_news["comments_count"] == 1


async def test_admin_signature_highlighting(
    test_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """
    Test that when a comment or topic is posted by the admin (passing Authorization header),
    the username is cryptographically signed, and when retrieved, the signature is validated,
    stripped, and the response is marked with is_admin: True.
    """
    from api import hub_router

    monkeypatch.setattr(hub_router, "HUB_ADMIN_API_KEY", "super-secret-admin-key")
    headers = {"Authorization": "Bearer super-secret-admin-key"}

    # 1. Create a topic as admin
    topic_payload = {
        "topic_type": "discussion",
        "title": "Admin Discussion",
        "description": "Discussion from the central hub admin.",
        "author_name": "AdminUser",
    }
    response = await test_client.post(
        "/api/v1/hub/topics", json=topic_payload, headers=headers
    )
    assert response.status_code == 201
    topic_data = response.json()
    assert topic_data["author_name"] == "AdminUser"
    assert topic_data["is_admin"] is True
    topic_id = topic_data["id"]

    # Verify how it is stored in DB
    result = await db_session.execute(
        select(models.HubTopic).filter(models.HubTopic.id == topic_id)
    )
    topic_in_db = result.scalars().first()
    assert topic_in_db is not None
    # author_name should have [a:<sig>] suffix
    assert topic_in_db.author_name != "AdminUser"
    assert "[a:" in topic_in_db.author_name

    # 2. Get topics list and verify clean name + is_admin: True
    response = await test_client.get("/api/v1/hub/topics?type=discussion")
    assert response.status_code == 200
    topics = response.json()
    matched = next(t for t in topics if t["id"] == topic_id)
    assert matched["author_name"] == "AdminUser"
    assert matched["is_admin"] is True

    # 3. Post a comment as admin
    comment_payload = {"author_name": "AdminUser", "text": "Admin comment reply."}
    response = await test_client.post(
        f"/api/v1/hub/topics/{topic_id}/comments", json=comment_payload, headers=headers
    )
    assert response.status_code == 201
    comment_data = response.json()
    assert comment_data["author_name"] == "AdminUser"
    assert comment_data["is_admin"] is True
    comment_id = comment_data["id"]

    # Verify comment in DB has signature
    result = await db_session.execute(
        select(models.HubComment).filter(models.HubComment.id == comment_id)
    )
    comment_in_db = result.scalars().first()
    assert "[a:" in comment_in_db.author_name

    # 4. Get comments list and verify clean name + is_admin: True
    response = await test_client.get(f"/api/v1/hub/topics/{topic_id}/comments")
    assert response.status_code == 200
    comments = response.json()
    matched_c = next(c for c in comments if c["id"] == comment_id)
    assert matched_c["author_name"] == "AdminUser"
    assert matched_c["is_admin"] is True
