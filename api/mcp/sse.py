"""
Server-Sent Events (SSE) session manager for Model Context Protocol.
Maintains client queues, session lifecycles, and event streaming for Claude Desktop & Cursor.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

logger = logging.getLogger("depthsight.mcp.sse")


class SSESession:
    """Represents an active SSE connection session for an MCP client."""

    def __init__(self, session_id: str, user_id: int):
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = time.time()
        self.last_activity = time.time()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.is_active = True

    async def push_event(self, event_type: str, data: Any) -> None:
        """Pushes an SSE event to the client queue."""
        self.last_activity = time.time()
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data)
        else:
            data_str = str(data)

        # SSE wire format
        sse_payload = f"event: {event_type}\ndata: {data_str}\n\n"
        await self.queue.put(sse_payload)

    def touch(self) -> None:
        self.last_activity = time.time()


class SSESessionManager:
    """Registry and lifecycle manager for all active SSE connections."""

    def __init__(self, session_ttl_seconds: int = 1800):
        self.sessions: Dict[str, SSESession] = {}
        self.session_ttl = session_ttl_seconds
        self._lock = asyncio.Lock()

    async def create_session(self, user_id: int) -> SSESession:
        async with self._lock:
            session_id = uuid.uuid4().hex
            session = SSESession(session_id=session_id, user_id=user_id)
            self.sessions[session_id] = session
            logger.info(f"Created MCP SSE session {session_id} for user {user_id}")
            return session

    def get_session(self, session_id: str) -> Optional[SSESession]:
        session = self.sessions.get(session_id)
        if session:
            session.touch()
        return session

    async def remove_session(self, session_id: str) -> None:
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions.pop(session_id)
                session.is_active = False
                logger.info(f"Closed MCP SSE session {session_id}")

    async def stream_session(
        self, session: SSESession, messages_endpoint: str
    ) -> AsyncGenerator[str, None]:
        """Generator that streams SSE events and keep-alives to the HTTP client."""
        # 1. First event: notify client of the POST endpoint for message transmission
        yield f"event: endpoint\ndata: {messages_endpoint}?session_id={session.session_id}\n\n"

        # 2. Main event loop with heartbeat keepalive
        heartbeat_interval = 15.0

        try:
            while session.is_active:
                try:
                    payload = await asyncio.wait_for(
                        session.queue.get(), timeout=heartbeat_interval
                    )
                    yield payload
                    session.queue.task_done()
                except asyncio.TimeoutError:
                    # Send lightweight heartbeat comment to keep the TCP connection alive
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            logger.debug(f"MCP SSE client connection cancelled: {session.session_id}")
        finally:
            await self.remove_session(session.session_id)


# Global singleton instance
sse_session_manager = SSESessionManager()
