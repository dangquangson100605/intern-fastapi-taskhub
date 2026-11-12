"""Password hashing and JWT authentication utilities."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException
from app.core.messages import ERROR_INVALID_TOKEN, ERROR_INVALID_TOKEN_TYPE
from app.models.enums import TokenType, UserRole

settings = get_settings()

DUMMY_PASSWORD_HASH: str = "$2b$12$e2qGEOpnknvm0P3uCkZj5eHhtHm1uxyGTcCdAtBICY5NZT7K1FE7G"


@dataclass(frozen=True)
class TokenPayload:
    """Validated claims extracted from a decoded JWT token."""

    user_id: int
    token_type: TokenType
    jti: str
    exp: int
    iat: float


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def _create_token(
    user_id: int,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Build and sign a JWT token returning (encoded_token, jti, expires_at_utc)."""
    now = datetime.now(UTC)
    expire = now + expires_delta
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type.value,
        "jti": jti,
        "iat": now.timestamp(),
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)

    encoded = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded, jti, expire


def create_access_token(user_id: int, role: UserRole) -> str:
    """Create a short-lived signed JWT access token."""
    token, _, _ = _create_token(
        user_id=user_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role.value},
    )
    return token


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Create a long-lived signed JWT refresh token returning (token, jti, expires_at)."""
    return _create_token(
        user_id=user_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """Decode and validate a JWT token's signature, expiry, type, and subject."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise UnauthorizedException(ERROR_INVALID_TOKEN) from exc

    raw_type = payload.get("type")
    if raw_type != expected_type.value:
        raise UnauthorizedException(ERROR_INVALID_TOKEN_TYPE)

    try:
        raw_sub = payload["sub"]
        if isinstance(raw_sub, bool) or not isinstance(raw_sub, (str, int)):
            raise ValueError("Invalid subject type")
        user_id = int(raw_sub)
        if user_id <= 0:
            raise ValueError("Subject ID must be positive")
        raw_jti = payload["jti"]
        if not isinstance(raw_jti, str) or not raw_jti:
            raise ValueError("Invalid jti claim")
        exp = int(payload["exp"])
        iat = float(payload["iat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedException(ERROR_INVALID_TOKEN) from exc

    return TokenPayload(
        user_id=user_id,
        token_type=expected_type,
        jti=raw_jti,
        exp=exp,
        iat=iat,
    )
