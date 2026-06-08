import logging
from typing import Iterable

from fastapi import APIRouter, FastAPI


def include_application_routers(
    app: FastAPI,
    routers: Iterable[APIRouter],
    *,
    is_central_hub: bool,
    logger: logging.Logger,
) -> None:
    """Register API route groups after decorators have attached their endpoints."""
    for router in routers:
        app.include_router(router)

    if is_central_hub:
        try:
            from ..hub_router import router as hub_router

            app.include_router(hub_router)
            logger.info("Federation Hub router loaded successfully.")
        except ImportError as e:
            logger.error(f"Federation Hub router could not be loaded: {e}")

    try:
        from ..simulation_router import simulation_router

        app.include_router(
            simulation_router, prefix="/api/simulation", tags=["Simulation"]
        )
    except ImportError as e:
        logger.warning(f"Simulation router could not be loaded: {e}")

    try:
        from ..phantom_router import phantom_router

        app.include_router(phantom_router)
        logger.info("Phantom trade router loaded successfully.")
    except ImportError as e:
        logger.warning(f"Phantom trade router could not be loaded: {e}")
