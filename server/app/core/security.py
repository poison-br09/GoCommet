import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

_api_key_scheme = APIKeyHeader(
    name="x-api-key",
    scheme_name="ApiKeyAuth",
    description="API key required for all endpoints. Pass as the `x-api-key` header.",
    auto_error=True,
)


async def require_api_key(api_key: str = Security(_api_key_scheme)) -> str:
    expected = settings.api_key.get_secret_value()
    if not secrets.compare_digest(api_key.encode(), expected.encode()):
        log.warning(
            "AUTH FAILED  |  received key length=%d  expected key length=%d  "
            "— if you just changed .env, restart the server (uvicorn does not reload .env automatically)",
            len(api_key), len(expected),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
    return api_key
