from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from orchestrator.persistence import (
    get_live_projects,
    save_feedback,
)
from shared.config import load_config
from shared.llm_client import llm


_FEEDBACK_CATEGORIES = ["bug", "feature", "praise", "question", "other"]

_CATEGORIZE_PROMPT = """You are categorizing game feedback from players. Given a comment,
classify it into exactly one of these categories:
- bug: The player reports something not working, a crash, glitch, or error
- feature: The player requests a new feature, enhancement, or improvement
- praise: The player expresses enjoyment, thanks, or positive sentiment
- question: The player asks a question about the game
- other: Anything else

Reply with a JSON object: {"category": "...", "reason": "...", "summary": "..."}
Do not include markdown formatting. Pure JSON only.

Comment: {text}"""


def _parse_itch_comments(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.select(".community_post")
    comments = []
    for post in posts:
        header = post.select_one(".post_header")
        content_div = post.select_one(".post_content")
        footer = post.select_one(".post_footer")

        author_el = header.select_one("strong a") if header else None
        author = author_el.get_text(strip=True) if author_el else ""

        date_el = header.select_one("time") if header else None
        posted_at = date_el.get("datetime", "") if date_el else ""

        text_el = content_div.select_one("p") if content_div else None
        text = text_el.get_text(strip=True) if text_el else ""

        votes_el = footer.select_one(".vote_count") if footer else None
        vote_count = int(votes_el.get_text(strip=True)) if votes_el else 0

        post_link = post.get("data-comment-id", "") or post.get("id", "")
        post_id = post_link.split("_")[-1] if "_" in post_link else post_link

        if not text or not post_id:
            continue

        comments.append({
            "post_id": str(post_id),
            "author": author,
            "text": text[:5000],
            "posted_at": posted_at,
            "vote_count": vote_count,
        })

    return comments


async def _categorize_feedback(text: str, config, project_name: str = "") -> tuple[str, str, str]:
    if not config.minimax_api_key:
        return "other", "no AI key", text[:200]

    try:
        raw, usage = await llm.chat_completion(
            model="MiniMax-M3",
            messages=[{"role": "user", "content": _CATEGORIZE_PROMPT.format(text=text[:1000])}],
            temperature=0.1,
            max_tokens=300,
            agent_name="feedback_collector",
            project_name=project_name,
        )
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        category = data.get("category", "other")
        if category not in _FEEDBACK_CATEGORIES:
            category = "other"
        return category, data.get("reason", ""), data.get("summary", text[:200])
    except Exception as e:
        logger.warning(f"Feedback categorization failed: {e}")
        return "other", str(e), text[:200]


async def collect_feedback() -> dict:
    config = load_config()
    projects = await get_live_projects()
    if not projects:
        logger.info("No live projects with itch.io URLs to collect feedback from")
        return {"feedback_collected": 0}

    total_saved = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for project in projects:
            project_id = project["id"]
            itch_url = project.get("itch_url", "")
            if not itch_url:
                continue

            logger.info(f"Collecting feedback for {project['name']} ({itch_url})")
            try:
                resp = await client.get(itch_url)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"Failed to fetch {itch_url}: {e}")
                continue

            comments = _parse_itch_comments(resp.text, itch_url)
            logger.info(f"Found {len(comments)} comments on {project['name']}")

            for comment in comments:
                category, reason, summary = await _categorize_feedback(comment["text"], config, project_name=project['name'])
                saved = await save_feedback(
                    project_id=project_id,
                    post_id=comment["post_id"],
                    body=comment["text"],
                    author=comment["author"],
                    posted_at=comment["posted_at"],
                    vote_count=comment["vote_count"],
                    category=category,
                    ai_analysis=json.dumps({"reason": reason, "summary": summary}, ensure_ascii=False),
                )
                if saved:
                    total_saved += 1
                    logger.info(
                        f"Saved feedback #{comment['post_id']}: [{category}] {summary[:60]}"
                    )

    logger.info(f"Feedback collection complete: {total_saved} new comments saved")
    return {"feedback_collected": total_saved}
