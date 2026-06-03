from __future__ import annotations

import json
import urllib.error
import urllib.request

from loguru import logger

from shared.config import load_config


def _title_to_slug(title: str) -> str:
    import re
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def _find_local_project_id(itch_title: str) -> str | None:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).resolve().parents[3] / "data" / "gcagents.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        slug = _title_to_slug(itch_title)
        row = conn.execute(
            "SELECT id FROM projects WHERE LOWER(name) = LOWER(?) OR LOWER(REPLACE(name, ' ', '-')) = LOWER(?)",
            (itch_title, slug),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


async def fetch_itch_stats() -> list[dict]:
    config = load_config()
    if not config.butler_api_key or not config.butler_username:
        logger.warning("itch.io credentials not configured, skipping stats fetch")
        return []

    url = "https://api.itch.io/profile/games"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {config.butler_api_key}"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        logger.error(f"itch.io API error: {e}")
        return []
    except TimeoutError:
        logger.error("itch.io API timeout")
        return []

    games = payload.get("games", [])
    results = []
    for g in games:
        title = g.get("title", "")
        itch_game_id = g.get("id")
        downloads = int(g.get("downloads_count", 0) or 0)
        views = int(g.get("views_count", 0) or 0)
        purchases = int(g.get("purchases_count", 0) or 0)
        itch_url = g.get("url", "")
        project_id = _find_local_project_id(title) or f"itch-{itch_game_id}"

        try:
            from orchestrator.persistence import save_itch_stat
            await save_itch_stat(
                project_id=project_id,
                itch_game_id=itch_game_id,
                title=title,
                itch_url=itch_url,
                downloads_count=downloads,
                views_count=views,
                purchases_count=purchases,
            )
        except Exception as e:
            logger.warning(f"Failed to save itch stat for {title}: {e}")

        results.append({
            "project_id": project_id,
            "itch_game_id": itch_game_id,
            "title": title,
            "itch_url": itch_url,
            "downloads_count": downloads,
            "views_count": views,
            "purchases_count": purchases,
        })

    logger.info(f"Fetched itch.io stats for {len(results)} games")
    return results
