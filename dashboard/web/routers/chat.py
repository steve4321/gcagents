from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from dashboard.web import api_server
from shared.config import ROOT_DIR

router = APIRouter()


# ── Chat API ───────────────────────────────────────────────────────────────────


@router.post("/api/chat/send", dependencies=[Depends(api_server.get_api_key)])
async def send_chat_message(message: dict):
    content = message.get("content", "").strip()
    target_agent = message.get("target_agent", "ceo").strip().lower()

    if not content:
        raise HTTPException(400, "Message content is required")

    if target_agent != "ceo":
        raise HTTPException(400, "Only CEO is available")

    from orchestrator.persistence import log_event, save_chat_message

    await save_chat_message(
        role="user",
        content=content,
        agent_name=target_agent,
        metadata={"target_agent": target_agent, "processed": True},
    )

    await log_event(
        event_type="system",
        severity="info",
        title=f"User message to {target_agent.upper()}",
        detail=content[:200],
        source_agent="dashboard",
    )

    reply = await _generate_ceo_reply(content)

    await save_chat_message(
        role="assistant",
        content=reply,
        agent_name="ceo",
    )

    return {"status": "sent", "target": target_agent}


async def _build_ceo_context() -> tuple[str, list[dict]]:
    """Gather comprehensive company data for the CEO system prompt."""

    from orchestrator.persistence import (
        get_all_projects,
        get_api_usage_summary,
        get_chat_history,
        get_company_memory,
        get_company_policy,
        get_latest_market_report,
        get_pending_decisions,
        get_recent_events,
    )

    # Projects
    projects = await get_all_projects()
    if projects:
        proj_lines = []
        for p in projects:
            proj_lines.append(
                f"  - {p.name} | 类型: {p.genre or '未定'} "
                f"| 阶段: {p.phase.value} | 进度: {p.progress:.0%}"
            )
        project_summary = "\n".join(proj_lines)
    else:
        project_summary = "  （暂无项目）"

    # Market report
    market = await get_latest_market_report()
    market_summary = "  （暂无市场报告）"
    if market and market.get("opportunities_json"):
        try:
            opps = (
                json.loads(market["opportunities_json"])
                if isinstance(market["opportunities_json"], str)
                else market["opportunities_json"]
            )
            if isinstance(opps, list):
                top = opps[:3]
                opp_lines = []
                for o in top:
                    if isinstance(o, dict):
                        opp_lines.append(
                            f"  - {o.get('genre', '?')}: "
                            f"{o.get('reason', o.get('description', '无详情'))}"
                        )
                    else:
                        opp_lines.append(f"  - {o}")
                if opp_lines:
                    market_summary = "\n".join(opp_lines)
        except (json.JSONDecodeError, TypeError):
            pass

    # Financials
    usage = await get_api_usage_summary()
    total_cost = usage.get("total_cost", 0.0)
    calls = usage.get("calls", 0)

    # Pending decisions
    decisions = await get_pending_decisions()

    # Recent events
    events = await get_recent_events(limit=8)
    event_lines = []
    for ev in events[:8]:
        title = ev.get("title", "")
        if title:
            event_lines.append(f"  - {title}")
    events_summary = "\n".join(event_lines) if event_lines else "  （无近期事件）"

    # Company memory / lessons
    memories = await get_company_memory(limit=5)
    mem_lines = []
    for m in memories[:5]:
        mem_lines.append(f"  - {m.get('title', m.get('content', ''))}")
    mem_summary = "\n".join(mem_lines) if mem_lines else "  （暂无）"

    # Policy
    policy = await get_company_policy()

    # Chat history (last 6 messages)
    chat_history = await get_chat_history(limit=6)

    context = (
        f"### 项目列表\n{project_summary}\n\n"
        f"### 市场机会（最新报告前3）\n{market_summary}\n\n"
        f"### 财务状况\n"
        f"  - 总API花费: ${total_cost:.2f}\n"
        f"  - API调用次数: {calls}\n"
        f"  - 预算上限: ${policy.get('budget_limit_usd', '?')}/月\n\n"
        f"### 待处理决策: {len(decisions)} 个\n\n"
        f"### 近期事件\n{events_summary}\n\n"
        f"### 公司记忆/经验教训\n{mem_summary}\n\n"
        f"### 公司策略\n"
        f"  - 最大活跃项目数: {policy.get('max_active_projects', '?')}\n"
        f"  - 自动发布: {'是' if policy.get('auto_publish') else '否'}\n"
        f"  - 偏好类型: {', '.join(policy.get('preferred_genres', [])) or '不限'}"
    )
    return context, chat_history


_CEO_PROMPT_CACHE: str | None = None


