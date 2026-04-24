"""Shared audio feature extraction for POCs 22, 23, 24.

All features keyed to seconds in the original audio timeline. Given a full-mix
wav and optionally a drums stem, returns a dict suitable for JSON serialisation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import librosa
import numpy as np


def extract(
    full_mix_path: Path,
    drums_path: Optional[Path] = None,
    sr: int = 22050,
    section_count: int = 8,
    beat_confidence_window_s: float = 0.3,
) -> dict:
    """Run librosa over the song and produce a feature dict.

    Beat tracking runs on the DRUMS stem when available (cleaner signal for
    percussion-defined beats; doesn't get confused by atmospheric / tonal
    content). Falls back to the full mix if no drums stem.

    `beats_s_confident` is the subset of the primary beat grid where at least
    one drum onset lies within ±`beat_confidence_window_s`. Those are the
    beats you can trust — beats in drum-sparse regions (ambient intros, quiet
    bridges) will be excluded.
    """
    y_full, sr = librosa.load(str(full_mix_path), sr=sr, mono=True)
    duration = len(y_full) / sr

    y_drums = None
    if drums_path is not None and drums_path.exists():
        y_drums, _ = librosa.load(str(drums_path), sr=sr, mono=True)

    # Primary beat track: drums stem if available, else full mix
    if y_drums is not None:
        tempo, beat_frames = librosa.beat.beat_track(y=y_drums, sr=sr)
        beat_source = "drums_stem"
    else:
        tempo, beat_frames = librosa.beat.beat_track(y=y_full, sr=sr)
        beat_source = "full_mix"
    tempo = float(np.ravel(tempo)[0]) if np.ndim(tempo) else float(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Also run on full mix for comparison / diagnostic
    tempo_full, beat_frames_full = librosa.beat.beat_track(y=y_full, sr=sr)
    tempo_full = float(np.ravel(tempo_full)[0]) if np.ndim(tempo_full) else float(tempo_full)
    beat_times_full = librosa.frames_to_time(beat_frames_full, sr=sr)

    # Onset strength curve (spectral novelty)
    onset_env = librosa.onset.onset_strength(y=y_full, sr=sr)
    onset_env_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr)

    # Full-mix onsets
    full_onsets = librosa.onset.onset_detect(y=y_full, sr=sr, units="time")

    # RMS envelope
    rms = librosa.feature.rms(y=y_full)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    # Section boundaries via chroma + agglomerative clustering
    section_bound_times: list[float] = []
    try:
        chroma = librosa.feature.chroma_cqt(y=y_full, sr=sr)
        if len(beat_frames) > section_count:
            chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
            bounds = librosa.segment.agglomerative(chroma_sync, k=section_count)
            # bounds are beat indices into chroma_sync; convert to time via beat_times
            section_bound_times = [
                float(beat_times[min(b, len(beat_times) - 1)]) for b in bounds
            ]
            # Ensure monotonic + deduped
            section_bound_times = sorted(set(round(t, 3) for t in section_bound_times))
    except Exception as e:  # noqa: BLE001
        print(f"[audio_features] section segmentation failed: {e}")

    out = {
        "duration_s": round(duration, 3),
        "tempo_bpm": tempo,
        "tempo_bpm_full_mix": tempo_full,
        "beat_source": beat_source,
        "sr": sr,
        "beats_s": [round(float(t), 3) for t in beat_times],
        "beats_s_full_mix": [round(float(t), 3) for t in beat_times_full],
        "onsets_full_s": [round(float(t), 3) for t in full_onsets],
        "onset_strength": [round(float(v), 3) for v in onset_env],
        "onset_strength_times_s": [round(float(t), 3) for t in onset_env_times],
        "rms": [round(float(v), 4) for v in rms],
        "rms_times_s": [round(float(t), 3) for t in rms_times],
        "section_boundaries_s": section_bound_times,
    }

    if y_drums is not None:
        drum_env = librosa.onset.onset_strength(y=y_drums, sr=sr)
        drum_env_times = librosa.frames_to_time(np.arange(len(drum_env)), sr=sr)
        drum_onsets = librosa.onset.onset_detect(y=y_drums, sr=sr, units="time")
        drum_onset_strengths = []
        for t in drum_onsets:
            idx = int(round(t * sr / 512))
            idx = max(0, min(idx, len(drum_env) - 1))
            drum_onset_strengths.append(float(drum_env[idx]))
        out["drum_strength"] = [round(float(v), 3) for v in drum_env]
        out["drum_strength_times_s"] = [round(float(t), 3) for t in drum_env_times]
        out["drum_onsets_s"] = [round(float(t), 3) for t in drum_onsets]
        out["drum_onset_strengths"] = [round(float(v), 3) for v in drum_onset_strengths]

        # Confident beats: those with at least one drum onset within ±window
        drum_arr = np.array(drum_onsets)
        confident = []
        for bt in beat_times:
            if len(drum_arr) and (np.abs(drum_arr - bt) <= beat_confidence_window_s).any():
                confident.append(float(bt))
        out["beats_s_confident"] = [round(t, 3) for t in confident]
        out["beat_confidence_window_s"] = beat_confidence_window_s
        out["beat_confidence_rate"] = round(
            len(confident) / max(len(beat_times), 1), 3
        )

    return out


def strong_drum_onsets(features: dict, percentile: float = 75.0) -> list[float]:
    """Return drum-onset timestamps whose strength is at/above the given percentile."""
    times = features.get("drum_onsets_s", [])
    strengths = features.get("drum_onset_strengths", [])
    if not times or not strengths:
        return []
    threshold = float(np.percentile(strengths, percentile))
    return [t for t, s in zip(times, strengths) if s >= threshold]


def snap_to_nearest_event(t: float, events: list[float], tolerance_s: float) -> tuple[float, bool]:
    """Snap `t` to the closest event in `events` if within `tolerance_s`.

    Returns (new_t, snapped_bool). If no event within tolerance, returns (t, False).
    """
    if not events:
        return t, False
    nearest = min(events, key=lambda e: abs(e - t))
    if abs(nearest - t) <= tolerance_s:
        return float(nearest), True
    return t, False
