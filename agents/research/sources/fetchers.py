"""Market data source adapters — 12 sources with HTTP/RSS scraping.

Each fetcher takes a SourceConfig and returns a list of MarketSignal objects.
Sources are scanned in parallel via asyncio.gather().
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime

import feedparser
import httpx
from loguru import logger

from shared.config import SourceConfig
from shared.constants import APPSTORE_REQUEST_INTERVAL, DEFAULT_SOURCE_SCORE, REDDIT_REQUEST_INTERVAL
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
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
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
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
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
        except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
            logger.error(f"Google Play scrape failed for {category}: {e}")

    return signals


async def fetch_reddit(config: SourceConfig) -> list[MarketSignal]:
    signals = []

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
                await asyncio.sleep(REDDIT_REQUEST_INTERVAL)
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
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
                        score=DEFAULT_SOURCE_SCORE,
                        captured_at=datetime.now(),
                    ))
                await asyncio.sleep(APPSTORE_REQUEST_INTERVAL)
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"App Store fetch failed for {endpoint_key}: {e}")

    return signals


async def fetch_itch_api(config: SourceConfig) -> list[MarketSignal]:
    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        logger.debug("ITCH_API_KEY not set, skipping itch API fetch")
        return []

    signals = []
    tags_to_search = config.tags or ["puzzle", "idle", "platformer", "roguelike"]
    async with httpx.AsyncClient() as client:
        for tag in tags_to_search:
            try:
                url = f"{config.base_url}/games/search"
                headers = {"Authorization": f"Bearer {api_key}"}
                params = {"tags": tag, "limit": 20}
                resp = await client.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                games = resp.json().get("games", resp.json().get("data", []))

                for game in games[:15]:
                    views = game.get("views", 0) or 0
                    score = min(views / 10000.0, 1.0) if views > 0 else 0.1
                    signals.append(MarketSignal(
                        source="itch_api",
                        signal_type="popular_tag",
                        genre=tag,
                        title=game.get("title", game.get("name", "Unknown")),
                        data={
                            "url": game.get("url", ""),
                            "tags": [tag],
                            "views": views,
                            "price": game.get("price", 0),
                        },
                        score=score,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"itch.io API fetch failed for tag '{tag}': {e}")

    return signals


async def fetch_plugplay(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        try:
            url = config.base_url + config.endpoints.get("games", "?format=json")
            resp = await client.get(url, timeout=30)
            resp.raise_for_status()
            games = resp.json()

            if isinstance(games, dict):
                games = games.get("games", games.get("data", []))
            if not isinstance(games, list):
                return []

            for game in games[:25]:
                play_count = game.get("play_count", game.get("plays", 0)) or 0
                rating = game.get("rating", game.get("score", 0)) or 0
                score = min((play_count / 5000.0) + (float(rating) / 5.0) * 0.3, 1.0) if play_count or rating else 0.2
                signals.append(MarketSignal(
                    source="plugplay",
                    signal_type="trending",
                    genre=game.get("category", game.get("genre")),
                    title=game.get("title", game.get("name", "Unknown")),
                    data={
                        "url": game.get("url", ""),
                        "play_count": play_count,
                        "rating": rating,
                    },
                    score=score,
                    captured_at=datetime.now(),
                ))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
            logger.error(f"PlugPlay fetch failed: {e}")

    return signals


async def fetch_x_trends(config: SourceConfig) -> list[MarketSignal]:
    bearer_token = os.environ.get(config.api_key_env, "")
    if not bearer_token:
        logger.debug("X_BEARER_TOKEN not set, skipping X trends fetch")
        return []

    signals = []
    gaming_keywords = {"game", "gaming", "indie", "steam", "playstation", "xbox", "nintendo",
                       "esport", "twitch", "roblox", "fortnite", "mobile game", "web game"}
    async with httpx.AsyncClient() as client:
        for woeid in getattr(config, "gaming_woeids", [1]):
            try:
                url = f"{config.base_url}/trends/by/woeid/{woeid}"
                headers = {"Authorization": f"Bearer {bearer_token}"}
                resp = await client.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                trends_data = resp.json().get("data", resp.json())

                trends_list = trends_data if isinstance(trends_data, list) else trends_data.get("trends", [])

                for trend in trends_list[:30]:
                    name = trend.get("trend", {}).get("name", trend.get("name", ""))
                    if not name:
                        continue
                    name_lower = name.lower()
                    if not any(kw in name_lower for kw in gaming_keywords):
                        continue

                    tweet_volume = trend.get("trend", {}).get("tweet_volume", trend.get("tweet_volume", 0)) or 0
                    score = min(tweet_volume / 50000.0, 1.0) if tweet_volume > 0 else 0.2
                    signals.append(MarketSignal(
                        source="x_trends",
                        signal_type="social_trend",
                        genre="gaming",
                        title=name,
                        data={
                            "tweet_volume": tweet_volume,
                            "woeid": woeid,
                        },
                        score=score,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"X trends fetch failed for woeid {woeid}: {e}")

    return signals


async def fetch_steam_spy(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    tags_to_query = config.tags or ["indie", "casual", "puzzle", "action", "strategy", "simulation", "arcade"]
    async with httpx.AsyncClient() as client:
        for tag in tags_to_query:
            try:
                url = f"{config.base_url}/api.php?request=tag&tag={tag.capitalize()}"
                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for app_id, app in list(data.items())[:20]:
                    if not isinstance(app, dict):
                        continue
                    positive = app.get("positive", 0) or 0
                    negative = app.get("negative", 0) or 0
                    players_2w = app.get("players_2weeks", 0) or 0
                    total_reviews = positive + negative
                    ratio = positive / total_reviews if total_reviews > 0 else 0.5
                    score = min(ratio * (players_2w / 10000.0 + 0.1), 1.0)

                    genre_raw = app.get("genre", "")
                    genre = genre_raw.split(",")[0].strip().lower() if genre_raw else tag
                    signals.append(MarketSignal(
                        source="steam_spy",
                        signal_type="steam_popularity",
                        genre=genre,
                        title=app.get("name", "Unknown"),
                        data={
                            "app_id": app_id,
                            "positive": positive,
                            "negative": negative,
                            "owners": app.get("owners", ""),
                            "players_2weeks": players_2w,
                            "genre_raw": genre_raw,
                        },
                        score=score,
                        captured_at=datetime.now(),
                    ))
                await asyncio.sleep(1)
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"SteamSpy fetch failed for tag '{tag}': {e}")

    return signals


async def fetch_youtube_trending(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        for feed_url in config.feeds:
            try:
                resp = await client.get(feed_url, timeout=30)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                for entry in feed.entries[:20]:
                    views = 0
                    for ns_key in entry:
                        if "views" in ns_key.lower():
                            try:
                                views = int(re.sub(r"[^\d]", "", str(entry[ns_key])))
                            except (ValueError, TypeError):
                                pass
                            break

                    score = min(views / 100000.0, 1.0) if views > 0 else 0.2
                    signals.append(MarketSignal(
                        source="youtube_trending",
                        signal_type="video_trend",
                        genre="gaming",
                        title=entry.get("title", "Unknown"),
                        data={
                            "url": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "views": views,
                        },
                        score=score,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"YouTube trending fetch failed for {feed_url}: {e}")

        search_terms = config.search_terms or ["indie game", "web game", "html5 game"]
        for term in search_terms:
            try:
                search_url = f"https://www.youtube.com/results?search_query={term}&sp=EgIQAQ%253D%253D"
                resp = await client.get(search_url, timeout=30, follow_redirects=True)
                html_text = resp.text

                video_titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"\]', html_text)
                view_counts = re.findall(r'"viewCount":"(\d+)"', html_text)

                for i, title in enumerate(video_titles[:10]):
                    views = int(view_counts[i]) if i < len(view_counts) else 0
                    score = min(views / 500000.0, 1.0) if views > 0 else 0.15
                    signals.append(MarketSignal(
                        source="youtube_trending",
                        signal_type="video_trend",
                        genre="gaming",
                        title=title,
                        data={
                            "search_term": term,
                            "views": views,
                        },
                        score=score,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"YouTube search fetch failed for '{term}': {e}")

    return signals


async def fetch_product_hunt(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    async with httpx.AsyncClient() as client:
        for feed_url in config.feeds:
            try:
                resp = await client.get(feed_url, timeout=30)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                for entry in feed.entries[:20]:
                    signals.append(MarketSignal(
                        source="product_hunt",
                        signal_type="new_product",
                        genre="gaming",
                        title=entry.get("title", "Unknown"),
                        data={
                            "url": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "summary": entry.get("summary", ""),
                        },
                        score=DEFAULT_SOURCE_SCORE,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"ProductHunt fetch failed for {feed_url}: {e}")

    return signals


async def fetch_tiktok_tags(config: SourceConfig) -> list[MarketSignal]:
    signals = []
    tags_to_search = config.tags or ["indiegame", "webgame", "html5game", "browsergame", "minigame"]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for tag in tags_to_search:
            try:
                url = f"{config.base_url}/tag/{tag}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                resp = await client.get(url, headers=headers, timeout=30)
                html_text = resp.text

                view_match = re.search(r'"playCount":(\d+)', html_text)
                views = int(view_match.group(1)) if view_match else 0

                title_matches = re.findall(r'"desc":"([^"]{10,100})"', html_text)
                unique_titles = list(dict.fromkeys(title_matches))[:5]

                if unique_titles:
                    for title in unique_titles:
                        score = min(views / 1000000.0, 1.0) if views > 0 else 0.3
                        signals.append(MarketSignal(
                            source="tiktok_tags",
                            signal_type="social_trend",
                            genre="gaming",
                            title=title,
                            data={
                                "tag": tag,
                                "views": views,
                            },
                            score=score,
                            captured_at=datetime.now(),
                        ))
                else:
                    signals.append(MarketSignal(
                        source="tiktok_tags",
                        signal_type="social_trend",
                        genre="gaming",
                        title=f"#{tag} trending",
                        data={"tag": tag, "views": views},
                        score=0.3,
                        captured_at=datetime.now(),
                    ))
            except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError, TypeError) as e:
                logger.error(f"TikTok tag fetch failed for #{tag}: {e}")

    return signals


def _score_itch_entry(entry, tags: list[str]) -> float:
    hot_genres = {"puzzle", "idle", "clicker", "platformer", "tower-defense", "roguelike", "match-3"}
    tag_match = len(set(t.lower() for t in tags) & hot_genres) / max(len(hot_genres), 1)
    return min(tag_match + 0.2, 1.0)


SOURCE_FETCHERS = {
    "itch_rss": fetch_itch_rss,
    "itch_api": fetch_itch_api,
    "statkraken": fetch_statkraken,
    "google_play": fetch_google_play,
    "reddit": fetch_reddit,
    "app_store": fetch_app_store,
    "plugplay": fetch_plugplay,
    "x_trends": fetch_x_trends,
    "steam_spy": fetch_steam_spy,
    "youtube_trending": fetch_youtube_trending,
    "product_hunt": fetch_product_hunt,
    "tiktok_tags": fetch_tiktok_tags,
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
