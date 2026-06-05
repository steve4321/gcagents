"""Ad SDK integration utilities for generated games."""

import json

from shared.constants import PLATFORM_AD_PATTERNS, PLATFORM_SDK_SNIPPETS


def get_sdk_script_tags(platforms: list[str]) -> str:
    """Return HTML script tags for the given platforms."""
    tags = []
    for p in platforms:
        snippet = PLATFORM_SDK_SNIPPETS.get(p, "")
        if snippet:
            tags.append(snippet)
    return "\n    ".join(tags)


def get_sdk_init_js(platforms: list[str]) -> str:
    """Return JS initialization code for ad SDKs."""
    inits = []
    for p in platforms:
        pattern = PLATFORM_AD_PATTERNS.get(p, {})
        init = pattern.get("init", "")
        if init:
            inits.append(init)
    return "\n    ".join(inits)


def get_ad_break_js(platforms: list[str]) -> str:
    """Return JS code for triggering ad breaks (call on game-over)."""
    ads = []
    for p in platforms:
        pattern = PLATFORM_AD_PATTERNS.get(p, {})
        adbreak = pattern.get("adbreak", "")
        if adbreak:
            ads.append(f"// {p}\n    {adbreak}")
    return "\n    ".join(ads)


def get_happytime_js(platforms: list[str]) -> str:
    """Return JS code for happytime events (call on achievements)."""
    events = []
    for p in platforms:
        pattern = PLATFORM_AD_PATTERNS.get(p, {})
        happytime = pattern.get("happytime", "")
        if happytime:
            events.append(f"// {p}\n    {happytime}")
    return "\n    ".join(events)


def get_all_platforms() -> list[str]:
    """Return all platforms that have SDK support."""
    return list(PLATFORM_SDK_SNIPPETS.keys())


def get_ad_helper_js(platforms: list[str]) -> str:
    """Return the global ad helper JS block for injection into index.html.

    Defines window.__triggerAdBreak and window.__triggerHappyTime as safe
    no-op stubs that activate only when the corresponding SDK is loaded.
    Also sets window.__AD_CONFIG__ with the list of target platforms.
    """
    if not platforms:
        return """<script>
    window.__AD_CONFIG__ = [];
    window.__triggerAdBreak = function() {};
    window.__triggerHappyTime = function() {};
    </script>"""

    ad_config = json.dumps(platforms)
    return f"""<script>
    window.__AD_CONFIG__ = {ad_config};
    </script>
    <script>
    window.__triggerAdBreak = function() {{
        try {{
            if (window.CrazyGames?.CrazySDK) {{
                const sdk = window.CrazyGames.CrazySDK.getInstance();
                sdk.requestAd('midgame', () => {{}}, () => {{}});
            }}
            if (window.PokiSDK) {{
                window.PokiSDK.commercialBreak().then(() => {{}});
            }}
        }} catch (e) {{ /* ad not available */ }}
    }};
    window.__triggerHappyTime = function() {{
        try {{
            if (window.CrazyGames?.CrazySDK) {{
                window.CrazyGames.CrazySDK.getInstance().happytime();
            }}
        }} catch (e) {{}}
    }};
    </script>"""
