"""Real pipeline integration for the storyboard editor.

Replaces the story-9/5/10 stub handlers with subprocess wrappers around the
POC 29 scripts (gen_keyframes.py, render_clips.py) + ffmpeg. Each handler:

1. Resolves a per-song outputs directory (config.OUTPUTS_DIR / slug).
2. Invokes the appropriate subprocess with a controlled argv + env.
3. Streams stdout through a progress parser so the editor can update the DB
   as each scene / stage completes.
4. Re-imports the resulting files as new `takes` rows.

Tests substitute the script path with a lightweight fake under
editor/server/tests/fake_scripts/ so no Gemini / LTX API calls fire.
"""

from __future__ import annotations
