"""Procedural Web Audio SFX generator for Visual Novel.

Emits a single ``sfx.js`` file with 5 VN-specific sound effects:
* choice_select   — short blip on choice click
* transition_whoosh — scene change
* heartbeat      — pre-choice tension
* route_unlock   — fanfare on route unlock
* ending_reveal  — stinger on ending reveal

All SFX are pure Web Audio (no asset files), making them free and
instantly available.
"""

from __future__ import annotations

from pathlib import Path


SFX_CATEGORIES: tuple[str, ...] = (
    "choice_select", "transition_whoosh", "heartbeat", "route_unlock", "ending_reveal",
)


SFX_DEFINITIONS: dict[str, str] = {
    "choice_select": """
      var o = c.createOscillator();
      var g = c.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(800, now);
      o.frequency.exponentialRampToValueAtTime(1200, now + 0.05);
      g.gain.setValueAtTime(0.18, now);
      g.gain.exponentialRampToValueAtTime(0.001, now + 0.08);
      o.connect(g); g.connect(c.destination);
      o.start(now); o.stop(now + 0.1);
    """,
    "transition_whoosh": """
      var buf = c.createBuffer(1, c.sampleRate * 0.3, c.sampleRate);
      var data = buf.getChannelData(0);
      for (var i = 0; i < data.length; i++) {
        var t = i / data.length;
        data[i] = (Math.random() * 2 - 1) * (1 - t) * 0.4;
      }
      var src = c.createBufferSource();
      src.buffer = buf;
      var filter = c.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(2000, now);
      filter.frequency.exponentialRampToValueAtTime(200, now + 0.3);
      var g = c.createGain();
      g.gain.setValueAtTime(0.2, now);
      g.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      src.connect(filter); filter.connect(g); g.connect(c.destination);
      src.start(now);
    """,
    "heartbeat": """
      for (var beat = 0; beat < 2; beat++) {
        var o = c.createOscillator();
        var g = c.createGain();
        var t0 = now + beat * 0.18;
        o.type = 'sine';
        o.frequency.setValueAtTime(60, t0);
        o.frequency.exponentialRampToValueAtTime(40, t0 + 0.1);
        g.gain.setValueAtTime(0.25, t0);
        g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.12);
        o.connect(g); g.connect(c.destination);
        o.start(t0); o.stop(t0 + 0.15);
      }
    """,
    "route_unlock": """
      [523, 659, 784, 1047].forEach(function(f, i) {
        var o = c.createOscillator();
        var g = c.createGain();
        var t0 = now + i * 0.12;
        o.type = 'triangle';
        o.frequency.setValueAtTime(f, t0);
        g.gain.setValueAtTime(0.18, t0);
        g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.3);
        o.connect(g); g.connect(c.destination);
        o.start(t0); o.stop(t0 + 0.35);
      });
    """,
    "ending_reveal": """
      [392, 440, 494, 587, 392].forEach(function(f, i) {
        var o = c.createOscillator();
        var g = c.createGain();
        var t0 = now + i * 0.25;
        o.type = 'sine';
        o.frequency.setValueAtTime(f, t0);
        g.gain.setValueAtTime(0.15, t0);
        g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.5);
        o.connect(g); g.connect(c.destination);
        o.start(t0); o.stop(t0 + 0.55);
      });
    """,
}


def generate_sfx_js() -> str:
    """Generate the ``sfx.js`` file content with all 5 SFX categories."""
    body_cases: list[str] = []
    for category in SFX_CATEGORIES:
        body = SFX_DEFINITIONS[category].strip()
        body_cases.append(
            f"      case {category!r}: {{\n{body}\n        break;\n      }}"
        )
    cases_str = "\n".join(body_cases)

    return f"""// Procedural VN SFX (5 categories)
(function() {{
  var ctx = null;
  function getCtx() {{
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    return ctx;
  }}
  function play(category) {{
    var c = getCtx();
    c.resume();
    var now = c.currentTime;
    switch (category) {{
{cases_str}
      default:
        console.warn('Unknown SFX category:', category);
    }}
  }}
  window.GameSFX = {{ play: play, categories: {list(SFX_CATEGORIES)!r} }};
}})();
"""


def write_sfx_js(audio_dir: Path) -> Path | None:
    """Write the consolidated ``sfx.js`` file into ``audio_dir``.

    Returns the file path, or None if writing failed.
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    target = audio_dir / "sfx.js"
    try:
        target.write_text(generate_sfx_js(), encoding="utf-8")
        return target
    except OSError:
        return None
