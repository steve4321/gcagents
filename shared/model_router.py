"""Multi-tier model router — selects optimal AI model based on task complexity.

Routes tasks to appropriate model tiers:
  - strong: Complex reasoning, architecture, code generation
  - fast: Quick responses, classification, formatting
  - cheap: Batch processing, simple validation, summaries
  - specialized: Domain-specific models (code, art, etc.)

Inspired by Aider's 3-tier model system (main/weak/editor).
Target: 30-50% cost reduction while maintaining output quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from loguru import logger


class ModelTier(str, Enum):
    """Model quality tiers."""

    STRONG = "strong"  # Best reasoning quality
    FAST = "fast"  # Good quality, fast response
    CHEAP = "cheap"  # Acceptable quality, minimal cost
    SPECIALIZED_CODE = "code"  # Code-optimized model
    SPECIALIZED_ART = "art"  # Art generation (ComfyUI)
    SPECIALIZED_AUDIO = "audio"  # Audio generation (Suno)


class TaskCategory(str, Enum):
    """Categories of tasks the system performs."""

    # High complexity — needs strong model
    ARCHITECTURE = "architecture"
    CODE_GENERATION = "code_generation"
    GAME_DESIGN = "game_design"
    MARKET_ANALYSIS = "market_analysis"

    # Medium complexity — fast model is fine
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    PLANNING = "planning"
    EVALUATION = "evaluation"

    # Low complexity — cheap model sufficient
    FORMATTING = "formatting"
    COMMIT_MESSAGE = "commit_message"
    LOG_ANALYSIS = "log_analysis"
    SIMPLE_VALIDATION = "simple_validation"
    INTENT_CLASSIFICATION = "intent_classification"

    # Specialized
    CODE_EDIT = "code_edit"
    CODE_REVIEW = "code_review"
    ART_GENERATION = "art_generation"
    MUSIC_GENERATION = "music_generation"


# Mapping: task category → default model tier
CATEGORY_TIER_MAP: dict[TaskCategory, ModelTier] = {
    TaskCategory.ARCHITECTURE: ModelTier.STRONG,
    TaskCategory.CODE_GENERATION: ModelTier.SPECIALIZED_CODE,
    TaskCategory.GAME_DESIGN: ModelTier.STRONG,
    TaskCategory.MARKET_ANALYSIS: ModelTier.FAST,
    TaskCategory.CLASSIFICATION: ModelTier.FAST,
    TaskCategory.SUMMARIZATION: ModelTier.FAST,
    TaskCategory.TRANSLATION: ModelTier.CHEAP,
    TaskCategory.PLANNING: ModelTier.STRONG,
    TaskCategory.EVALUATION: ModelTier.FAST,
    TaskCategory.FORMATTING: ModelTier.CHEAP,
    TaskCategory.COMMIT_MESSAGE: ModelTier.CHEAP,
    TaskCategory.LOG_ANALYSIS: ModelTier.CHEAP,
    TaskCategory.SIMPLE_VALIDATION: ModelTier.CHEAP,
    TaskCategory.INTENT_CLASSIFICATION: ModelTier.CHEAP,
    TaskCategory.CODE_EDIT: ModelTier.SPECIALIZED_CODE,
    TaskCategory.CODE_REVIEW: ModelTier.SPECIALIZED_CODE,
    TaskCategory.ART_GENERATION: ModelTier.SPECIALIZED_ART,
    TaskCategory.MUSIC_GENERATION: ModelTier.SPECIALIZED_AUDIO,
}


@dataclass
class ModelConfig:
    """Configuration for a single model."""

    tier: ModelTier
    model_name: str
    provider: str  # "openai_compatible" | "zhipuai" | "comfyui" | "suno"
    base_url: str | None = None
    api_key_env: str | None = None
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    max_tokens: int = 4096
    supports_tools: bool = False
    roles: list[str] = field(default_factory=list)


@dataclass
class ModelTierConfig:
    """Configuration for a model tier with fallback chain."""

    tier: ModelTier
    primary: str  # Model name
    fallback: str | None = None  # Fallback model name
    roles: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    model: str
    tier: ModelTier
    category: TaskCategory
    reason: str
    estimated_cost: str  # "low" | "medium" | "high"
    fallback: str | None = None


class ModelRouter:
    """Routes tasks to the optimal model based on complexity and cost.

    Usage:
        router = ModelRouter(config)
        decision = router.route(TaskCategory.CODE_GENERATION, complexity=0.8)
        model = decision.model  # e.g., "MiniMax-M2.1"
    """

    def __init__(self, tier_configs: list[ModelTierConfig] | None = None) -> None:
        self._tiers: dict[ModelTier, ModelTierConfig] = {}

        # Default tier configuration (matches current agents.yaml models)
        defaults = tier_configs or [
            ModelTierConfig(
                tier=ModelTier.STRONG,
                primary="MiniMax-M3",
                fallback="deepseek-v4-flash",
                roles=["planning", "ceo", "architecture"],
            ),
            ModelTierConfig(
                tier=ModelTier.FAST,
                primary="MiniMax-M3",
                fallback="glm-4-flash",
                roles=["analysis", "classification", "summarization"],
            ),
            ModelTierConfig(
                tier=ModelTier.CHEAP,
                primary="glm-4-flash",
                fallback=None,
                roles=["translation", "formatting", "commit_message"],
            ),
            ModelTierConfig(
                tier=ModelTier.SPECIALIZED_CODE,
                primary="MiniMax-M2.1",
                fallback="deepseek-v4-flash",
                roles=["code_gen", "code_edit", "code_review"],
            ),
            ModelTierConfig(
                tier=ModelTier.SPECIALIZED_ART,
                primary="stable-diffusion-xl",
                fallback=None,
                roles=["art"],
            ),
            ModelTierConfig(
                tier=ModelTier.SPECIALIZED_AUDIO, primary="suno", fallback=None, roles=["music"]
            ),
        ]

        for cfg in defaults:
            self._tiers[cfg.tier] = cfg

    def route(
        self,
        category: TaskCategory,
        complexity: float | None = None,
        agent_role: str | None = None,
        prefer_cheaper: bool = False,
    ) -> RoutingDecision:
        """Select the optimal model for a task.

        Args:
            category: What type of task this is
            complexity: 0.0-1.0 score. Higher = more capable model needed.
            agent_role: Override based on agent role (e.g., "lead_programmer")
            prefer_cheaper: If True, bias toward cheaper models

        Returns:
            RoutingDecision with selected model, tier, and reasoning
        """
        # Determine tier
        base_tier = CATEGORY_TIER_MAP.get(category, ModelTier.FAST)

        # Complexity-based adjustment
        if complexity is not None:
            if complexity >= 0.7 and base_tier in (ModelTier.FAST, ModelTier.CHEAP):
                base_tier = ModelTier.STRONG
                logger.debug(f"ModelRouter: complexity={complexity:.2f} upgraded to STRONG tier")
            elif complexity < 0.3 and base_tier == ModelTier.STRONG and prefer_cheaper:
                base_tier = ModelTier.FAST
                logger.debug(
                    f"ModelRouter: complexity={complexity:.2f} downgraded to FAST tier (prefer_cheaper)"
                )

        # Role-based override
        if agent_role:
            for tier_cfg in self._tiers.values():
                if agent_role in tier_cfg.roles:
                    base_tier = tier_cfg.tier
                    break

        # Get model config
        tier_cfg = self._tiers.get(base_tier)
        if not tier_cfg:
            tier_cfg = self._tiers[ModelTier.FAST]
            base_tier = ModelTier.FAST

        # Cost estimate
        cost_map = {
            ModelTier.STRONG: "high",
            ModelTier.FAST: "medium",
            ModelTier.CHEAP: "low",
            ModelTier.SPECIALIZED_CODE: "medium",
            ModelTier.SPECIALIZED_ART: "high",
            ModelTier.SPECIALIZED_AUDIO: "high",
        }

        return RoutingDecision(
            model=tier_cfg.primary,
            tier=base_tier,
            category=category,
            reason=f"{category.value} → {base_tier.value} → {tier_cfg.primary}",
            estimated_cost=cost_map.get(base_tier, "medium"),
            fallback=tier_cfg.fallback,
        )

    def route_task_type(self, task_type: str, complexity: float | None = None) -> RoutingDecision:
        """Convenience: route based on scheduler task type string.

        Maps scheduler task types to TaskCategories automatically.
        """
        type_to_category: dict[str, TaskCategory] = {
            "market_scan": TaskCategory.MARKET_ANALYSIS,
            "design_game": TaskCategory.GAME_DESIGN,
            "art_gen": TaskCategory.ART_GENERATION,
            "generate_music": TaskCategory.MUSIC_GENERATION,
            "develop": TaskCategory.CODE_GENERATION,
            "develop_simple": TaskCategory.CODE_GENERATION,
            "qa": TaskCategory.CODE_REVIEW,
            "build": TaskCategory.SIMPLE_VALIDATION,
            "localize": TaskCategory.TRANSLATION,
            "deploy": TaskCategory.SIMPLE_VALIDATION,
        }

        category = type_to_category.get(task_type, TaskCategory.CLASSIFICATION)
        return self.route(category, complexity=complexity)

    def get_model_for_agent(self, agent_role: str) -> str:
        """Get the primary model for an agent role.

        Used when the scheduler needs to know which model an agent should use.
        """
        for tier_cfg in self._tiers.values():
            if agent_role in tier_cfg.roles:
                return tier_cfg.primary

        # Default: fast tier
        return self._tiers.get(
            ModelTier.FAST, ModelTierConfig(tier=ModelTier.FAST, primary="MiniMax-M3")
        ).primary

    def get_all_tiers(self) -> dict[str, dict]:
        """Get summary of all configured tiers."""
        return {
            tier.value: {
                "primary": cfg.primary,
                "fallback": cfg.fallback,
                "roles": cfg.roles,
            }
            for tier, cfg in self._tiers.items()
        }


# Singleton
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
