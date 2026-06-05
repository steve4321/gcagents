"""RenJS story script generator.

The pipeline generates 4 YAML files per game:
- Config.yaml — engine configuration (positions, transitions, timing)
- Setup.yaml — asset registry (backgrounds, characters, CGs, music, SFX)
- Story.yaml — the actual story (scene/act/choice structure)
- GUI.yaml — UI layout (optional, uses defaults if missing)

The LLM only writes Story.yaml (the story itself). Config/Setup/GUI can
be auto-generated from the World Bible + production plan.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate_gui_yaml(plan: dict) -> str:
    """Generate GUI.yaml with proper messageBox/choices configuration.

    Uses Phaser's built-in default font ('Arial') so we don't need to
    ship font files. Coordinates are for 1024x768 canvas.
    """
    return """# RenJS GUI.yaml — auto-generated, compatible with RenJS V2
name: default
resolution:
  - 1024
  - 768
assetCounter: 1
config:
  hud:
    - id: default
      type: choices
      x: 512
      'y': 400
      alignment: centered
      separation: 15
      text:
        style:
          font: "Georgia, serif"
          fontSize: 26px
          fill: "#d4af37"
          align: left
          boundsAlignH: center
          boundsAlignV: middle
      hover:
        fill: "#ffffff"
    - id: default
      type: messageBox
      x: 40
      'y': 530
      width: 944
      height: 200
      backgroundColor: "rgba(0, 0, 0, 0.85)"
      text:
        x: 24
        'y': 24
        style:
          font: "Georgia, serif"
          fontSize: 22px
          fill: "#ffffff"
          align: left
          wordWrap: true
          wordWrapWidth: 896
    - id: default
      type: nameBox
      x: 60
      'y': 490
      text:
        x: 0
        'y': 0
        style:
          font: "Georgia, serif"
          fontSize: 24px
          fill: "#d4af37"
          align: left
          boundsAlignH: left
          boundsAlignV: middle
    - id: default
      type: log
      x: 512
      'y': 100
      width: 944
      height: 400
      backgroundColor: "rgba(0, 0, 0, 0.8)"
      text:
        style:
          font: "Georgia, serif"
          fontSize: 20px
          fill: "#cccccc"
          align: left
          wordWrap: true
          wordWrapWidth: 920
"""


def generate_config_yaml(plan: dict) -> str:
    """Generate Config.yaml from the production plan.

    This is fully auto-generated; the LLM doesn't touch it.
    """
    title = plan.get("game_title", "Visual Novel")
    num_chapters = plan.get("num_chapters", 1)

    return f"""# RenJS Config.yaml — auto-generated from production plan
# Do not edit manually; regenerate via the pipeline.

positions:
  OUTLEFT:
    x: -133
    y: 600
  LEFT:
    x: 133
    y: 600
  DEFAULT:
    x: 400
    y: 600
  CENTER:
    x: 400
    y: 600
  RIGHT:
    x: 666
    y: 600
  OUTRIGHT:
    x: 933
    y: 600

transitions:
  defaults:
    characters: FADE
    backgrounds: FADE
    cgs: FADE
    music: FADE
  say: CUT
  visualChoices: FADE
  textChoices: CUT
  menus: FADE
  skippable: false

fadetime: 750
skiptime: 50
autotime: 150
timeout: 5000
logChoices: true

precomputeBreakLines: true

userPreferences:
  textSpeed: 60
  autoSpeed: 150
  bgmv: 0.8
  sfxv: 0.5
  muted: false

# Chapter navigation metadata (used by chapter selection menu)
gameMeta:
  title: "{title}"
  chapters: {num_chapters}
