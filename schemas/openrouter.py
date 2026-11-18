"""Pydantic request and response models for OpenRouter chat."""

from pydantic import BaseModel, Field


class OpenRouterChatRequest(BaseModel):
    """One user prompt submitted to the OpenRouter playground."""

    prompt: str = Field(min_length=1, max_length=4_000)


class OpenRouterChatResponse(BaseModel):
    """Text response and model ID returned by OpenRouter."""

    model: str
    answer: str


class OpenRouterLmiSummaryRequest(BaseModel):
    """Selected LMI report to summarize."""

    filename: str = Field(min_length=1, max_length=255)


class OpenRouterLmiSummaryResponse(BaseModel):
    """Summary result and selected source file."""

    models: list[str]
    document: str
    answer: str
    summary_id: str | None = None
    cached: bool = False
    cache_warning: str | None = None
