"""Base Pydantic schema and shared field validation helpers."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo

from app.core.constants import USER_PASSWORD_MAX_LENGTH
from app.core.messages import ERROR_FIELD_CANNOT_BE_NULL, ERROR_PASSWORD_TOO_LONG_BYTES


class BaseSchema(BaseModel):
    """Base schema that strips leading and trailing whitespace automatically."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


def validate_password_bytes(value: str) -> str:
    """Enforce bcrypt's 72-byte UTF-8 maximum length limit."""
    if len(value.encode("utf-8")) > USER_PASSWORD_MAX_LENGTH:
        raise ValueError(ERROR_PASSWORD_TOO_LONG_BYTES.format(max_bytes=USER_PASSWORD_MAX_LENGTH))
    return value


def validate_non_null(value: Any, info: ValidationInfo) -> Any:
    """Reject explicit null values for non-nullable partial update fields."""
    if value is None:
        field_name = info.field_name or "field"
        raise ValueError(ERROR_FIELD_CANNOT_BE_NULL.format(field=field_name))
    return value
