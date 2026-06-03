from __future__ import annotations

import json
import re
import time
import uuid

from loguru import logger

from shared.config import load_config
from shared.llm_client import llm

_CONCEPT_SYSTEM = """You are a game designer. Given a brief concept prompt, produce a minimal JSON game spec.

Required fields:
- name: short game name (lowercase, hyphenated)
- title: display title
- genre: one of (shooter, platformer, puzzle, runner, arena, rpg, strategy, arcade)
- description: one sentence
- player_color: hex color for player rectangle
- enemy_color: hex color for enemy/obstacle
- collectible_color: hex color for collectibles
- bg_color: hex color for background
- controls: object with "move" (e.g. "arrow keys") and "action" (e.g. "space to shoot")
- core_mechanic: one sentence describing the main interaction
- score_label: label for score display (e.g. "Score", "Kills", "Distance")
- win_condition: how to win or when game ends
- theme: emoji representing the theme

Output ONLY valid JSON, no markdown fences."""

_GAME_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #111; display: flex; justify-content: center; align-items: center; height: 100vh; font-family: sans-serif; color: #fff; overflow: hidden; }}
  #gameContainer {{ position: relative; }}
  canvas {{ border: 2px solid #333; display: block; image-rendering: pixelated; }}
  #hud {{ position: absolute; top: 8px; left: 8px; right: 8px; display: flex; justify-content: space-between; font-size: 14px; pointer-events: none; z-index: 10; }}
  #hud span {{ background: rgba(0,0,0,0.6); padding: 4px 10px; border-radius: 4px; }}
  #overlay {{ position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; background: rgba(0,0,0,0.75); z-index: 20; }}
  #overlay h1 {{ font-size: 32px; margin-bottom: 12px; }}
  #overlay p {{ font-size: 16px; color: #aaa; margin-bottom: 8px; }}
  #overlay button {{ margin-top: 16px; padding: 10px 32px; font-size: 16px; background: {player_color}; border: none; border-radius: 6px; cursor: pointer; color: #fff; font-weight: bold; }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>
<div id="gameContainer">
  <canvas id="c" width="640" height="480"></canvas>
  <div id="hud">
    <span id="scoreLabel">{score_label}: <b id="scoreVal">0</b></span>
    <span id="livesLabel">Lives: <b id="livesVal">3</b></span>
  </div>
  <div id="overlay">
    <h1>{title}</h1>
    <p>{description}</p>
    <p>{controls_text} &mdash; {core_mechanic}</p>
    <button id="startBtn">Start Game</button>
  </div>
</div>
<script>
(function() {{
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;

  const COLORS = {{
    bg: '{bg_color}',
    player: '{player_color}',
    enemy: '{enemy_color}',
    collectible: '{collectible_color}',
  }};

  let state = 'menu';
  let score = 0, lives = 3;
  let player, entities, particles, spawnTimer;

  const keys = {{}};
  document.addEventListener('keydown', e => {{ keys[e.code] = true; e.preventDefault(); }});
  document.addEventListener('keyup', e => {{ keys[e.code] = false; }});

  function init() {{
    player = {{ x: W/2 - 15, y: H - 60, w: 30, h: 30, speed: 4, dx: 0, dy: 0 }};
    entities = [];
    particles = [];
    spawnTimer = 0;
    score = 0;
    lives = 3;
    updateHUD();
  }}

  function updateHUD() {{
    document.getElementById('scoreVal').textContent = score;
    document.getElementById('livesVal').textContent = lives;
  }}

  function spawn() {{
    const r = Math.random();
    if (r < 0.6) {{
      entities.push({{ type:'enemy', x: Math.random()*(W-20), y: -20, w: 20, h: 20, vy: 2 + Math.random()*2 }});
    }} else {{
      entities.push({{ type:'collectible', x: Math.random()*(W-16), y: -16, w: 16, h: 16, vy: 1.5 + Math.random()*1.5 }});
    }}
  }}

  function addParticles(x, y, color, count) {{
    for (let i = 0; i < count; i++) {{
      particles.push({{
        x, y, vx: (Math.random()-0.5)*4, vy: (Math.random()-0.5)*4,
        life: 30 + Math.random()*20, maxLife: 50, color, size: 2+Math.random()*3
      }});
    }}
  }}

  function rectCollide(a, b) {{
    return a.x < b.x+b.w && a.x+a.w > b.x && a.y < b.y+b.h && a.y+a.h > b.y;
  }}

  function update() {{
    if (state !== 'playing') return;

    player.dx = 0; player.dy = 0;
    if (keys['ArrowLeft'] || keys['KeyA']) player.dx = -player.speed;
    if (keys['ArrowRight'] || keys['KeyD']) player.dx = player.speed;
    if (keys['ArrowUp'] || keys['KeyW']) player.dy = -player.speed;
    if (keys['ArrowDown'] || keys['KeyS']) player.dy = player.speed;

    player.x = Math.max(0, Math.min(W - player.w, player.x + player.dx));
    player.y = Math.max(0, Math.min(H - player.h, player.y + player.dy));

    spawnTimer++;
    if (spawnTimer >= 40) {{ spawn(); spawnTimer = 0; }}

    for (let i = entities.length-1; i >= 0; i--) {{
      const e = entities[i];
      e.y += e.vy;

      if (e.y > H + 40) {{ entities.splice(i, 1); continue; }}

      if (rectCollide(player, e)) {{
        if (e.type === 'collectible') {{
          score += 10;
          addParticles(e.x+e.w/2, e.y+e.h/2, COLORS.collectible, 8);
          entities.splice(i, 1);
          updateHUD();
        }} else if (e.type === 'enemy') {{
          lives--;
          addParticles(player.x+player.w/2, player.y+player.h/2, '#ff0000', 15);
          entities.splice(i, 1);
          updateHUD();
          if (lives <= 0) {{
            state = 'gameover';
            showOverlay('Game Over!', 'Final {score_label}: ' + score, 'Play Again');
          }}
        }}
      }}
    }}

    for (let i = particles.length-1; i >= 0; i--) {{
      const p = particles[i];
      p.x += p.vx; p.y += p.vy; p.life--;
      if (p.life <= 0) particles.splice(i, 1);
    }}
  }}

  function draw() {{
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, W, H);

    if (state === 'menu') return;

    ctx.fillStyle = COLORS.player;
    ctx.fillRect(player.x, player.y, player.w, player.h);

    ctx.fillStyle = '#fff';
    ctx.font = '14px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('{theme}', player.x + player.w/2, player.y + player.h/2 + 5);

    entities.forEach(e => {{
      ctx.fillStyle = e.type === 'enemy' ? COLORS.enemy : COLORS.collectible;
      ctx.fillRect(e.x, e.y, e.w, e.h);
      if (e.type === 'enemy') {{
        ctx.fillStyle = '#fff'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText('X', e.x+e.w/2, e.y+e.h/2+3);
      }} else {{
        ctx.fillStyle = '#fff'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText('*', e.x+e.w/2, e.y+e.h/2+4);
      }}
    }});

    particles.forEach(p => {{
      const alpha = p.life / p.maxLife;
      ctx.globalAlpha = alpha;
      ctx.fillStyle = p.color;
      ctx.fillRect(p.x, p.y, p.size, p.size);
    }});
    ctx.globalAlpha = 1;
  }}

  function showOverlay(title, subtitle, btnText) {{
    const ol = document.getElementById('overlay');
    ol.innerHTML = '<h1>' + title + '</h1><p>' + subtitle + '</p>' +
      '<button onclick="window._restart()">' + btnText + '</button>';
    ol.classList.remove('hidden');
  }}

  window._restart = function() {{
    init();
    state = 'playing';
    document.getElementById('overlay').classList.add('hidden');
  }};

  document.getElementById('startBtn').addEventListener('click', window._restart);

  function loop() {{
    update();
    draw();
    requestAnimationFrame(loop);
  }}

  init();
  loop();
}})();
</script>
</body>
</html>'''


def _pick_model() -> str:
    config = load_config()
    if not config.minimax_api_key:
        raise RuntimeError("No LLM API key configured (need MINIMAX_API_KEY)")
    return "MiniMax-M3"


async def _generate_concept(concept_prompt: str) -> dict:
    model = _pick_model()
    resp, _ = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": _CONCEPT_SYSTEM},
            {"role": "user", "content": f"Game concept: {concept_prompt}"},
        ],
        max_tokens=512,
        temperature=0.8,
        agent_name="prototype",
    )
    cleaned = resp.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"LLM returned invalid JSON, using fallback concept. Raw: {cleaned[:200]}")
        return _fallback_concept(concept_prompt)


def _fallback_concept(prompt: str) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:30]
    return {
        "name": slug or "prototype-game",
        "title": slug.replace("-", " ").title() or "Prototype Game",
        "genre": "arcade",
        "description": prompt[:100],
        "player_color": "#00d4ff",
        "enemy_color": "#ff5252",
        "collectible_color": "#ffb300",
        "bg_color": "#1a1a2e",
        "controls": {"move": "arrow keys or WASD", "action": "avoid enemies, collect items"},
        "core_mechanic": "Dodge enemies and collect items for points",
        "score_label": "Score",
        "win_condition": "Survive as long as possible",
        "theme": "\u2b50",
    }


def _build_html(concept: dict) -> str:
    controls = concept.get("controls", {})
    move = controls.get("move", "arrow keys")
    controls_text = f"Move: {move}"

    return _GAME_TEMPLATE.format(
        title=concept.get("title", "Prototype"),
        description=concept.get("description", ""),
        controls_text=controls_text,
        core_mechanic=concept.get("core_mechanic", "Survive and score"),
        score_label=concept.get("score_label", "Score"),
        player_color=concept.get("player_color", "#00d4ff"),
        enemy_color=concept.get("enemy_color", "#ff5252"),
        collectible_color=concept.get("collectible_color", "#ffb300"),
        bg_color=concept.get("bg_color", "#1a1a2e"),
        theme=concept.get("theme", "\u2b50"),
    )


async def run_prototype(concept_prompt: str, project_name: str | None = None) -> dict:
    start = time.time()
    config = load_config()
    config.games_output_dir.mkdir(parents=True, exist_ok=True)

    concept = await _generate_concept(concept_prompt)
    name = project_name or concept.get("name", f"proto-{uuid.uuid4().hex[:8]}")
    name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")

    project_dir = config.games_output_dir / name
    if project_dir.exists():
        stamp = time.strftime("%m%d%H%M")
        project_dir = config.games_output_dir / f"{name}-{stamp}"

    dist_dir = project_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    html = _build_html(concept)
    index_path = dist_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    metadata = {
        "name": name,
        "title": concept.get("title", name),
        "genre": concept.get("genre", "arcade"),
        "type": "prototype",
        "concept_prompt": concept_prompt,
    }
    meta_path = project_dir / "prototype.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    elapsed = time.time() - start
    preview_path = f"/games-preview/{name}/dist/index.html"

    logger.info(f"Prototype '{name}' built in {elapsed:.1f}s at {dist_dir}")

    return {
        "project_name": name,
        "concept": concept,
        "preview_url": preview_path,
        "dist_path": str(dist_dir),
        "metadata_path": str(meta_path),
        "duration_seconds": round(elapsed, 1),
    }
