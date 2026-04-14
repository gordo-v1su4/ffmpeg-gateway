import os
import secrets
from typing import Set
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader


def load_api_keys() -> Set[str]:
    keys_str = os.getenv("API_KEYS", "")
    if not keys_str:
        return set()
    keys = set(key.strip() for key in keys_str.split(",") if key.strip())
    return keys


VALID_API_KEYS: Set[str] = load_api_keys()

api_key_header = APIKeyHeader(
    name="X-API-Key",
    description="API Key for authentication.",
    auto_error=False,
)


async def verify_api_key(x_api_key: str = Security(api_key_header)) -> str:
    if not VALID_API_KEYS:
        return "no-keys-configured"
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    is_valid = any(
        secrets.compare_digest(x_api_key, valid_key) for valid_key in VALID_API_KEYS
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key
