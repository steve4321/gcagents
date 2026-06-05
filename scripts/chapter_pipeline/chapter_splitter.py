"""Split a full-game GDD into multiple chapter GDDs.

Each chapter GDD is a self-contained design document that:
- References the shared World Bible for characters/locations/style
- Defines its own subset of nodes, dialogue, and choices
- Starts at a designated entry node and ends at a choice that links to next chapter
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def split_gdd_into_chapters(
    gdd: dict,
    bible: dict,
    num_chapters: int = 5,
    output_dir: Path | None = None,
) -> list[dict]:
    """Split a full GDD into N chapter GDDs, each referencing the world bible.

    Strategy:
    - Chapter 1: Introduction, character establishment, first choice
    - Chapter 2-N-1: Rising action, midpoint, complications
    - Chapter N: Climax, endings

    Each chapter GDD contains:
    - title, chapter_id, chapter_title
    - world_bible_path (reference, not embedded)
    - chapter-specific nodes/dialogue specs (filled by LLM)
    - entry_node, exit_node (for cross-chapter linking)
    - key_events that MUST happen in this chapter
    """
    chapters = []
    common_route = gdd.get("route_structure", {}).get("common_route", {})
    char_routes = gdd.get("route_structure", {}).get("character_routes", [])

    common_nodes = common_route.get("nodes", 20) if isinstance(common_route, dict) else 20

    chapter_themes = _plan_chapter_themes(gdd, num_chapters, char_routes)

    for i in range(num_chapters):
        ch_num = i + 1
        theme = chapter_themes[i]
        is_first = ch_num == 1
        is_last = ch_num == num_chapters

        nodes_per_route = max(8, common_nodes // num_chapters + 5)

        chapter_gdd = {
            "title": gdd.get("title", "Visual Novel"),
            "chapter_id": ch_num,
            "chapter_title": theme["title"],
            "total_chapters": num_chapters,
            "world_bible_path": "world_bible.json",
            "genre": gdd.get("genre", "visual-novel"),
            "is_first_chapter": is_first,
            "is_last_chapter": is_last,
            "synopsis": theme["synopsis"],
            "key_events": theme["key_events"],
            "narrative_premise": gdd.get("narrative_premise", ""),
            "player_protagonist": gdd.get("player_protagonist", {}),
            "character_roster": gdd.get("character_roster", []),
            "stat_system": gdd.get("stat_system", {}),
            "route_structure": {
                "common_route": {
                    "name": f"chapter_{ch_num}",
                    "theme": theme["theme"],
                    "nodes": nodes_per_route,
                },
                "character_routes": [
                    {
                        "name": f"{r.get('name', f'route_{idx}')}_ch{ch_num}",
                        "heroine": r.get("heroine", ""),
                        "theme": r.get("theme", ""),
                        "nodes": max(6, nodes_per_route // 2),
                    }
                    for idx, r in enumerate(char_routes)
                ],
            },
            "branching_tree": {
                "root": f"ch{ch_num}_start" if not is_first else "common_start",
                "nodes": {},
            },
            "ending_conditions": gdd.get("ending_conditions", []) if is_last else [],
            "cg_milestones": _chapter_cgs(gdd, ch_num, num_chapters),
            "scenes": gdd.get("scenes", []),
            "art_style": gdd.get("art_style", {}),
            "audio": gdd.get("audio", {}),
            "entry_node": "common_start" if is_first else f"ch{ch_num}_start",
            "exit_node": f"ch{ch_num}_end" if not is_last else None,
            "writing_directive": _writing_directive_for_chapter(theme, ch_num, num_chapters),
        }
        chapters.append(chapter_gdd)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for ch in chapters:
            ch_path = output_dir / f"chapter_{ch['chapter_id']}_gdd.json"
            ch_path.write_text(
                json.dumps(ch, indent=2, ensure_ascii=False)
            )

    return chapters


def _plan_chapter_themes(gdd: dict, num_chapters: int, char_routes: list) -> list[dict]:
    """Plan the dramatic arc across chapters using Freytag's pyramid."""
    themes = []
    if num_chapters == 1:
        themes.append({
            "title": "The Complete Story",
            "theme": "complete narrative",
            "synopsis": gdd.get("narrative_premise", "")[:300],
            "key_events": gdd.get("cg_milestones", [])[:3],
        })
        return themes

    if num_chapters == 3:
        titles = ["The Awakening", "The Resistance", "The Reckoning"]
        synopses = [
            "The protagonist discovers the corruption and meets potential allies.",
            "Tensions rise as the protagonist joins the resistance and faces moral choices.",
            "The final confrontation with corporate power determines the fate of all.",
        ]
    elif num_chapters == 5:
        titles = [
            "第一章：觉醒 (The Awakening)",
            "第二章：抉择 (The Crossroads)",
            "第三章：风暴 (The Storm)",
            "第四章：牺牲 (The Sacrifice)",
            "第五章：革命 (The Revolution)",
        ]
        synopses = [
            "主角林月在巨型公司Omnicorp工作，发现财务数据异常，偶遇神秘工运领袖李伟，被迫做出第一个道德抉择。",
            "主角深入接触劳工组织，了解数字游民陈雪的故事，面临是否泄露公司机密的抉择，引入黑客Zhao Ming。",
            "公司安保升级，主角在追查中遭遇背叛（Zhang Yan），工人运动受挫，团队必须重组。",
            "主角和盟友策划一次大胆行动，但必须牺牲部分安全换取关键证据。",
            "最终对决Omnicorp CEO，多个结局分支根据之前的道德抉择展开。",
        ]
    else:
        titles = [f"Chapter {i+1}" for i in range(num_chapters)]
        synopses = [
            f"Chapter {i+1} of the story continues the narrative." for i in range(num_chapters)
        ]

    for i in range(num_chapters):
        themes.append({
            "title": titles[i] if i < len(titles) else f"Chapter {i+1}",
            "theme": _theme_for_position(i, num_chapters),
            "synopsis": synopses[i] if i < len(synopses) else "",
            "key_events": [],
        })
    return themes