"""


def generate_setup_yaml(plan: dict, assets_dir: str = "assets") -> str:
    """Generate Setup.yaml from the production plan's art/audio manifest.

    Maps each planned asset to its file path in the game directory.
    """
    art = plan.get("art", {})

    backgrounds_lines = ["backgrounds:"]
    for bg in art.get("backgrounds", []):
        bg_id = bg["id"]
        bg_path = bg["file_path"].replace("public/assets/", f"{assets_dir}/")
        backgrounds_lines.append(f'  {bg_id}: {bg_path}')

    characters_lines = ["characters:"]
    for char in art.get("characters", []):
        char_id = char["id"]
        char_name = char.get("name", char_id)
        looks_lines = []
        for expr, path in char.get("file_paths", {}).items():
            clean_path = path.replace("public/assets/", f"{assets_dir}/")
            looks_lines.append(f'      {expr}: {clean_path}')
        if not looks_lines:
            looks_lines.append(f'      neutral: {assets_dir}/characters/{char_id}_neutral.png')
        characters_lines.append(f'  {char_id}:')
        characters_lines.append(f'    displayName: {char_name}')
        characters_lines.append(f'    speechColour: "#ca90cf"')
        characters_lines.append(f'    looks:')
        characters_lines.extend(looks_lines)

    cgs_lines = ["cgs:"]
    for cg in art.get("cg", []):
        cg_id = cg["id"]
        cg_path = cg["file_path"].replace("public/assets/", f"{assets_dir}/")
        cgs_lines.append(f'  {cg_id}: {cg_path}')

    audio = plan.get("audio", {})
    music_lines = ["music:"]
    for bgm in audio.get("bgm", []):
        music_lines.append(f'  {bgm["id"]}: {bgm["file_path"].replace("public/assets/", f"{assets_dir}/")}')

    sfx_lines = ["sfx:"]
    for sfx in audio.get("sfx", []):
        sfx_lines.append(f'  {sfx["id"]}: {sfx["file_path"].replace("public/assets/", f"{assets_dir}/")}')

    sections = []
    if len(backgrounds_lines) > 1:
        sections.append("\n".join(backgrounds_lines))
    if len(characters_lines) > 1:
        sections.append("\n".join(characters_lines))
    if len(cgs_lines) > 1:
        sections.append("\n".join(cgs_lines))
    if len(music_lines) > 1:
        sections.append("\n".join(music_lines))
    if len(sfx_lines) > 1:
        sections.append("\n".join(sfx_lines))

    return "# RenJS Setup.yaml — auto-generated from production plan\n" + "\n\n".join(sections) + "\n"


def build_story_prompt(
    chapter_gdd: dict,
    world_bible: dict,
    plan: dict,
    chapter_index: int,
    total_chapters: int,
) -> str:
    """Build the LLM prompt for generating one chapter's Story.yaml.

    This is the ONLY thing the LLM needs to write for the chapter.
    The story is in RenJS screenplay format (YAML).
    """
    ch_id = chapter_gdd.get("chapter_id", chapter_index + 1)
    ch_title = chapter_gdd.get("chapter_title", f"Chapter {ch_id}")
    is_last = ch_id == total_chapters

    char_names = [c.get("name", "?") for c in world_bible.get("characters", [])]
    location_names = [loc.get("name", "?") for loc in world_bible.get("locations", [])]
    stat_names = [s.get("name", "?") for s in world_bible.get("stats", [])]

    available_bgs = [bg["id"] for bg in plan.get("art", {}).get("backgrounds", [])
                     if bg.get("chapter") == ch_id]
    available_chars = [c["id"] for c in plan.get("art", {}).get("characters", [])]
    available_cgs = [cg["id"] for cg in plan.get("art", {}).get("cg", [])
                     if cg.get("chapter") == ch_id]

    if not available_bgs:
        available_bgs = [f"ch{ch_id}_intro", f"ch{ch_id}_scene"]
    if not available_cgs:
        available_cgs = []

    return f"""You are writing Chapter {ch_id} of {total_chapters} of a Visual Novel.

=== GAME BIBLE (canon — DO NOT contradict) ===
Title: {world_bible.get('title')}
Setting: {world_bible.get('world', {}).get('setting', '')[:300]}
Tone: {world_bible.get('world', {}).get('tone', '')}
Characters (use exact names): {', '.join(char_names)}
Locations (use exact names): {', '.join(location_names)}
Stats (use exact names): {', '.join(stat_names)}

=== CHAPTER INSTRUCTIONS ===
Chapter title: {ch_title}
Synopsis: {chapter_gdd.get('synopsis', '')[:500]}
Writing directive: {chapter_gdd.get('writing_directive', '')[:400]}
This is chapter {ch_id} of {total_chapters}.

=== AVAILABLE ASSETS (use these exact IDs) ===
Backgrounds: {', '.join(available_bgs)}
Characters: {', '.join(available_chars)}
CGs: {', '.join(available_cgs) if available_cgs else '(none for this chapter)'}

=== RENJS SCRIPT SYNTAX (YAML) ===
- show <background_id>: — show a background
- show <character_id>: <expression> AT <LEFT|CENTER|RIGHT> — show character
- <character_id> says [expression]: <text> — character speaks
- choice: — present choices, each indented as "  - \"text\":" with actions
- play <bgm_id>: — play music
- play sfx <sfx_id>: — play sound effect
- hide <character_id>: — hide character
- scene: <next_scene_name> — jump to scene
- if <var>: — conditional
- set <var>: <value> — set variable
- modify <var>: <delta> — modify stat
- end: — end the chapter

