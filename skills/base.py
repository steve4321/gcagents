"""Skill system base — pluggable, conditionally-activated agent capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class SkillContext:
    """Context provided to a skill for activation check and execution."""

    task_type: str
    project_id: str | None = None
    agent_role: str = ""
    artifact_path: str | None = None
    params: dict = field(default_factory=dict)
    project_state: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class SkillResult:
    """Result of a skill execution."""

    skill_name: str
    success: bool
    output: dict = field(default_factory=dict)
    message: str = ""
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


class Skill(ABC):
    """Base class for all skills — pluggable agent capabilities."""

    # Subclasses MUST set these as class attributes
    skill_name: str = ""
    skill_description: str = ""
    skill_version: str = "1.0.0"
    skill_dependencies: list[str] = []
    skill_conflicts: list[str] = []

    @abstractmethod
    def should_activate(self, context: SkillContext) -> bool:
        """Return True if this skill should run for the given context."""
        ...

    @abstractmethod
    async def execute(self, context: SkillContext) -> SkillResult:
        """Execute the skill and return results."""
        ...

    def __repr__(self) -> str:
        return f"Skill({self.skill_name} v{self.skill_version})"


class SkillRegistry:
    """Global registry for skills — self-registration on import."""

    _skills: dict[str, type[Skill]] = {}

    @classmethod
    def register(cls, skill_cls: type[Skill]) -> type[Skill]:
        """Register a skill class. Use as class decorator.

        Usage::

            @SkillRegistry.register
            class CodeReviewSkill(Skill):
                skill_name = "code_review"
                ...
        """
        name = skill_cls.skill_name
        if not name:
            raise ValueError(
                f"Skill class {skill_cls.__name__} must set skill_name"
            )
        cls._skills[name] = skill_cls
        logger.debug(f"Skill registered: {name}")
        return skill_cls

    @classmethod
    def get_skill(cls, name: str) -> type[Skill] | None:
        """Get a skill class by name."""
        return cls._skills.get(name)

    @classmethod
    def get_applicable_skills(cls, context: SkillContext) -> list[Skill]:
        """Get all skills that should activate for the given context."""
        applicable = []
        for skill_cls in cls._skills.values():
            skill = skill_cls()
            try:
                if skill.should_activate(context):
                    applicable.append(skill)
            except Exception as e:
                logger.warning(
                    f"Skill activation check failed for "
                    f"{skill.skill_name}: {e}"
                )
        return applicable

    @classmethod
    def get_all_skills(cls) -> dict[str, str]:
        """Get name → description mapping of all registered skills."""
        return {
            name: cls.skill_description
            for name, cls in cls._skills.items()
        }

    @classmethod
    def count(cls) -> int:
        return len(cls._skills)

    @classmethod
    def list_skill_names(cls) -> list[str]:
        return sorted(cls._skills.keys())
