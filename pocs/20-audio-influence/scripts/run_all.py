#!/usr/bin/env python
"""POC 20 — audio influence. Per song: 1 shared keyframe, 9 LTX variants
(no audio + 4 cfg × 2 audio sources). Gallery with inline <video> players
that play the actual conditioning audio alongside the generated clip."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

import yaml

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir, save_prompts  # noqa: E402

ENV_FILE = REPO_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if "GEMINI_API_KEY" not in os.environ:
    print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
    sys.exit(1)

from google import genai

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
MUSIC_DIR = REPO_ROOT / "music"
STEMS_CACHE = REPO_ROOT / "pocs" / "17-filter-gallery" / "cache"
POC18_OUTPUTS = REPO_ROOT / "pocs" / "18-filter-chooser" / "outputs"
POC7_ALIGNED_FALLBACK = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"

WIDTH = 512
HEIGHT = 320
FPS = 10
NUM_FRAMES = 249  # 1 + 8*31; 24.9 s at 10 fps (user asked for 25 s)
DURATION_S = NUM_FRAMES / FPS  # 24.9 s

# Per-song start times (user-specified)
SONG_WINDOWS = {
    "busy-invisible": 90.0,
    "chronophobia": 50.0,
    "my-little-blackbird": 120.0,
}

CFG_SCALES = [3, 7, 15, 20]
AUDIO_SOURCES = ["full", "drums"]

MOTION_PROMPT = (
    "slow gentle camera settle, subtle ambient motion within the frame, "
    "quiet continuous movement"
)
TECH_NEGATIVE = "blurry, low quality, worst quality, distorted, watermark, subtitle"

DEFAULT_SEED = 42

def mlx_video_base(seed: int) -> list[str]:
    return [
        "uv", "run", "mlx_video.ltx_2.generate",
        "--seed", str(seed),
        "--pipeline", "dev-two-stage",
        "--model-repo", "prince-canuma/LTX-2.3-dev",
        "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
        "--width", str(WIDTH),
        "--height", str(HEIGHT),
        "--num-frames", str(NUM_FRAMES),
        "--fps", str(FPS),
        "--image-strength", "1.0",
        "--image-frame-idx", "0",
        "--negative-prompt", TECH_NEGATIVE,
    ]

PASS_A_PROMPT = """You are a music video director for a song that will be rendered ENTIRELY in the "{filter_word}" style.

Song lyrics:
---
{lyrics}
---

Write a character/world brief (5-8 sentences). Every shot exists WITHIN the {filter_word} style: materials, textures, palette, lighting all follow that style. Describe the narrator, the central metaphor, the setting. Concrete visual cues only. Describe what IS present.

Return ONLY the brief as a single paragraph."""

PASS_B_PROMPT = """You are a music video director generating ONE keyframe image prompt for a specific passage of a song.

World brief (applies to every shot):
---
{brief}
---

Target passage (the actual lyrics sung during this {duration_s:.1f}-second window):
---
{target_passage}
---

Write ONE image-generation prompt (3-4 sentences) for a keyframe that visually captures this passage as a composite moment — the central metaphor, the emotional tone, the imagery the singer is describing. This one keyframe will anchor the entire {duration_s:.1f}s shot (audio conditioning will drive motion on top of it), so the image must feel anchored in what is being sung.

Requirements:
  - Depict the passage's central metaphor or staged moment, not a literal inventory
  - Honour the world brief (same character, same setting, same filter)
  - Describe what IS present; no emotional labels, no negations
  - Concrete visual cues only — materials, textures, lighting, composition

Return ONLY the final image prompt as a single paragraph."""


# --- helpers -----------------------------------------------------------------

def clean_lyrics(raw: str) -> str:
    return "\n".join(
        s for s in (ln.strip() for ln in raw.splitlines())
        if s and not s.startswith("#")
    )


def load_aligned(song_stem: str) -> dict:
    """Read this song's aligned.json from POC 17 cache, falling back to POC 7 for my-little-blackbird."""
    path = STEMS_CACHE / song_stem / "aligned.json"
    if not path.exists() and song_stem == "my-little-blackbird":
        path = POC7_ALIGNED_FALLBACK
    if not path.exists():
        raise RuntimeError(f"aligned.json missing for {song_stem}")
    return json.loads(path.read_text())


