"""Portable live-input validation without server or model dependencies."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["start"]
    sample_rate: Literal[16000] = 16000
    encoding: Literal["pcm_s16le"] = "pcm_s16le"
    language: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w-]+$")
    hotwords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=200)
