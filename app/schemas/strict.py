"""Shared finite, whitespace-normalized, closed contracts."""
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False, protected_namespaces=('model_validate', 'model_dump'))
