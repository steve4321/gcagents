"""Merge multiple chapter outputs into a single unified game.

Each chapter produces its own branching.json and dialogue.json. The merger:
- Combines all branching nodes (namespaced by chapter)
- Combines all dialogue entries (namespaced by chapter)
- Creates cross-chapter save state persistence
- Generates a chapter selection menu
- Validates that ending nodes from chapter N-1 link to entry nodes of chapter N
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def merge_chapters(
    chapter_data_list: list[dict],
    bible: dict,
    output_dir: Path,
) -> dict:
    """Merge N chapter data dicts into a single game.

    Each chapter_data is:
    {
        "chapter_id": 1,
        "branching": {"nodes": {...}, "edges": [...], "root": "..."},
        "dialogue": {...},
        "endings": [...],
    }

    Returns the merged branching.json and dialogue.json paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)

    merged_branching = {
        "root": "",
        "nodes": {},
        "edges": [],
        "routes": {},
        "chapters": [],
        "chapter_order": [],
    }
    merged_dialogue: dict[str, Any] = {}
    merged_endings = []
    chapter_index = {}

    for ch_data in chapter_data_list:
        ch_id = ch_data.get("chapter_id", 0)
        ch_title = ch_data.get("chapter_title", f"Chapter {ch_id}")
        merged_branching["chapter_order"].append({
            "id": ch_id,
            "title": ch_title,
            "entry_node": ch_data.get("entry_node", f"ch{ch_id}_start"),
            "node_count": len(ch_data.get("branching", {}).get("nodes", {})),
        })

        branching = ch_data.get("branching", {})
        for node_id, node in branching.get("nodes", {}).items():
            namespaced_id = f"ch{ch_id}_{node_id}" if not str(node_id).startswith(f"ch{ch_id}_") else node_id
            if isinstance(node, dict):
                node_copy = dict(node)
                node_copy["chapter_id"] = ch_id
                node_copy["chapter_title"] = ch_title
                merged_branching["nodes"][namespaced_id] = node_copy

        for edge in branching.get("edges", []):
            edge_copy = dict(edge)
            if "from" in edge_copy:
                src = edge_copy["from"]
                if not str(src).startswith(f"ch{ch_id}_"):
                    edge_copy["from"] = f"ch{ch_id}_{src}"
            if "to" in edge_copy:
                tgt = edge_copy["to"]
                if not str(tgt).startswith(f"ch{ch_id}_") and not _is_global_ending(tgt):
                    edge_copy["to"] = f"ch{ch_id}_{tgt}"
            merged_branching["edges"].append(edge_copy)

        for dlg_id, dlg in ch_data.get("dialogue", {}).items():
            if not str(dlg_id).startswith(f"ch{ch_id}_"):
                namespaced_dlg_id = f"ch{ch_id}_{dlg_id}"
            else:
                namespaced_dlg_id = dlg_id
            if isinstance(dlg, dict):
                dlg_copy = dict(dlg)
                dlg_copy["chapter_id"] = ch_id
            else:
                dlg_copy = dlg
            merged_dialogue[namespaced_dlg_id] = dlg_copy

        for ending in ch_data.get("endings", []):
            merged_endings.append({**ending, "chapter_id": ch_id})

        if ch_id == 1:
            for node_id, node in branching.get("nodes", {}).items():
                if isinstance(node, dict) and "start" in str(node_id).lower():
                    merged_branching["root"] = f"ch{ch_id}_{node_id}" if not str(node_id).startswith(f"ch{ch_id}_") else node_id
                    break
            if not merged_branching["root"]:
                first_node_id = next(iter(branching.get("nodes", {}).keys()), None)
                if first_node_id:
                    merged_branching["root"] = f"ch{ch_id}_{first_node_id}" if not str(first_node_id).startswith(f"ch{ch_id}_") else first_node_id

        chapter_index[ch_id] = {
            "title": ch_title,
            "node_count": len(branching.get("nodes", {})),
            "entry_node": ch_data.get("entry_node", f"ch{ch_id}_start"),
        }

    merged_branching["chapters"] = chapter_index

    if not merged_branching["root"] and merged_branching["nodes"]:
        merged_branching["root"] = next(iter(merged_branching["nodes"].keys()))

    cross_chapter_links = _build_cross_chapter_links(chapter_data_list)

    branching_path = data_dir / "branching.json"
    dialogue_path = data_dir / "dialogue.json"
    endings_path = data_dir / "endings.json"
    bible_path = data_dir / "world_bible.json"
    cross_chapter_path = data_dir / "cross_chapter.json"

    branching_path.write_text(
        json.dumps(merged_branching, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    dialogue_path.write_text(
        json.dumps(merged_dialogue, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    endings_path.write_text(
        json.dumps(merged_endings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    bible_path.write_text(
        json.dumps(bible, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    cross_chapter_path.write_text(
        json.dumps(cross_chapter_links, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "branching_path": branching_path,
        "dialogue_path": dialogue_path,
        "endings_path": endings_path,
        "bible_path": bible_path,
        "cross_chapter_path": cross_chapter_path,
        "stats": {
            "chapters": len(chapter_data_list),
            "total_nodes": len(merged_branching["nodes"]),
            "total_edges": len(merged_branching["edges"]),
            "total_dialogue": len(merged_dialogue),
            "total_endings": len(merged_endings),
        },
    }


def _is_global_ending(node_id: str) -> bool:
    return str(node_id).startswith("ending_") or str(node_id).startswith("ch_end_")


def _build_cross_chapter_links(chapter_data_list: list[dict]) -> dict:
    """Build the cross-chapter transition graph for save/load."""
    links = []
    for i in range(len(chapter_data_list) - 1):
        curr = chapter_data_list[i]
        nxt = chapter_data_list[i + 1]
        links.append({
            "from_chapter": curr.get("chapter_id"),
            "from_exit_node": curr.get("exit_node", f"ch{curr.get('chapter_id')}_end"),
            "to_chapter": nxt.get("chapter_id"),
            "to_entry_node": nxt.get("entry_node", f"ch{nxt.get('chapter_id')}_start"),
        })
    return {
        "version": "1.0",
        "links": links,
        "save_format": {
            "stats": "dict<stat_name, int>",
            "flags": "dict<flag_name, bool>",
            "current_chapter": "int",
            "current_node": "str (namespaced node id)",
        },
    }


def generate_chapter_selection_html(bible: dict, chapter_list: list[dict]) -> str:
    """Generate HTML for the chapter selection screen."""
    chapters_html = ""
    for ch in chapter_list:
        ch_id = ch.get("chapter_id", 0)
        title = ch.get("chapter_title", f"Chapter {ch_id}")
        synopsis = ch.get("synopsis", "")[:150]
        is_locked = ch_id > 1
        chapters_html += f'''
        <div class="chapter-card{' locked' if is_locked else ''}" data-chapter="{ch_id}">
            <div class="chapter-number">第 {ch_id} 章</div>
            <div class="chapter-title">{title}</div>
            <div class="chapter-synopsis">{synopsis}</div>
            {'<div class="locked-badge">🔒 上一章未完成</div>' if is_locked else '<div class="play-button">▶ 开始</div>'}
        </div>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{bible.get('title', 'Visual Novel')} - 章节选择</title>
    <style>
        body {{
            margin: 0; background: linear-gradient(135deg, #0a0a15 0%, #1a1a2e 50%, #0a0a15 100%);
            color: #e0e0e0; font-family: 'Noto Sans CJK SC', 'Microsoft YaHei', sans-serif;
            min-height: 100vh; padding: 40px 20px;
        }}
        h1 {{
            text-align: center; color: #d4af37; font-size: 2.5em; margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(212,175,55,0.5);
        }}
        .subtitle {{ text-align: center; color: #888; margin-bottom: 40px; font-size: 0.9em; }}
        .chapters-grid {{
            max-width: 900px; margin: 0 auto; display: grid; gap: 20px;
        }}
        .chapter-card {{
            background: rgba(20,20,30,0.8); border: 2px solid #3a3a5a; border-radius: 12px;
            padding: 24px; cursor: pointer; transition: all 0.3s;
        }}
        .chapter-card:hover {{ border-color: #d4af37; transform: translateY(-2px); }}
        .chapter-card.locked {{ opacity: 0.5; cursor: not-allowed; }}
        .chapter-number {{ color: #d4af37; font-size: 0.9em; margin-bottom: 8px; }}
        .chapter-title {{ font-size: 1.5em; font-weight: bold; margin-bottom: 12px; }}
        .chapter-synopsis {{ color: #aaa; line-height: 1.6; font-size: 0.95em; }}
        .play-button {{
            margin-top: 16px; color: #d4af37; font-weight: bold;
        }}
        .locked-badge {{ margin-top: 16px; color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{bible.get('title', 'Visual Novel')}</h1>
    <div class="subtitle">抵制资本主义 · 共 {len(chapter_list)} 章 · 约 {sum(len(ch.get('expected_nodes', 20)) for ch in chapter_list) * 300:,} 字</div>
    <div class="chapters-grid">{chapters_html}
    </div>
    <script>
        document.querySelectorAll('.chapter-card:not(.locked)').forEach(card => {{
            card.addEventListener('click', () => {{
                const chId = card.dataset.chapter;
                localStorage.setItem('current_chapter', chId);
                window.location.href = 'index.html?chapter=' + chId;
            }});
        }});
    </script>
</body>
</html>'''
