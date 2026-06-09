# api/session_manager.py

import aiohttp
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends


class AiohttpSessionManager:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def start_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close_session(self):
        if self._session:
            await self._session.close()
            self._session = None

    def get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            # This should not happen in a running application
            raise RuntimeError(
                "Aiohttp session is not initialized. Call start_session() on app startup."
            )
        return self._session


session_manager = AiohttpSessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code to execute before application startup
    await session_manager.start_session()
    yield
    # Code to execute after application shutdown
    await session_manager.close_session()


# Dependency for endpoints
async def get_aiohttp_session() -> aiohttp.ClientSession:
    return session_manager.get_session()


# Remove redundant brackets () after get_aiohttp_session.
# Depends must receive the function itself, not the result of its call.
HttpSessDep = Depends(get_aiohttp_session)