def extract_window_passage(aligned: dict, start_s: float, end_s: float) -> str:
    """Return the text of all sung words whose start falls within [start_s, end_s]."""
    words = aligned.get("words", [])
    in_window = [w for w in words if w.get("start") is not None and start_s <= w["start"] <= end_s]
    if not in_window:
        return ""
    # Preserve original word tokens with simple spacing
    return " ".join(w["word"] for w in in_window)


def load_chosen_filters() -> dict[str, str]:
    latest = POC18_OUTPUTS / "latest"
    if not latest.exists():
        raise RuntimeError(f"POC 18 output missing at {latest}. Run POC 18 first.")
    out: dict[str, str] = {}
    for f in latest.iterdir():
        if f.suffix == ".json" and f.stem not in ("prompts", "run_state"):
            data = json.loads(f.read_text())
            chosen = data.get("chosen_filter")
            if chosen:
                out[f.stem] = chosen
    return out


def gemini_image_with_retry(client, contents, max_attempts: int = 3) -> Optional[bytes]:
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
        except Exception as e:
            print(f"  image attempt {attempt}: exception {e}", file=sys.stderr)
            time.sleep(2)
            continue
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            time.sleep(2); continue
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            finish = getattr(candidates[0], "finish_reason", None)
            print(f"  image attempt {attempt}: empty parts (finish={finish})", file=sys.stderr)
            time.sleep(2); continue
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                return p.inline_data.data
        time.sleep(2)
    return None


def fmt_duration(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)} s"
    m = seconds / 60
    if m < 60: return f"{m:.1f} min"
    return f"{m/60:.2f} h"


def extract_audio_slice(src_wav: Path, start_s: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start_s:.3f}", "-t", f"{DURATION_S:.3f}",
         "-i", str(src_wav),
         "-c:a", "pcm_s16le", "-ar", "48000", str(out_path)],
        check=True,
    )


def mux_video_audio(video_path: Path, audio_path: Path, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video_path), "-i", str(audio_path),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         str(out_path)],
        check=True,
    )


# --- HTML --------------------------------------------------------------------

def variant_slug(source: str, cfg: Optional[int]) -> str:
    if source == "none":
        return "no_audio"
    return f"{source}_cfg{cfg:02d}"


def variant_label(source: str, cfg: Optional[int]) -> str:
    if source == "none":
        return "no audio"
    return f"{source} · cfg {cfg}"


def render_comparator_html(run_dir: Path, tasks: list, results: dict,
                           song_stems: list, chosen_filters: dict,
                           start_time: Optional[float], current: Optional[tuple],
                           done_flag: bool, title: str) -> str:
    """Shared layout: LHS scrollable thumbs, RHS comparator stage + play/pause bar.

    User clicks thumbs to add (up to 4) to the stage. All stage clips play
    synchronised via one master timeline. Radio button picks which is unmuted.
    """
    total = len(tasks)
    completed = sum(1 for v in results.values() if v.get("status") == "done")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    elapsed = time.time() - start_time if start_time else 0

    variants = [("none", None)]
    for src in AUDIO_SOURCES:
        for cfg in CFG_SCALES:
            variants.append((src, cfg))

    # Build clip catalogue for JS
    clip_entries = []
    for song in song_stems:
        for src, cfg in variants:
            slug = variant_slug(src, cfg)
            key = f"{song}::{slug}"
            r = results.get(key, {})
            base = f"{song}/{slug}"
            clip_entries.append({
                "song": song,
                "variant": slug,
                "label": variant_label(src, cfg),
                "status": r.get("status", "pending") if not (current and current == (song, slug)) else "running",
                "src": f"{base}/clip_with_audio.mp4",
                "poster": f"{song}/shared/keyframe.png",
                "filter": chosen_filters.get(song, "?"),
            })
    catalogue_json = json.dumps(clip_entries)

    # Per-song section on the LHS
    lhs_sections = []
    for song in song_stems:
        entries = [e for e in clip_entries if e["song"] == song]
        thumbs = []
        for e in entries:
            cls = f"thumb {e['status']}"
            content = ""
            if e["status"] == "done":
                content = (
                    f"<video src='{e['src']}' poster='{e['poster']}' muted preload='none' loop playsinline></video>"
                )
            else:
                content = f"<div class='placeholder'>{escape(e['status'])}</div>"
            thumbs.append(
                f"<button class='{cls}' data-song='{escape(e['song'])}' data-variant='{escape(e['variant'])}' "
                f"data-src='{escape(e['src'])}' data-poster='{escape(e['poster'])}' "
                f"data-label='{escape(e['label'])}' type='button'>"
                f"{content}<span class='label'>{escape(e['label'])}</span></button>"
            )
        lhs_sections.append(
            f"<section><h3>{escape(song)}<span class='filter'>{escape(chosen_filters.get(song,'?'))}</span></h3>"
            f"<div class='thumbs'>{''.join(thumbs)}</div></section>"
        )

    summary_line = (
        f"{completed}/{total} done"
        + (f" · {failed} failed" if failed else "")
        + (f" · {fmt_duration(elapsed)}" if elapsed else "")
    )
    current_html = (
        f"<span class='now'>now: {escape(current[0])}/{escape(current[1])}</span>"
        if current and not done_flag else ""
    )
    refresh = "" if done_flag else '<meta http-equiv="refresh" content="30">'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>{refresh}