def _theme_for_position(idx: int, total: int) -> str:
    position = idx / max(total - 1, 1)
    if position < 0.2:
        return "introduction and inciting incident"
    elif position < 0.5:
        return "rising action and character development"
    elif position < 0.8:
        return "complications and midpoint reversal"
    else:
        return "climax and resolution"


def _chapter_cgs(gdd: dict, ch_num: int, total: int) -> list[dict]:
    """Distribute CG milestones across chapters."""
    all_cgs = gdd.get("cg_milestones", [])
    if not all_cgs:
        return []
    per_chapter = max(1, len(all_cgs) // total)
    start = (ch_num - 1) * per_chapter
    end = start + per_chapter if ch_num < total else len(all_cgs)
    return all_cgs[start:end]


def _writing_directive_for_chapter(theme: dict, ch_num: int, total: int) -> str:
    position = ch_num / total
    if position <= 0.25:
        return (
            "OPENING CHAPTER: Establish the world, protagonist's daily life, and the "
            "first hint of conflict. Introduce 2-3 key characters through natural "
            "dialogue. The tone is restrained tension — show, don't tell. "
            "End the chapter on a moral choice that has no obviously 'right' answer."
        )
    elif position <= 0.5:
        return (
            "RISING ACTION: Deepen relationships, reveal more of the conspiracy, "
            "introduce complications. Use the chapter to explore at least one "
            "character's backstory through dialogue. The protagonist's worldview "
            "should be challenged but not yet broken."
        )
    elif position <= 0.75:
        return (
            "MIDPOINT/COMPLICATION: A betrayal or revelation that changes the stakes. "
            "A trusted character should act against expectations. The protagonist "
            "faces their first major loss. Dialogue should be sharper, more clipped, "
            "reflecting rising tension."
        )
    else:
        return (
            "CLIMAX/RESOLUTION: The final confrontation. Multiple ending paths "
            "open based on accumulated stats. Dialogue should be the most elevated "
            "of the entire game — every line carries weight. Allow for at least "
            "3 distinct endings (good, neutral, bad) reachable from this chapter."
        )
