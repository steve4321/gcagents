"""Persistence layer for GCAgents — split into domain submodules.

All public functions are re-exported here so that
``from orchestrator.persistence import <name>`` continues to work exactly
as it did when this was a single ``persistence.py`` module.
"""

from __future__ import annotations

# Agent logs (agent_logs table)
from orchestrator.persistence.agents import (
    get_agent_logs,
    get_agent_stats,
    save_agent_log,
)

# Analytics (game_metrics table + aggregation)
from orchestrator.persistence.analytics import (
    get_analytics_summary,
    get_game_analytics_summary,
    get_game_metrics_detail,
    get_project_metrics,
    save_game_metric,
)

# Chat (chat_messages table)
from orchestrator.persistence.chat import (
    get_chat_history,
    get_pending_instructions,
    mark_instruction_processed,
    save_chat_message,
)

# Decisions (decisions table)
from orchestrator.persistence.decisions import (
    _row_to_decision,
    get_decision_by_id,
    get_decision_history,
    get_pending_decisions,
    get_project_decisions,
    resolve_decision,
    save_decision,
)

# Engine / shared infrastructure
from orchestrator.persistence.engine import (
    _engine_cache,
    _get_engine,
    _parse_datetime,
    ensure_tables,
    get_orchestrator_history,
    get_orchestrator_state,
    save_pipeline_state,
)

# Events (event_logs table)
from orchestrator.persistence.events import (
    get_recent_events,
    log_event,
)

# Feedback (game_feedback table)
from orchestrator.persistence.feedback import (
    get_all_feedback,
    get_pending_feedback,
    get_unprocessed_feedback,
    mark_feedback_processed,
    save_feedback,
)

# Finance (api_usage_logs + finance_budgets tables)
from orchestrator.persistence.finance import (
    check_budget_available,
    get_active_budgets,
    get_api_usage_summary,
    get_project_cost,
    get_usage_summary,
    log_api_usage,
    record_spend,
    set_budget,
)

# Game projects (game_projects + itch_stats tables)
from orchestrator.persistence.game_projects import (
    find_project_by_name,
    find_project_to_update,
    get_completed_genres,
    get_latest_itch_stats,
    get_latest_project,
    get_live_projects,
    get_project_gdd,
    save_itch_stat,
)

# Market reports & signals
from orchestrator.persistence.market import (
    get_last_scan_time,
    get_latest_market_report,
    get_latest_market_signals,
    get_market_report_detail,
    save_market_report,
    save_market_signals,
)

# Company memory (company_memory table)
from orchestrator.persistence.memory import (
    get_company_memory,
    save_user_genre_directive,
)

# Company policy (company_policy table)
from orchestrator.persistence.policy import (
    get_company_policy,
    set_company_policy,
)

# Projects (projects + game_versions tables)
from orchestrator.persistence.projects import (
    _mirror_to_game_projects,
    _row_to_project,
    get_all_projects,
    get_latest_version,
    get_project,
    get_projects_by_phase,
    save_game_version,
    save_project,
    set_project_live,
    update_project_art_assets_path,
    update_project_art_status,
    update_project_awaiting_decision,
    update_project_build_path,
    update_project_code_path,
    update_project_gdd,
    update_project_music_status,
    update_project_phase,
    update_project_platform_urls,
    update_project_proposal_and_phase,
    update_project_qa_result,
)

# Tasks (tasks table)
from orchestrator.persistence.tasks import (
    _row_to_task,
    claim_next_task,
    count_completed_tasks,
    count_completed_tasks_batch,
    count_completed_tasks_by_type,
    get_active_task_project_ids,
    get_pending_tasks,
    get_project_tasks,
    get_recent_completed_tasks,
    get_task,
    has_active_task,
    save_task,
    update_task_status,
)

__all__ = [
    # engine / shared
    "_engine_cache",
    "_get_engine",
    "_parse_datetime",
    "ensure_tables",
    "get_orchestrator_history",
    "get_orchestrator_state",
    "save_pipeline_state",
    # projects
    "_mirror_to_game_projects",
    "_row_to_project",
    "get_all_projects",
    "get_latest_version",
    "get_project",
    "get_projects_by_phase",
    "save_game_version",
    "save_project",
    "set_project_live",
    "update_project_art_assets_path",
    "update_project_art_status",
    "update_project_awaiting_decision",
    "update_project_build_path",
    "update_project_code_path",
    "update_project_gdd",
    "update_project_music_status",
    "update_project_phase",
    "update_project_platform_urls",
    "update_project_proposal_and_phase",
    "update_project_qa_result",
    # tasks
    "_row_to_task",
    "claim_next_task",
    "count_completed_tasks",
    "count_completed_tasks_batch",
    "count_completed_tasks_by_type",
    "get_active_task_project_ids",
    "get_pending_tasks",
    "get_project_tasks",
    "get_recent_completed_tasks",
    "get_task",
    "has_active_task",
    "save_task",
    "update_task_status",
    # decisions
    "_row_to_decision",
    "get_decision_by_id",
    "get_decision_history",
    "get_pending_decisions",
    "get_project_decisions",
    "resolve_decision",
    "save_decision",
    # market
    "get_last_scan_time",
    "get_latest_market_report",
    "get_latest_market_signals",
    "get_market_report_detail",
    "save_market_report",
    "save_market_signals",
    # feedback
    "get_all_feedback",
    "get_pending_feedback",
    "get_unprocessed_feedback",
    "mark_feedback_processed",
    "save_feedback",
    # analytics
    "get_analytics_summary",
    "get_game_analytics_summary",
    "get_game_metrics_detail",
    "get_project_metrics",
    "save_game_metric",
    # finance
    "check_budget_available",
    "get_active_budgets",
    "get_api_usage_summary",
    "get_project_cost",
    "get_usage_summary",
    "log_api_usage",
    "record_spend",
    "set_budget",
    # chat
    "get_chat_history",
    "get_pending_instructions",
    "mark_instruction_processed",
    "save_chat_message",
    # agents
    "get_agent_logs",
    "get_agent_stats",
    "save_agent_log",
    # game_projects
    "find_project_by_name",
    "find_project_to_update",
    "get_completed_genres",
    "get_latest_itch_stats",
    "get_latest_project",
    "get_live_projects",
    "get_project_gdd",
    "save_itch_stat",
    # events
    "get_recent_events",
    "log_event",
    # policy
    "get_company_policy",
    "set_company_policy",
    # memory
    "get_company_memory",
    "save_user_genre_directive",
]
