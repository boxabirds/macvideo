"""Shared helpers for POC scripts.

Two things every POC should do:
  1. Put each run's outputs in a timestamped subfolder so reruns don't clobber
     prior results.
  2. Save a single `prompts.json` per run capturing every prompt (user prompts,
     LLM-expanded prompts, image-gen prompts, video-gen prompts, negative
     prompts, style bases). Makes runs reproducible and auditable without
     digging through stdout logs.

Usage (Python scripts):

    from pocs._lib.poc_helpers import make_run_dir, save_prompts
    run_dir = make_run_dir(__file__)
    # ... write outputs into run_dir ...
    save_prompts(run_dir, {
        "subject": "...",
        "llm_expansions": {...},
        "image_prompts": {...},
        "video_prompts": {...},
        "negative_prompts": [...],
    })

Usage (shell scripts):

    # See pocs/_lib/poc_helpers.sh — sourceable, exports RUN_DIR and TS
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def poc_root_from(script_path: str | Path) -> Path:
    """Given a script path inside pocs/NN-name/scripts/, return pocs/NN-name/."""
    p = Path(script_path).resolve()
    for cand in [p, *p.parents]:
        if cand.parent.name == "pocs":
            return cand
    raise RuntimeError(f"Could not find POC root from {script_path}")


def make_run_dir(script_path: str | Path, tag: str | None = None) -> Path:
    """Create a timestamped output directory under <poc-root>/outputs/.

    Updates <poc-root>/outputs/latest as a symlink to the new dir for
    convenience (`open outputs/latest/...`).

    Returns the new directory path.
    """
    poc = poc_root_from(script_path)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{ts}-{tag}" if tag else ts
    run = poc / "outputs" / name
    run.mkdir(parents=True, exist_ok=True)

    latest = poc / "outputs" / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(name)
    except OSError:
        pass

    return run


def save_prompts(run_dir: str | Path, prompts: dict) -> Path:
    """Write `prompts.json` with full prompt provenance.

    The dict is free-form; conventional top-level keys:
      - subject           (str)   the human-authored scene
      - style_base        (str)   the style applied to everything
      - filters           (list)  style filter words in play
      - llm_input_prompts (dict)  prompts sent TO the LLM, keyed by purpose
      - llm_expansions    (dict)  the LLM's outputs, keyed the same way
      - image_prompts     (dict)  final prompts sent to the image model
      - video_prompts     (dict)  final prompts sent to the video model
      - negative_prompts  (dict)  applied negatives
      - notes             (str)   anything else worth preserving
    """
    run_dir = Path(run_dir)
    out = run_dir / "prompts.json"
    out.write_text(json.dumps(prompts, indent=2, default=str))
    return out
