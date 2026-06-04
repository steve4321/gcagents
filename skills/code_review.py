"""Code review skill — post-generation code quality analysis."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from skills.base import Skill, SkillContext, SkillRegistry, SkillResult


@SkillRegistry.register
class CodeReviewSkill(Skill):
    """Reviews generated code for quality, patterns, and potential issues."""

    skill_name = "code_review"
    skill_description = "Post-generation code quality review"
    skill_version = "1.0.0"
    skill_dependencies = ["read_file"]

    REVIEW_CRITERIA = (
        "1. TypeScript type safety (no 'any' types, proper interfaces)\n"
        "2. Error handling (no empty catch blocks)\n"
        "3. Game architecture (proper scene management, resource loading)\n"
        "4. Performance (no unnecessary re-renders, proper cleanup)"
    )

    def should_activate(self, context: SkillContext) -> bool:
        return (
            context.task_type in ("develop", "develop_simple")
            and context.artifact_path is not None
        )

    async def execute(self, context: SkillContext) -> SkillResult:
        from shared.llm_client import llm

        code_path = context.artifact_path
        if not code_path:
            return SkillResult(
                skill_name=self.skill_name,
                success=False,
                message="No artifact path provided",
            )

        try:
            code_dir = Path(code_path)
            if not code_dir.exists():
                return SkillResult(
                    skill_name=self.skill_name,
                    success=False,
                    message=f"Code directory not found: {code_path}",
                )

            files = (
                list(code_dir.rglob("*.ts")) + list(code_dir.rglob("*.js"))
            )
            file_list = "\n".join(
                f"  - {f.relative_to(code_dir)}" for f in files[:20]
            )

            review_prompt = (
                f"You are reviewing a game codebase at {code_path}.\n"
                f"Files:\n{file_list}\n\n"
                f"Analyze the code quality. Check for:\n"
                f"{self.REVIEW_CRITERIA}\n\n"
                'Respond in JSON:\n'
                '{"score": 0-10, "issues": ["..."], '
                '"suggestions": ["..."]}'
            )

            response, usage = await llm.chat_completion(
                model="glm-4-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior game developer "
                            "reviewing code quality."
                        ),
                    },
                    {"role": "user", "content": review_prompt},
                ],
                max_tokens=500,
                temperature=0.3,
                agent_name="skill_code_review",
                project_name=context.project_id or "",
            )

            try:
                review = json.loads(response)
            except json.JSONDecodeError:
                review = {
                    "score": 0,
                    "issues": [],
                    "suggestions": [
                        "Review response was not valid JSON"
                    ],
                }

            return SkillResult(
                skill_name=self.skill_name,
                success=True,
                output=review,
                message=f"Code review score: {review.get('score', '?')}/10",
                next_actions=(
                    ["fix_issues"]
                    if review.get("score", 10) < 5
                    else []
                ),
            )

        except Exception as e:
            logger.warning(f"Code review skill failed: {e}")
            return SkillResult(
                skill_name=self.skill_name,
                success=False,
                message=f"Review failed: {e}",
            )
