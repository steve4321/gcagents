from __future__ import annotations

import asyncio
from datetime import datetime

import feedparser
import httpx
from loguru import logger

from shared.config import SourceConfig
from shared.models import MarketSignal


async def fetch_itch_rss(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        for feed_url in config.feeds:
            try:
                resp = await client.get(feed_url, timeout=30)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                for entry in feed.entries[:20]:
                    tags = [tag.term for tag in getattr(entry, "tags", [])]
                    signals.append(MarketSignal(
                        source="itch_rss",
                        signal_type="new_game",
                        genre=tags[0] if tags else None,
                        title=entry.title,
                        data={
                            "url": entry.link,
                            "tags": tags,
                            "published": entry.get("published", ""),
                            "summary": entry.get("summary", ""),
                        },
                        score=_score_itch_entry(entry, tags),
                        captured_at=datetime.now(),
                    ))
            except Exception as e:
                logger.error(f"itch.io RSS fetch failed for {feed_url}: {e}")

    return signals


async def fetch_statkraken(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        for platform in config.platforms:
            try:
                url = f"{config.base_url}/platforms/{platform}/items?trending=true&limit=20"
                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                items = resp.json().get("data", resp.json().get("items", []))

                for item in items[:20]:
                    signals.append(MarketSignal(
                        source=f"statkraken_{platform}",
                        signal_type="trending",
                        genre=item.get("category", item.get("genre")),
                        title=item.get("title", item.get("name", "Unknown")),
                        data=item,
                        score=float(item.get("rating", item.get("score", 0))),
                        captured_at=datetime.now(),
                    ))
            except Exception as e:
                logger.error(f"StatKraken fetch failed for {platform}: {e}")

    return signals


async def fetch_google_play(config: SourceConfig) -> list[MarketSignal]:
    from google_play_scraper import scraper

    signals = []
    for category in config.categories:
        try:
            result = scraper.collection(
                collection=scraper.Collection.TOP_FREE,
                category=scraper.Category[category],
                num=20,
            )
            for app in result:
                signals.append(MarketSignal(
                    source="google_play",
                    signal_type="chart",
                    genre=category.replace("GAME_", "").lower(),
                    title=app["title"],
                    data={
                        "package": app["appId"],
                        "score": app.get("score"),
                        "installs": app.get("installs", ""),
                        "genre": app.get("genre", ""),
                    },
                    score=float(app.get("score", 0)) / 5.0,
                    captured_at=datetime.now(),
                ))
            await asyncio.sleep(1.0 / config.throttle_per_second)
        except Exception as e:
            logger.error(f"Google Play scrape failed for {category}: {e}")

    return signals


async def fetch_reddit(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    auth = httpx.BasicAuth(
        config.api_key_env,
        config.api_secret_env,
    ) if config.auth_type == "oauth2" else None

    async with httpx.AsyncClient() as client:
        for subreddit in config.subreddits:
            try:
                url = f"https://www.reddit.com/r/{subreddit}/top.json?limit=25&t=week"
                headers = {"User-Agent": "gcagents/0.1"}
                resp = await client.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                posts = resp.json().get("data", {}).get("children", [])

                for post in posts:
                    d = post["data"]
                    signals.append(MarketSignal(
                        source=f"reddit_{subreddit}",
                        signal_type="community_hot",
                        genre=subreddit,
                        title=d["title"],
                        data={
                            "url": f"https://reddit.com{d['permalink']}",
                            "score": d["score"],
                            "num_comments": d["num_comments"],
                            "selftext": d.get("selftext", "")[:500],
                        },
                        score=min(d["score"] / 1000.0, 1.0),
                        captured_at=datetime.now(),
                    ))
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Reddit fetch failed for r/{subreddit}: {e}")

    return signals


async def fetch_app_store(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        for endpoint_key, url_template in config.endpoints.items():
            try:
                if endpoint_key == "top_charts":
                    url = config.base_url + url_template
                else:
                    continue

                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                entries = data.get("feed", {}).get("entry", [])
                for entry in entries[:20]:
                    entry_data = entry.get("im:name", entry.get("title", {}))
                    title = entry_data.get("label", "") if isinstance(entry_data, dict) else str(entry_data)

                    signals.append(MarketSignal(
                        source="app_store",
                        signal_type="top_chart",
                        genre="casual",
                        title=title,
                        data={"raw": entry},
                        score=0.5,
                        captured_at=datetime.now(),
                    ))
                await asyncio.sleep(4)
            except Exception as e:
                logger.error(f"App Store fetch failed for {endpoint_key}: {e}")

    return signals


def _score_itch_entry(entry, tags: list[str]) -> float:
    hot_genres = {"puzzle", "idle", "clicker", "platformer", "tower-defense", "roguelike", "match-3"}
    tag_match = len(set(t.lower() for t in tags) & hot_genres) / max(len(hot_genres), 1)
    return min(tag_match + 0.2, 1.0)


SOURCE_FETCHERS = {
    "itch_rss": fetch_itch_rss,
    "statkraken": fetch_statkraken,
    "google_play": fetch_google_play,
    "reddit": fetch_reddit,
    "app_store": fetch_app_store,
}


async def scan_all_sources(sources_config: dict[str, SourceConfig]) -> list[MarketSignal]:
    all_signals: list[MarketSignal] = []
    tasks = []

    for name, config in sources_config.items():
        fetcher = SOURCE_FETCHERS.get(name)
        if fetcher:
            tasks.append(fetcher(config))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_signals.extend(result)
        elif isinstance(result, Exception):
            logger.error(f"Source scan error: {result}")

    logger.info(f"Market scan complete: {len(all_signals)} signals from {len(tasks)} sources")
    return all_signals
