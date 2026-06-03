"""Translate game strings using LLM."""
from __future__ import annotations

import json
import re

from loguru import logger

from shared.constants import DEFAULT_ANALYSIS_MODEL
from shared.llm_client import llm

TARGET_LOCALES = {
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "pt": "Portuguese",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "tr": "Turkish",
    "it": "Italian",
    "pl": "Polish",
}


async def translate_strings(
    strings: dict[str, str],
    locales: list[str] | None = None,
    game_genre: str = "",
) -> dict[str, dict[str, str]]:
    """Translate game strings to target locales using LLM.

    Args:
        strings: {string_id: english_text}
        locales: target locale codes (default: top 5 by market size)
        game_genre: context for better translations

    Returns:
        {locale_code: {string_id: translated_text}}
    """
    if locales is None:
        locales = ["ja", "ko", "es", "pt", "de"]

    model = DEFAULT_ANALYSIS_MODEL

    results: dict[str, dict[str, str]] = {}

    for locale in locales:
        lang_name = TARGET_LOCALES.get(locale, locale)

        prompt = (
            f"Translate these game UI strings from English to {lang_name}.\n"
            f"Game genre: {game_genre}\n"
            f"Keep translations short and appropriate for games (UI context).\n"
            f"Return ONLY a JSON object mapping string IDs to translations.\n\n"
            f"Strings:\n{json.dumps(strings, indent=2, ensure_ascii=False)}"
        )

        try:
            response, usage = await llm.chat_completion(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are a game localization expert. "
                            f"Translate UI strings to {lang_name}. "
                            f"Keep game-appropriate tone. Return only valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
                agent_name="localizer",
            )

            translated = _parse_json_response(response)
            if translated and isinstance(translated, dict):
                valid = {k: v for k, v in translated.items() if k in strings}
                if valid:
                    results[locale] = valid
                    logger.info(f"Translated {len(valid)} strings to {lang_name}")
                else:
                    logger.warning(f"No valid translations for {lang_name}")
            else:
                logger.warning(f"Failed to parse translations for {lang_name}")

        except Exception as e:
            logger.error(f"Translation error for {lang_name}: {e}")
            continue

    return results


def _parse_json_response(text: str) -> dict | None:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None