def _load_ceo_prompt() -> str:
    """Load CEO chat system prompt from config/prompts/ceo_chat.yaml.

    Cached at module level; reload by clearing ``_CEO_PROMPT_CACHE``.
    """
    global _CEO_PROMPT_CACHE
    if _CEO_PROMPT_CACHE is not None:
        return _CEO_PROMPT_CACHE
    import yaml

    path = ROOT_DIR / "config" / "prompts" / "ceo_chat.yaml"
    with open(path) as _f:
        data = yaml.safe_load(_f)
    _CEO_PROMPT_CACHE = data["system"]
    return _CEO_PROMPT_CACHE


async def _generate_ceo_reply(content: str) -> str:
    from shared.llm_client import llm

    context, chat_history = await _build_ceo_context()

    system_prompt = _load_ceo_prompt().replace("{context}", context)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-6:]:
        role = msg.get("role", "user")
        msg_content = msg.get("content", "")
        if msg_content and role in ("user", "assistant"):
            clean = re.sub(r"\[ACTION\].*?\[/ACTION\]", "", msg_content).strip()
            if clean:
                messages.append({"role": role, "content": clean})
    messages.append({"role": "user", "content": content})

    try:
        reply, _ = await llm.chat_completion(
            model="MiniMax-M3",
            messages=messages,
            max_tokens=800,
            temperature=0.7,
            agent_name="ceo-chat",
        )
        cleaned_reply = await _execute_ceo_actions(reply.strip())
        return cleaned_reply
    except Exception as e:
        logger.error(f"CEO chat error: {e}")
        return "抱歉，我暂时无法回复。请稍后再试。"


async def _execute_ceo_actions(reply: str) -> str:
    """Parse and execute hidden [ACTION] blocks from the CEO reply."""
    import re

    actions = re.findall(r"\[ACTION\](.*?)\[/ACTION\]", reply)
    cleaned = re.sub(r"\[ACTION\].*?\[/ACTION\]", "", reply).strip()

    for action_str in actions:
        try:
            action = json.loads(action_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse CEO action: {action_str[:100]}")
            continue

        action_type = action.get("action")
        data = action.get("data", {})

        ALLOWED_ACTIONS = {
            "create_project",
            "cancel_project",
            "publish_project",
            "update_project",
            "pause_project",
        }
        if action_type not in ALLOWED_ACTIONS:
            logger.warning(f"Unknown CEO action type: {action_type}")
            continue

        if action_type == "create_project":
            await _action_create_project(data)
        elif action_type == "cancel_project":
            await _action_cancel_project(data)
        elif action_type == "publish_project":
            await _action_publish_project(data)
        else:
            logger.warning(f"Unknown CEO action: {action_type}")

    return cleaned


async def _action_create_project(data: dict) -> None:
    """Create a new project from CEO action data."""
    import uuid

    from orchestrator.persistence import save_project
    from shared.models import ProjectPhase, ProjectState

    name = data.get("name", "").strip()
    genre = data.get("genre", "").strip()
    description = data.get("description", "").strip()

    if not name:
        logger.warning("create_project action missing name")
        return

    project = ProjectState(
        id=uuid.uuid4().hex[:12],
        name=name,
        genre=genre,
        phase=ProjectPhase.BACKLOG,
        proposal={"description": description} if description else None,
    )
    await save_project(project)
    logger.info(f"CEO created project: {name} (genre={genre})")


async def _action_cancel_project(data: dict) -> None:
    """Cancel a project by name or id."""
    from orchestrator.persistence import get_all_projects, update_project_phase

    project_id = data.get("project_id", "").strip()
    project_name = data.get("project_name", "").strip()

    if project_id:
        await update_project_phase(project_id, "cancelled")
        logger.info(f"CEO cancelled project: {project_id}")
        return

    if project_name:
        projects = await get_all_projects()
        for p in projects:
            if p.name.lower() == project_name.lower():
                await update_project_phase(p.id, "cancelled")
                logger.info(f"CEO cancelled project: {p.name} ({p.id})")
                return
        logger.warning(f"cancel_project: project not found: {project_name}")


async def _action_publish_project(data: dict) -> None:
    """Publish a project by name or id."""
    from orchestrator.persistence import get_all_projects, update_project_phase

    project_id = data.get("project_id", "").strip()
    project_name = data.get("project_name", "").strip()

    if project_id:
        await update_project_phase(project_id, "publishing")
        logger.info(f"CEO publishing project: {project_id}")
        return

    if project_name:
        projects = await get_all_projects()
        for p in projects:
            if p.name.lower() == project_name.lower():
                await update_project_phase(p.id, "publishing")
                logger.info(f"CEO publishing project: {p.name} ({p.id})")
                return
        logger.warning(f"publish_project: project not found: {project_name}")


@router.get("/api/chat/history")
async def get_chat_history_api(limit: int = 100):
    from orchestrator.persistence import get_chat_history

    return await get_chat_history(limit)
