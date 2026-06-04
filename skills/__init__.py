"""GCAgents skill system.

Import skill modules here to trigger registration.

To add a new skill:
    1. Create a new file in skills/
    2. Subclass Skill and set skill_name, skill_description
    3. Implement should_activate() and execute()
    4. Add @SkillRegistry.register decorator
    5. Import in this __init__.py
"""

from skills.base import Skill, SkillContext, SkillRegistry, SkillResult  # noqa: F401
from skills.code_review import CodeReviewSkill  # noqa: F401
