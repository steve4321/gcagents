"""Music generation for game projects."""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config


async def generate_music(state: CompanyState) -> dict:
    """Scheduler entry point: generate BGM + SFX for a game project."""
    gdd = state.gdd
    if not gdd:
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing GDD for music generation"]}

    title = gdd.get("title", "unknown")
    genre = gdd.get("genre", "arcade")
    mood = gdd.get("mood", "upbeat")
    logger.info(f"Music generation for: {title} (genre={genre}, mood={mood})")

    config = load_config()
    games_dir = config.games_output_dir

    code_path = state.game_code_path
    if code_path:
        dist = Path(code_path).parent if Path(code_path).is_file() else Path(code_path)
    else:
        dist = games_dir / title / "dist"

    use_suno = bool(config.suno_api_key)

    try:
        result = await generate_game_audio(
            game_dist_path=dist,
            genre=genre,
            mood=mood,
            use_suno=use_suno,
            suno_api_key=config.suno_api_key or None,
        )
        result["phase"] = PipelinePhase.DEVELOPING
        return result
    except Exception as e:
        logger.warning(f"Music generation failed ({e}), using silent fallback")
        return {"phase": PipelinePhase.DEVELOPING, "music_status": "failed", "error": str(e)}


async def generate_game_audio(
    game_dist_path: str | Path,
    genre: str = "arcade",
    mood: str = "upbeat",
    use_suno: bool = False,
    suno_api_key: str | None = None,
) -> dict:
    """Generate background music and sound effects for a game.

    Args:
        game_dist_path: Path to game's dist/ directory
        genre: Game genre (affects music style)
        mood: Mood (upbeat, calm, tense, epic)
        use_suno: Whether to attempt Suno API
        suno_api_key: Suno API key if available

    Returns:
        dict with: bgm_path, sfx_path, bgm_type, sfx_count, music_status
    """
    dist = Path(game_dist_path)
    audio_dir = dist / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    bgm_type = "procedural_webaudio"
    bgm_path = audio_dir / "bgm.js"

    if use_suno and suno_api_key:
        suno_result = await _try_suno_generation(genre, mood, audio_dir, suno_api_key)
        if suno_result:
            bgm_type = "suno_api"
            bgm_path = suno_result
        else:
            logger.info("Suno generation unavailable, falling back to procedural Web Audio")
            bgm_path.write_text(_generate_bgm_js(genre, mood), encoding="utf-8")
    else:
        bgm_path.write_text(_generate_bgm_js(genre, mood), encoding="utf-8")

    sfx_js = _generate_sfx_js()
    sfx_path = audio_dir / "sfx.js"
    sfx_path.write_text(sfx_js, encoding="utf-8")

    logger.info(f"Generated audio: bgm_type={bgm_type}, sfx_count=5 -> {audio_dir}")

    return {
        "bgm_path": str(bgm_path),
        "sfx_path": str(sfx_path),
        "bgm_type": bgm_type,
        "sfx_count": 5,
        "music_status": "done",
    }


# -- Suno API (optional primary backend) --


async def _try_suno_generation(
    genre: str, mood: str, audio_dir: Path, api_key: str
) -> Path | None:
    """Attempt Suno API generation. Returns bgm path on success, None on failure."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.suno.ai/api/v1/generate",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "prompt": f"Video game background music, {genre} style, {mood} mood, looping, instrumental",
                    "duration": 30,
                    "output": "mp3",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Suno API returned status {resp.status_code}")
                return None

            data = resp.json()
            audio_url = data.get("audio_url") or data.get("url")
            if not audio_url:
                return None

            dl = await client.get(audio_url)
            if dl.status_code == 200:
                bgm_file = audio_dir / "bgm.mp3"
                bgm_file.write_bytes(dl.content)
                return bgm_file
    except ImportError:
        logger.debug("httpx not installed, skipping Suno API")
    except Exception as e:
        logger.warning(f"Suno API call failed: {e}")

    return None


# -- Procedural Web Audio generators --


def _generate_bgm_js(genre: str, mood: str) -> str:
    """Generate a Web Audio procedural BGM JavaScript module."""
    genre_configs = {
        "arcade": {"tempo": 140, "scale": "major", "octave": 4},
        "puzzle": {"tempo": 90, "scale": "pentatonic", "octave": 4},
        "platformer": {"tempo": 130, "scale": "major", "octave": 4},
        "rpg": {"tempo": 80, "scale": "minor", "octave": 3},
        "shooter": {"tempo": 160, "scale": "minor", "octave": 4},
        "idle": {"tempo": 70, "scale": "major", "octave": 3},
    }

    config = genre_configs.get(genre, genre_configs["arcade"])
    notes = _get_scale_freqs(config["scale"], config["octave"])

    vol = 0.12 if mood == "calm" else 0.15
    dur_factor = 0.9 if mood == "tense" else 0.8

    return f"""// Procedural BGM generated for {genre} game ({mood} mood)