CRITICAL RULES:
1. ALL dialogue text MUST be 200-400 Chinese characters of literary prose
2. Use only character names from the bible (no new characters)
3. Use only background IDs from the AVAILABLE ASSETS list
4. Use the world bible stats: when player makes a meaningful choice, use `modify <stat>: <delta>`
5. Generate 30-50 dialogue entries (say actions) in this chapter
6. Generate 3-5 choices that affect stats
7. Start with `start:` scene name
8. Keep YAML valid (proper indentation, quotes for special characters)
9. {('End the chapter with a choice that leads to next chapter entry' if not is_last else 'End the chapter with multiple ending paths based on stats')}

Output: ONLY the YAML content starting with `start:`. No prose, no markdown fences."""


def merge_story_yamls(chapter_stories: list[str]) -> str:
    """Merge multiple chapter Story.yaml files into one.

    Each chapter's `start:` scene is renamed to `ch<N>_start:` and
    the chapters are linked via cross-chapter choice targets.
    """
    merged_scenes: list[str] = []
    chapter_entries: list[str] = []
    for i, story in enumerate(chapter_stories):
        ch_id = i + 1
        renamed = _rename_story_scenes(story, ch_id)
        if i == 0:
            merged_scenes.append(renamed)
        else:
            scenes_after_start = _extract_scenes_after_start(renamed)
            merged_scenes.append(scenes_after_start)
        chapter_entries.append(f"  ch{ch_id}_start:")

    return "\n".join(merged_scenes)


def _rename_story_scenes(story: str, chapter_id: int) -> str:
    """Rename all top-level scene names in a story to be chapter-scoped."""
    import re
    lines = story.split("\n")
    result: list[str] = []
    scene_pattern = re.compile(r"^(\s*)([a-zA-Z_][a-zA-Z0-9_]*):\s*$")
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            result.append(line)
            continue
        m = scene_pattern.match(line)
        if m and not line.startswith(" "):
            indent, name = m.group(1), m.group(2)
            if name in ("start", "end"):
                result.append(line)
            else:
                result.append(f"{indent}ch{chapter_id}_{name}:")
        else:
            result.append(line)
    return "\n".join(result)


def _extract_scenes_after_start(story: str) -> str:
    """Return everything in the story except the `start:` scene line itself."""
    lines = story.split("\n")
    out: list[str] = []
    skip_start = True
    for line in lines:
        if skip_start and line.strip() == "start:":
            skip_start = False
            continue
        if not skip_start:
            out.append(line)
    return "\n".join(out)


def generate_boot_js(plan: dict, game_dir: str = "") -> str:
    """Generate boot.js that bootstraps the RenJS game."""
    title = plan.get("game_title", "Visual Novel")
    return f"""// Auto-generated boot.js — bootstraps RenJS
const RenJSConfig = {{
  name: '{title}',
  w: 1024,
  h: 768,
  renderer: Phaser.AUTO,
  scaleMode: Phaser.ScaleManager.SHOW_ALL,
  loadingScreen: {{
    background: 'vendor/renjs/loading_bg.png',
    loadingBar: {{
      asset: 'vendor/renjs/loading_bar.png',
      position: {{ x: 109, y: 458 }},
      size: {{ w: 578, h: 82 }},
    }},
  }},
  fonts: '',
  guiConfig: 'story/GUI.yaml',
  storyConfig: 'story/Config.yaml',
  storySetup: 'story/Setup.yaml',
  storyText: [
    'story/Story.yaml'
  ],
  logChoices: true,
  userPreferences: {{
    textSpeed: 60,
    autoSpeed: 150,
    bgmv: 0.8,
    sfxv: 0.5,
    muted: false,
  }},
}};

const RenJSGame = new RenJS.game(RenJSConfig);
RenJSGame.launch();
"""


def generate_index_html(plan: dict, vendor_path: str = "vendor/renjs/renjs.js") -> str:
    """Generate the single index.html for the entire game."""
    title = plan.get("game_title", "Visual Novel")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      margin: 0; padding: 0; background: #000;
      display: flex; justify-content: center; align-items: center;
      min-height: 100vh;
      font-family: 'Noto Sans CJK SC', 'Microsoft YaHei', 'PingFang SC', sans-serif;
      overflow: hidden;
    }}
    canvas {{ display: block; }}
  </style>
</head>
<body>
  <script src="{vendor_path}"></script>
  <script src="boot.js"></script>
</body>
</html>
"""
