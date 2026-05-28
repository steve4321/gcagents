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
    UPDATING = "updating"
    RETIRED = "retired"


class FeedbackCategory(str, Enum):
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    PRAISE = "praise"
    QUESTION = "question"
    OTHER = "other"


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
    current_version: str = "0.0.0"
    feedback_count: int = 0
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: datetime | None = None


class GameMetric(BaseModel):
    id: int | None = None
    project_id: int
    metric_name: str  # play_count | avg_session_s | completion_rate | crash_count | retention_1d
    metric_value: float
    recorded_at: datetime = datetime.now()


class GameFeedback(BaseModel):
    id: int | None = None
    project_id: int
    post_id: str  # itch.io post id for dedup
    author: str = ""
    text: str
    posted_at: datetime | None = None
    vote_count: int = 0
    category: FeedbackCategory = FeedbackCategory.OTHER
    ai_analysis: str = ""
    processed: bool = False
    created_at: datetime = datetime.now()


class GameVersion(BaseModel):
    id: int | None = None
    project_id: int
    version: str  # "1.0.0"
    gdd_snapshot: dict | None = None
    changelog: str = ""
    feedback_ids: list[int] = []
    build_size: int = 0
    created_at: datetime = datetime.now()


class CompanyMemory(BaseModel):
    category: str
    title: str
    content: dict
    importance: float = 0.5
    created_at: datetime = datetime.now()


class FinanceBudget(BaseModel):
    id: int | None = None
    category: str
    budget_type: str = "monthly"
    budget_limit_usd: float
    spent_usd: float = 0.0
    period_start: str | None = None
    period_end: str | None = None
    is_active: bool = True
    created_at: datetime = datetime.now()


class ChatMessage(BaseModel):
    id: int | None = None
    role: str
    content: str
    agent_name: str = ""
    metadata: dict = {}
    created_at: datetime = datetime.now()


class EventLog(BaseModel):
    id: int | None = None
    event_type: str
    severity: str = "info"
    title: str
    detail: str = ""
    source_agent: str = ""
    project_name: str = ""
    metadata: dict = {}
    created_at: datetime = datetime.now()


class ProjectPhase(str, Enum):
    BACKLOG = "backlog"
    SCANNING = "scanning"
    DESIGNING = "designing"
    DEVELOPING = "developing"
    TESTING = "testing"
    BUILDING = "building"
    PUBLISHING = "publishing"
    LIVE = "live"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ProjectState(BaseModel):
    id: str
    name: str
    genre: str = ""
    phase: ProjectPhase = ProjectPhase.BACKLOG
    progress: float = 0.0
    proposal: dict | None = None
    gdd: dict | None = None
    code_path: str | None = None
    art_status: str = "pending"
    qa_result: dict | None = None
    itch_url: str | None = None
    version: str = "0.0.0"
    awaiting_decision: str | None = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class DecisionType(str, Enum):
    NEW_PROJECT = "new_project"
    PUBLISH = "publish"
    CANCEL = "cancel"
    BUDGET_OVERRUN = "budget_overrun"
    DIRECTION_CHANGE = "direction_change"


class DecisionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DecisionPoint(BaseModel):
    id: str
    project_id: str | None = None
    decision_type: DecisionType
    question: str
    options: list[dict] = []
    context: dict = {}
    status: DecisionStatus = DecisionStatus.PENDING
    human_response: str | None = None
    created_at: datetime = datetime.now()
    resolved_at: datetime | None = None


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRecord(BaseModel):
    id: str
    project_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    params: dict = {}
    result: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = datetime.now()