(function() {{
  var ctx = new (window.AudioContext || window.webkitAudioContext)();
  var tempo = {config['tempo']};
  var beatDur = 60 / tempo;
  var playing = false;
  var nextNote = 0;

  var notes = {json.dumps(notes)};

  var melody = [0, 2, 4, 5, 4, 2, 0, -1, 3, 5, 7, 5, 3, 0, -1, -1];
  var bass = [0, 0, 3, 3, 4, 4, 5, 5];

  var melodyIdx = 0;
  var bassIdx = 0;

  function playNote(freq, time, duration, type, volume) {{
    if (freq <= 0) return;
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = type || 'square';
    osc.frequency.setValueAtTime(freq, time);
    gain.gain.setValueAtTime(volume || {vol}, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + duration * {dur_factor});
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(time);
    osc.stop(time + duration);
  }}

  function scheduleNotes() {{
    if (!playing) return;
    while (nextNote < ctx.currentTime + 0.5) {{
      var mNote = melody[melodyIdx % melody.length];
      if (mNote >= 0 && mNote < notes.length) {{
        playNote(notes[mNote], nextNote, beatDur * 0.8, 'square', {vol});
      }}
      var bNote = bass[bassIdx % bass.length];
      if (bNote >= 0 && bNote < notes.length) {{
        playNote(notes[bNote] / 2, nextNote, beatDur * 2, 'triangle', 0.1);
      }}
      melodyIdx++;
      bassIdx++;
      nextNote += beatDur;
    }}
    setTimeout(scheduleNotes, 200);
  }}

  window.GameBGM = {{
    start: function() {{
      if (playing) return;
      ctx.resume();
      playing = true;
      nextNote = ctx.currentTime;
      scheduleNotes();
    }},
    stop: function() {{
      playing = false;
    }}
  }};
}})();
"""


def _generate_sfx_js() -> str:
    """Generate Web Audio SFX JavaScript module."""
    return """// Procedural Sound Effects
(function() {
  var ctx = null;

  function getCtx() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    return ctx;
  }

  function playSFX(type) {
    var c = getCtx();
    c.resume();
    var now = c.currentTime;
    switch(type) {
      case 'jump': {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'square';
        osc.frequency.setValueAtTime(300, now);
        osc.frequency.exponentialRampToValueAtTime(600, now + 0.1);
        gain.gain.setValueAtTime(0.2, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
        osc.connect(gain); gain.connect(c.destination);
        osc.start(now); osc.stop(now + 0.15);
        break;
      }
      case 'collect': {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(800, now);
        osc.frequency.exponentialRampToValueAtTime(1200, now + 0.08);
        gain.gain.setValueAtTime(0.2, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
        osc.connect(gain); gain.connect(c.destination);
        osc.start(now); osc.stop(now + 0.12);
        break;
      }
      case 'hit': {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(200, now);
        osc.frequency.exponentialRampToValueAtTime(50, now + 0.2);
        gain.gain.setValueAtTime(0.25, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
        osc.connect(gain); gain.connect(c.destination);
        osc.start(now); osc.stop(now + 0.25);
        break;
      }
      case 'gameover': {
        [400, 350, 300, 200].forEach(function(f, i) {
          var osc = c.createOscillator();
          var gain = c.createGain();
          osc.type = 'square';
          osc.frequency.setValueAtTime(f, now + i * 0.2);
          gain.gain.setValueAtTime(0.15, now + i * 0.2);
          gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.2 + 0.18);
          osc.connect(gain); gain.connect(c.destination);
          osc.start(now + i * 0.2); osc.stop(now + i * 0.2 + 0.2);
        });
        break;
      }
      case 'click': {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(600, now);
        gain.gain.setValueAtTime(0.15, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);
        osc.connect(gain); gain.connect(c.destination);
        osc.start(now); osc.stop(now + 0.05);
        break;
      }
    }
  }

  window.GameSFX = {
    play: playSFX,
    jump: function() { playSFX('jump'); },
    collect: function() { playSFX('collect'); },
    hit: function() { playSFX('hit'); },
    gameover: function() { playSFX('gameover'); },
    click: function() { playSFX('click'); }
  };
})();
"""


def _get_scale_freqs(scale: str, octave: int) -> list[float]:
    """Get frequency list for a musical scale."""
    base = 261.63 * (2 ** (octave - 4))
    scales = {
        "major": [0, 2, 4, 5, 7, 9, 11, 12],
        "minor": [0, 2, 3, 5, 7, 8, 10, 12],
        "pentatonic": [0, 2, 4, 7, 9, 12, 14, 16],
    }
    semitones = scales.get(scale, scales["major"])
    return [round(base * (2 ** (s / 12)), 2) for s in semitones]
