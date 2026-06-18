from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()


@router.get("/metrics")
async def metrics():
    """Prometheus-format metrics endpoint (text/plain; version=0.0.4)."""
    from shared.persistence_metrics import collect_metrics_text

    text = await collect_metrics_text()
    return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")
