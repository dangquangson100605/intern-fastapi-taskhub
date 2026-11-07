"""Base Pydantic schema with standard configurations."""

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base schema that strips leading and trailing whitespace automatically."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