<style>
  :root {{ color-scheme: light dark; --bg:#111; --fg:#eee; --panel:#1a1a1a; --accent:#4c9; --muted:#888; }}
  html, body {{ margin:0; height:100%; overflow:hidden; background:var(--bg); color:var(--fg); font-family:-apple-system, sans-serif; }}
  .app {{ display:grid; grid-template-columns: 340px 1fr; height:100vh; }}

  /* LHS */
  .lhs {{ overflow-y:auto; border-right:1px solid #fff2; background:var(--panel); }}
  .lhs .header {{ padding:10px 12px; border-bottom:1px solid #fff2; position:sticky; top:0; background:var(--panel); z-index:1; }}
  .lhs .header h1 {{ margin:0; font-size:14px; font-weight:600; }}
  .lhs .header .meta {{ font-size:11px; color:var(--muted); margin-top:4px; }}
  .lhs section {{ padding:10px 12px 14px; border-bottom:1px solid #fff1; }}
  .lhs section h3 {{ margin:0 0 8px; font-size:13px; display:flex; justify-content:space-between; align-items:baseline; font-weight:500; }}
  .lhs section h3 .filter {{ font-size:11px; color:var(--muted); font-weight:400; }}
  .thumbs {{ display:grid; grid-template-columns: 1fr 1fr; gap:6px; }}
  .thumb {{ background:#000; border:2px solid transparent; border-radius:4px; overflow:hidden; cursor:pointer; padding:0; display:flex; flex-direction:column; text-align:left; }}
  .thumb:hover {{ border-color:#fff4; }}
  .thumb.selected {{ border-color:var(--accent); }}
  .thumb.pending, .thumb.failed, .thumb.running {{ cursor:not-allowed; opacity:.5; }}
  .thumb video, .thumb .placeholder {{ width:100%; aspect-ratio:16/10; display:block; background:#000; object-fit:cover; }}
  .thumb .placeholder {{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:11px; text-transform:uppercase; }}
  .thumb .label {{ font-size:10px; color:var(--fg); padding:4px 6px; background:#0008; }}

  /* RHS */
  .rhs {{ display:grid; grid-template-rows: 1fr 48px; height:100vh; overflow:hidden; }}
  .stage {{ display:grid; padding:8px; gap:8px; overflow:hidden; align-content:stretch; justify-content:stretch; }}
  .stage.count-0 {{ grid-template-columns:1fr; }}
  .stage.count-1 {{ grid-template-columns:1fr; }}
  .stage.count-2 {{ grid-template-columns:1fr 1fr; }}
  .stage.count-3 {{ grid-template-columns:1fr 1fr 1fr; }}
  .stage.count-4 {{ grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; }}
  .stage .empty {{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:14px; border:1px dashed #fff3; border-radius:6px; margin:20px; }}
  .cell {{ position:relative; background:#000; border-radius:6px; overflow:hidden; display:flex; flex-direction:column; }}
  .cell video {{ flex:1; width:100%; height:100%; object-fit:contain; background:#000; min-height:0; }}
  .cell .overlay {{ position:absolute; bottom:0; left:0; right:0; background:linear-gradient(transparent, #000c); padding:6px 10px; display:flex; justify-content:space-between; align-items:center; gap:10px; font-size:12px; }}
  .cell .overlay .title {{ flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .cell .overlay .sound-mark {{ color:var(--accent); margin-left:6px; }}
  .cell .overlay .close {{ background:none; border:none; color:var(--fg); cursor:pointer; font-size:16px; line-height:1; padding:0 4px; }}
  .cell .overlay .close:hover {{ color:#f66; }}

  /* Controls bar */
  .controls {{ height:48px; border-top:1px solid #fff2; display:flex; align-items:center; gap:14px; padding:0 14px; background:var(--panel); font-size:13px; }}
  .controls button.primary {{ background:var(--accent); color:#000; border:none; padding:6px 14px; border-radius:4px; cursor:pointer; font-weight:600; font-size:13px; }}
  .controls button.primary:hover {{ filter:brightness(1.1); }}
  .controls .timeline {{ flex:1; position:relative; height:4px; background:#fff2; border-radius:2px; cursor:pointer; }}
  .controls .timeline .progress {{ position:absolute; left:0; top:0; bottom:0; background:var(--accent); border-radius:2px; width:0%; }}
  .controls .time {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
</style>
</head>
<body>
<div class="app">
  <aside class="lhs">
    <div class="header">
      <h1>{escape(title)}</h1>
      <div class="meta">{escape(summary_line)} {current_html}</div>
      <div class="meta">Click thumbnails to compare (max 4). {'Auto-refresh 30 s.' if not done_flag else ''}</div>
    </div>
    {''.join(lhs_sections)}
  </aside>
  <main class="rhs">
    <div class="stage count-0" id="stage">
      <div class="empty">Click up to 4 clips on the left to compare them side-by-side.</div>
    </div>
    <div class="controls">
      <button class="primary" id="playpause" type="button">▶ Play all</button>
      <div class="timeline" id="timeline"><div class="progress" id="progress"></div></div>
      <span class="time" id="time">0.0 / 0.0 s</span>
    </div>
  </main>
</div>
<script>
const CATALOGUE = {catalogue_json};
const selected = [];
let masterAudio = null;   // single <audio> plays the song's full-mix slice
let currentSong = null;

function ensureMasterAudio(song) {{
  if (currentSong === song && masterAudio) return;
  if (masterAudio) {{ masterAudio.pause(); masterAudio.remove(); }}
  currentSong = song;
  masterAudio = document.createElement('audio');
  masterAudio.src = `${{song}}/shared/full_mix.wav`;
  masterAudio.loop = true;
  masterAudio.preload = 'auto';
  masterAudio.addEventListener('timeupdate', onAudioTick);
  // Extra safety: some browsers fire 'ended' even with loop=true in rare cases.
  masterAudio.addEventListener('ended', () => {{
    masterAudio.currentTime = 0;
    masterAudio.play().catch(()=>{{}});
  }});
  document.body.appendChild(masterAudio);
}}

function onAudioTick() {{
  if (!masterAudio) return;
  const t = masterAudio.currentTime;
  const d = masterAudio.duration || 0;
  document.querySelectorAll('.stage video').forEach(v => {{
    if (Math.abs(v.currentTime - t) > 0.15 && !v.seeking) v.currentTime = t;
    // Restart any video that browser paused (end-of-stream, stall, etc.)
    if (!masterAudio.paused && v.paused) v.play().catch(()=>{{}});
  }});
  document.getElementById('progress').style.width = (d ? (t/d*100) : 0) + '%';
  document.getElementById('time').textContent = t.toFixed(1) + ' / ' + d.toFixed(1) + ' s';
}}

// Safety net: if audio element stops despite loop=true, restart it from 0
// Also restart any paused video when master is playing.
setInterval(() => {{
  if (!masterAudio) return;
  if (!masterAudio.paused) {{
    document.querySelectorAll('.stage video').forEach(v => {{
      if (v.paused) v.play().catch(()=>{{}});
    }});
  }}
}}, 300);

function isSelected(song, variant) {{
  return selected.some(s => s.song === song && s.variant === variant);
}}

function toggle(song, variant) {{
  const i = selected.findIndex(s => s.song === song && s.variant === variant);
  if (i >= 0) {{
    selected.splice(i, 1);
    if (selected.length === 0 && masterAudio) {{ masterAudio.pause(); masterAudio.remove(); masterAudio = null; currentSong = null; }}
  }} else {{
    if (selected.length >= 4) return;
    const c = CATALOGUE.find(c => c.song === song && c.variant === variant);
    if (!c || c.status !== 'done') return;
    selected.push({{...c}});
  }}
  renderStage();
  renderThumbs();
}}

function renderThumbs() {{
  document.querySelectorAll('.thumb').forEach(t => {{
    t.classList.toggle('selected', isSelected(t.dataset.song, t.dataset.variant));
  }});
}}

function renderStage() {{
  const stage = document.getElementById('stage');
  stage.className = `stage count-${{selected.length}}`;
  if (selected.length === 0) {{
    stage.innerHTML = `<div class='empty'>Click up to 4 clips on the left to compare them side-by-side.</div>`;
    masterVideo = null;
    updatePlayButton(false);
    return;
  }}
  // First selected clip plays audio; all others muted (audio is the same per song anyway)
  // Videos are PURELY VISUAL. Audio comes from a single <audio> element playing
  // the song's full-mix slice — same audio regardless of which clip is selected.
  stage.innerHTML = selected.map((s, i) => `
    <div class="cell" data-index="${{i}}">
      <video src="${{s.src}}" poster="${{s.poster}}" muted loop playsinline preload="auto"></video>
      <div class="overlay">
        <span class="title">${{s.song}} / ${{s.label}}</span>
        <button class="close" onclick="toggle('${{s.song}}','${{s.variant}}')" title="remove">✕</button>
      </div>
    </div>
  `).join('');
  ensureMasterAudio(selected[0].song);
  const vids = document.querySelectorAll('.stage video');
  vids.forEach(v => {{
    v.muted = true;
    v.currentTime = masterAudio ? masterAudio.currentTime : 0;
  }});
  updatePlayButton(masterAudio ? !masterAudio.paused : false);
}}

function updatePlayButton(playing) {{
  document.getElementById('playpause').textContent = playing ? '⏸ Pause' : '▶ Play all';
}}

document.getElementById('playpause').onclick = () => {{
  if (!selected.length || !masterAudio) return;
  const vids = document.querySelectorAll('.stage video');
  vids.forEach(v => v.muted = true);  // videos always muted
  if (masterAudio.paused) {{
    vids.forEach(v => v.currentTime = masterAudio.currentTime);
    masterAudio.play();
    vids.forEach(v => v.play());
    updatePlayButton(true);
  }} else {{
    masterAudio.pause();
    vids.forEach(v => v.pause());
    updatePlayButton(false);
  }}
}};

document.getElementById('timeline').onclick = (e) => {{
  if (!masterAudio || !masterAudio.duration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const t = ((e.clientX - rect.left) / rect.width) * masterAudio.duration;
  masterAudio.currentTime = t;
  document.querySelectorAll('.stage video').forEach(v => v.currentTime = t);
}};

// Wire up thumb clicks
document.querySelectorAll('.thumb').forEach(btn => {{
  btn.addEventListener('click', () => toggle(btn.dataset.song, btn.dataset.variant));
}});
</script>
</body></html>
"""


def write_progress(run_dir: Path, tasks: list, results: dict, start_time: float,
                   current: Optional[tuple], done_flag: bool,
                   song_stems: list, chosen_filters: dict):
    html = render_comparator_html(
        run_dir, tasks, results, song_stems, chosen_filters,
        start_time, current, done_flag,
        title="POC 20 — Audio Influence (live)",
    )
    (run_dir / "progress.html").write_text(html)


def write_gallery(run_dir: Path, song_stems: list, chosen_filters: dict, results: dict):
    tasks = [(s, variant_slug(src, cfg), src, cfg) for s in song_stems
             for (src, cfg) in [("none", None)] + [(sr, cf) for sr in AUDIO_SOURCES for cf in CFG_SCALES]]
    html = render_comparator_html(
        run_dir, tasks, results, song_stems, chosen_filters,
        start_time=None, current=None, done_flag=True,
        title="POC 20 — Audio Influence",
    )
    (run_dir / "gallery.html").write_text(html)


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Resume into the existing `outputs/latest` run dir instead of creating a new timestamped one")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help=f"Seed passed to LTX for every clip (default {DEFAULT_SEED})")
    args = ap.parse_args()

    chosen_filters = load_chosen_filters()
    song_stems = [s for s in SONG_WINDOWS.keys() if s in chosen_filters]
    if len(song_stems) != len(SONG_WINDOWS):
        print(f"WARNING: missing POC 18 filters for: {set(SONG_WINDOWS) - set(song_stems)}", file=sys.stderr)
    if not song_stems:
        print("No songs with both a window and a chosen filter.", file=sys.stderr)
        sys.exit(1)

    if args.resume:
        latest = HERE / "outputs" / "latest"
        if not latest.exists():
            print(f"ERROR: --resume given but {latest} does not exist", file=sys.stderr)
            sys.exit(1)
        run_dir = latest.resolve()
        print(f"Resuming run: {run_dir}")
    else:
        run_dir = make_run_dir(__file__)
        print(f"Run dir: {run_dir}")
    print(f"Seed: {args.seed}")
    print(f"Songs: {song_stems}")

    # Build task list
    variants = [("none", None)] + [(src, cfg) for src in AUDIO_SOURCES for cfg in CFG_SCALES]
    tasks = [(song, variant_slug(s, c), s, c) for song in song_stems for (s, c) in variants]
    # Keep only slug in results keys
    results: dict[str, dict] = {}

    start = time.time()
    write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Per-song setup: extract audio slices, generate shared keyframe
    song_info: dict[str, dict] = {}
    for song in song_stems:
        print(f"\n=== Preparing {song} ===")
        shared_dir = run_dir / song / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)

        # Audio slices
        full_wav = MUSIC_DIR / f"{song}.wav"
        drums_wav = STEMS_CACHE / song / "stems" / "htdemucs_6s" / song / "drums.wav"
        if not drums_wav.exists():
            raise RuntimeError(f"Drums stem missing for {song} at {drums_wav}; run POC 17 first.")

        full_slice = shared_dir / "full_mix.wav"
        drums_slice = shared_dir / "drums.wav"
        extract_audio_slice(full_wav, SONG_WINDOWS[song], full_slice)
        extract_audio_slice(drums_wav, SONG_WINDOWS[song], drums_slice)
        print(f"  extracted audio slices ({SONG_WINDOWS[song]:.1f}–{SONG_WINDOWS[song]+DURATION_S:.1f} s)")

        # Extract lyrics sung during the 25s window for Pass B
        aligned = load_aligned(song)
        target_passage = extract_window_passage(aligned, SONG_WINDOWS[song], SONG_WINDOWS[song] + DURATION_S)
        if not target_passage:
            print(f"  WARNING: no sung words in window for {song}; keyframe will be generic", file=sys.stderr)
            target_passage = "(instrumental — no words sung during this window)"
        (shared_dir / "target_passage.txt").write_text(target_passage)
        print(f"  target passage ({len(target_passage.split())} words): {target_passage[:140]}...")

        # Shared keyframe via Gemini (now window-passage-aware, not neutral)
        keyframe_path = shared_dir / "keyframe.png"
        if not keyframe_path.exists():
            lyrics = clean_lyrics((MUSIC_DIR / f"{song}.txt").read_text())
            filter_word = chosen_filters[song]

            pass_a = PASS_A_PROMPT.format(lyrics=lyrics, filter_word=filter_word)
            brief = client.models.generate_content(model=LLM_MODEL, contents=pass_a).text.strip()

            pass_b = PASS_B_PROMPT.format(
                brief=brief,
                target_passage=target_passage,
                duration_s=DURATION_S,
            )
            image_prompt = client.models.generate_content(
                model=LLM_MODEL, contents=pass_b
            ).text.strip().strip('"').strip()

            image_bytes = gemini_image_with_retry(client, [image_prompt])
            if image_bytes is None:
                raise RuntimeError(f"Shared keyframe failed for {song}")
            keyframe_path.write_bytes(image_bytes)
            (shared_dir / "brief.txt").write_text(brief)
            (shared_dir / "image_prompt.txt").write_text(image_prompt)
            print(f"  keyframe saved ({len(image_bytes):,} bytes)")

        song_info[song] = {
            "filter": chosen_filters[song],
            "window_start": SONG_WINDOWS[song],
            "keyframe": keyframe_path,
            "full_slice": full_slice,
            "drums_slice": drums_slice,
            "brief": (shared_dir / "brief.txt").read_text() if (shared_dir / "brief.txt").exists() else "",
            "image_prompt": (shared_dir / "image_prompt.txt").read_text() if (shared_dir / "image_prompt.txt").exists() else "",
            "target_passage": target_passage,
        }

    # Main loop: run 9 variants per song
    for i, (song, slug, source, cfg) in enumerate(tasks):
        key = f"{song}::{slug}"
        out_dir = run_dir / song / slug
        clip_muxed = out_dir / "clip_with_audio.mp4"
        if clip_muxed.exists():
            results[key] = {"status": "done", "cached": True}
            write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        write_progress(run_dir, tasks, results, start, (song, slug), False, song_stems, chosen_filters)
        print(f"\n[{i+1}/{len(tasks)}] {song} × {slug}")

        info = song_info[song]
        ltx_prompt = f"{MOTION_PROMPT}. {info['image_prompt']}"
        clip_path = out_dir / "clip.mp4"

        cmd = mlx_video_base(args.seed) + [
            "--prompt", ltx_prompt,
            "--image", str(info["keyframe"]),
            "--output-path", str(clip_path),
        ]
        audio_slice_path: Optional[Path] = None
        if source == "full":
            audio_slice_path = info["full_slice"]
        elif source == "drums":
            audio_slice_path = info["drums_slice"]
        if audio_slice_path is not None:
            cmd += ["--audio-file", str(audio_slice_path),
                    "--audio-cfg-scale", str(cfg)]

        log_path = out_dir / "ltx.log"
        try:
            t0 = time.time()
            with log_path.open("w") as logf:
                logf.write(f"CMD: {' '.join(cmd)}\n\n")
                res = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
            ltx_s = time.time() - t0
            if res.returncode != 0 or not clip_path.exists():
                raise RuntimeError(f"LTX rc={res.returncode}, see {log_path}")

            # Mux with audio (no audio clip → use silence track)
            if audio_slice_path is not None:
                mux_video_audio(clip_path, audio_slice_path, clip_muxed)
            else:
                # No-audio clip: still produce a .mp4 with silent audio track for consistent playback
                silent_wav = out_dir / "silence.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
                     "-t", f"{DURATION_S:.3f}",
                     "-c:a", "pcm_s16le", str(silent_wav)],
                    check=True,
                )
                mux_video_audio(clip_path, silent_wav, clip_muxed)

            save_prompts(out_dir, {
                "song": song,
                "variant": slug,
                "audio_source": source,
                "audio_cfg_scale": cfg,
                "seed": args.seed,
                "window_start_s": SONG_WINDOWS[song],
                "window_duration_s": DURATION_S,
                "num_frames": NUM_FRAMES,
                "fps": FPS,
                "filter": info["filter"],
                "target_passage": info["target_passage"],
                "world_brief": info["brief"],
                "keyframe_image_prompt": info["image_prompt"],
                "motion_prompt": MOTION_PROMPT,
                "technical_negative": TECH_NEGATIVE,
                "ltx_final_prompt": ltx_prompt,
                "ltx_wall_time_s": round(ltx_s, 2),
                "audio_slice_path": str(audio_slice_path) if audio_slice_path else None,
            })
            results[key] = {"status": "done", "ltx_s": ltx_s}
            print(f"    ✓ done in {fmt_duration(ltx_s)}")
        except Exception as e:
            (out_dir / "error.txt").write_text(f"{e}\n\n{traceback.format_exc()}")
            results[key] = {"status": "failed", "error": str(e)}
            print(f"    ✗ failed: {e}", file=sys.stderr)

        (run_dir / "run_state.json").write_text(json.dumps({
            "tasks": [list(t) for t in tasks], "results": results, "start_time": start,
        }, indent=2, default=str))
        write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)

    write_gallery(run_dir, song_stems, chosen_filters, results)
    write_progress(run_dir, tasks, results, start, None, True, song_stems, chosen_filters)

    elapsed = time.time() - start
    done = sum(1 for v in results.values() if v.get("status") == "done")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    print(f"\n===\nDone: {done}/{len(tasks)}, failed: {failed}, elapsed {fmt_duration(elapsed)}")
    print(f"Gallery: {run_dir / 'gallery.html'}")


if __name__ == "__main__":
    main()
