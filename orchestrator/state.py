from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from langgraph.graph import add_messages
from pydantic import BaseModel

from shared.models import GameProposal


class PipelinePhase(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    EVALUATING = "evaluating"
    DESIGNING = "designing"
    DEVELOPING = "developing"
    TESTING = "testing"
    BUILDING = "building"
    PUBLISHING = "publishing"
    OPERATING = "operating"


class CompanyState(BaseModel):
    phase: PipelinePhase = PipelinePhase.IDLE
    messages: Annotated[list, add_messages] = []
    current_proposal: GameProposal | None = None
    current_project_id: int | None = None
    market_insights: list[dict] = []
    gdd: dict | None = None
    art_assets_path: str | None = None
    game_code_path: str | None = None
    build_path: str | None = None
    itch_url: str | None = None
    qa_results: dict | None = None
    errors: list[str] = []
    retry_count: int = 0

    class Config:
        arbitrary_types_allowed = True
