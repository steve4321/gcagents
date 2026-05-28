from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ProjectStatus(str, Enum):
    PROPOSED = "proposed"
    DESIGNING = "designing"
    DEVELOPING = "developing"
    TESTING = "testing"
    BUILDING = "building"
    PUBLISHING = "publishing"
    LIVE = "live"
    RETIRED = "retired"


class MarketSignal(BaseModel):
    source: str
    signal_type: str
    genre: str | None = None
    title: str
    data: dict
    score: float = 0.0
    captured_at: datetime = datetime.now()


class GameProposal(BaseModel):
    name: str
    genre: str
    description: str
    target_platforms: list[str]
    estimated_dev_hours: float
    market_opportunity_score: float
    differentiation: str
    reference_games: list[str]
    created_at: datetime = datetime.now()


class GameProject(BaseModel):
    id: int | None = None
    name: str
    genre: str
    status: ProjectStatus = ProjectStatus.PROPOSED
    gdd: dict | None = None
    proposal: GameProposal
    itch_url: str | None = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: datetime | None = None


class GameMetric(BaseModel):
    project_id: int
    metric_type: str
    value: float
    captured_at: datetime = datetime.now()


class CompanyMemory(BaseModel):
    category: str
    title: str
    content: dict
    importance: float = 0.5
    created_at: datetime = datetime.now()
