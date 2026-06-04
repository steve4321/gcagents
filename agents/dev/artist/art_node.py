from __future__ import annotations

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase


async def generate_art(state: CompanyState) -> dict:
    """Generate game art assets via ComfyUI. Falls back to Phaser shapes if ComfyUI unavailable."""
    gdd = state.gdd
    if not gdd:
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing GDD for art generation"]}

    logger.info(f"Art generation for: {gdd.get('title', 'unknown')}")

    try:
        from agents.dev.artist.art_agent import generate_art as _generate_art_impl

        result = await _generate_art_impl(state)

        updated_gdd = state.gdd
        if updated_gdd and "art_style" in updated_gdd:
            result["gdd"] = updated_gdd

        return result
    except ImportError:
        logger.warning("ComfyUI art agent not available, using Phaser shape fallback")
        return {"phase": PipelinePhase.DEVELOPING}
    except Exception as e:
        logger.warning(f"Art generation failed ({e}), falling back to Phaser shapes")
        return {"phase": PipelinePhase.DEVELOPING}
