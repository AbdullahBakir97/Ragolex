import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ragolex.api.dependencies import EngineDep, SettingsDep
from ragolex.api.schemas import HealthResponse, WelcomeResponse
from ragolex.persistence.database import is_database_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["base"])


@router.get("/", summary="Service name and version")
async def welcome(settings: SettingsDep) -> WelcomeResponse:
    return WelcomeResponse(
        message="Hello All",
        app_name=settings.APP_NAME,
        app_version=settings.APP_VERSION,
    )


@router.get(
    "/health",
    summary="Health check for load balancers and orchestrators",
    response_model=HealthResponse,
    responses={503: {
        "model": HealthResponse,
        "description": "The database is unreachable",
        "content": {"application/json": {
            "example": {"status": "unavailable", "database": "unavailable"}}},
    }},
)
async def health(engine: EngineDep) -> HealthResponse | JSONResponse:
    if await is_database_available(engine):
        return HealthResponse(status="ok", database="ok")

    logger.warning("Health check failed: database unavailable")
    unhealthy = HealthResponse(status="unavailable", database="unavailable")
    return JSONResponse(status_code=503, content=unhealthy.model_dump())
