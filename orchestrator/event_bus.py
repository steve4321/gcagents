from __future__ import annotations

from loguru import logger


async def emit(
    event_type: str,
    title: str,
    detail: str = "",
    severity: str = "info",
    source_agent: str = "",
    project_name: str = "",
    metadata: dict | None = None,
) -> int:
    from orchestrator.persistence import log_event

    event_id = await log_event(
        event_type=event_type,
        severity=severity,
        title=title,
        detail=detail,
        source_agent=source_agent,
        project_name=project_name,
        metadata=metadata,
    )

    logger.info(f"[EVENT] [{event_type}] [{severity}] {title}")

    try:
        from dashboard.web.api_server import broadcast_event
        import asyncio

        asyncio.create_task(broadcast_event({
            "id": event_id,
            "event_type": event_type,
            "severity": severity,
            "title": title,
            "detail": detail,
            "source_agent": source_agent,
            "project_name": project_name,
            "created_at": "",
        }))
    except Exception:
        pass

    return event_id
