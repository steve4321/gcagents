"""Mood-based BGM mapping and procedural Web Audio generation for Visual Novel.

Maps 7 VN moods to procedural Web Audio configurations and emits a
``bgm_<mood>.js`` file that the game can load. Tracks are designed to
loop indefinitely with low CPU cost.

The 7 moods cover the full emotional range of a VN:
* neutral — calm, default
* tense   — low strings, anxiety
* romantic — warm melody
* sad     — slow minor
* happy   — uplifting
* mystery — ambient pad
* action  — driving beat
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


MOODS: tuple[str, ...] = (
    "neutral", "tense", "romantic", "sad", "happy", "mystery", "action",
)


MOOD_BGM_CONFIG: dict[str, dict] = {
    "neutral":  {"tempo": 70,  "scale": "major",      "octave": 4, "waveform": "sine",     "volume": 0.10},
    "tense":    {"tempo": 60,  "scale": "minor",      "octave": 3, "waveform": "sawtooth", "volume": 0.08},
    "romantic": {"tempo": 75,  "scale": "major",      "octave": 5, "waveform": "triangle", "volume": 0.12},
    "sad":      {"tempo": 50,  "scale": "minor",      "octave": 4, "waveform": "sine",     "volume": 0.10},
    "happy":    {"tempo": 110, "scale": "major",      "octave": 4, "waveform": "square",   "volume": 0.12},
    "mystery":  {"tempo": 55,  "scale": "pentatonic", "octave": 4, "waveform": "sine",     "volume": 0.09},
    "action":   {"tempo": 140, "scale": "minor",      "octave": 4, "waveform": "square",   "volume": 0.13},
}


SCALE_NOTES: dict[str, list[int]] = {
    "major":      [0, 2, 4, 5, 7, 9, 11, 12],
    "minor":      [0, 2, 3, 5, 7, 8, 10, 12],
    "pentatonic": [0, 3, 5, 7, 10, 12],
}


def _note_frequencies(scale: str, octave: int) -> list[float]:
    """Return frequencies (Hz) for the given scale at the given octave."""
    base_freq = 261.63 * (2 ** (octave - 4))
    return [round(base_freq * (2 ** (semitone / 12.0)), 2) for semitone in SCALE_NOTES[scale]]


def get_mood_config(mood: str) -> dict:
    if mood not in MOOD_BGM_CONFIG:
        raise ValueError(f"unknown mood {mood!r}; valid: {MOODS}")
    return MOOD_BGM_CONFIG[mood]


def generate_bgm_js(mood: str) -> str:
    """Generate a ``bgm_<mood>.js`` file content (Web Audio procedural)."""
    config = get_mood_config(mood)
    notes = _note_frequencies(config["scale"], config["octave"])
    tempo = config["tempo"]
    waveform = config["waveform"]
    volume = config["volume"]

    return f"""// Procedural BGM — mood: {mood} (tempo={tempo} {config['scale']} @ oct {config['octave']})
(function() {{
  var ctx = new (window.AudioContext || window.webkitAudioContext)();
  var tempo = {tempo};
  var beatDur = 60 / tempo;
  var playing = false;
  var nextNote = 0;
  var notes = {json.dumps(notes)};
  var waveform = {json.dumps(waveform)};
  var volume = {volume};

  var melody = [0, 2, 4, 5, 4, 2, 0, -1, 3, 5, 7, 5, 3, 0, -1, -1];
  var bass = [0, 0, 3, 3, 4, 4, 5, 5];
  var melodyIdx = 0, bassIdx = 0;

  function playNote(freq, time, duration, type, vol) {{
    if (freq <= 0) return;
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, time);
    gain.gain.setValueAtTime(vol, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(time);
    osc.stop(time + duration);
  }}

  function scheduleNotes() {{
    if (!playing) return;
    while (nextNote < ctx.currentTime + 0.5) {{
      var m = melody[melodyIdx % melody.length];
      if (m >= 0 && m < notes.length) playNote(notes[m], nextNote, beatDur * 0.8, waveform, volume);
      var b = bass[bassIdx % bass.length];
      if (b >= 0 && b < notes.length) playNote(notes[b] / 2, nextNote, beatDur * 2, 'triangle', volume * 0.5);
      melodyIdx++; bassIdx++;
      nextNote += beatDur;
    }}
    setTimeout(scheduleNotes, 200);
  }}

  window.GameBGM_{mood.upper()} = {{
    start: function() {{
      if (playing) return;
      ctx.resume();
      playing = true;
      nextNote = ctx.currentTime;
      scheduleNotes();
    }},
    stop: function() {{ playing = false; }}
  }};
}})();
"""


def write_all_bgm_tracks(audio_dir: Path) -> dict[str, Path]:
    """Write one ``bgm_<mood>.js`` per mood into ``audio_dir``.

    Returns a mapping of mood → file path. Skips existing files (no overwrite).
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for mood in MOODS:
        target = audio_dir / f"bgm_{mood}.js"
        if target.exists():
            written[mood] = target
            continue
        try:
            target.write_text(generate_bgm_js(mood), encoding="utf-8")
            written[mood] = target
        except OSError as e:
            logger.warning(f"failed to write bgm for {mood}: {e}")
    return written


def mood_to_filename(mood: str) -> str:
    if mood not in MOOD_BGM_CONFIG:
        raise ValueError(f"unknown mood {mood!r}")
    return f"bgm_{mood}.js"
