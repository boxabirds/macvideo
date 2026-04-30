# POC 31 — RESULT (three-song re-run)

**Status:** MARGINAL — Gemini beats WhisperX by 2.6 pp on average
across three songs, BELOW the pre-registered ≥3 pp PASS threshold.
On one of the three songs (busy-invisible) the two are tied. Verdict:
Gemini is a defensible default but not a clear winner.

**Date run:** 2026-04-25 (initial single-song run + corrected
three-song re-run after fixing two script bugs and one
section-marker regex bug).

## Headline

Variant W = WhisperX large-v3, no `initial_prompt`, htdemucs_6s
vocals stem (POC 30 recipe).
Variant G = Gemini 2.5 Pro, native audio input, same vocals stem.
Both compared against `music/${slug}.txt` ground truth.

| Song | GT words | Gemini accuracy | WhisperX accuracy | Lift (pp) | Gemini wall |
|---|---|---|---|---|---|
| my-little-blackbird | 232 | **89.2%** (WER 10.8%) | 87.5% (WER 12.5%) | +1.7 | 17 s |
| busy-invisible | 224 | **87.1%** (WER 12.9%) | 87.1% (WER 12.9%) | 0 | 13 s |
| chronophobia | 217 | **88.5%** (WER 11.5%) | 82.5% (WER 17.5%) | +6.0 | 15 s |
| **average** | — | **88.3%** | **85.7%** | **+2.6** | 15 s |

WhisperX wall time per song: ~36–37 s.

## Three bugs fixed during this POC (worth recording)

1. **Cross-song baseline confusion.** First version of `run.sh`
   hardcoded `pocs/30-whisper-timestamped/outputs/whisperx-noprompt.json`
   as the WhisperX baseline. POC 30 only ran on `my-little-blackbird`,
   so when POC 31 ran on `busy-invisible` and `chronophobia`, the
   WhisperX comparison was against a different song's transcript.
   Symptom: WER reported as 98.7% and 101.3% (>100% is the giveaway —
   it means insertions exceed reference length). Fix: `run.sh` now
   runs WhisperX per song into `outputs/${slug}/whisperx-noprompt.json`.

2. **Output overwrite across songs.** All three Gemini runs wrote to
   the same `outputs/gemini.json`. Only the last song's output
   survived on disk. Fix: per-song subdirectories
   (`outputs/${slug}/`).

3. **Section-marker regex too strict (in POC 30's `compare.py`).**
   The `SECTION_MARKER_RE` required `*[Verse 1]*` (markdown bold
   asterisks). `my-little-blackbird.txt` uses that style; the two
   newer GT files use plain `[Verse 1]` without asterisks. So plain
   markers were tokenised as words ('verse', '1', 'chorus', 'bridge'…)
   and counted in ground truth. This added 6 spurious words to
   chronophobia's GT and 11 to busy-invisible's, deflating BOTH
   models' scores on those songs. Fix: regex now matches
   `r"^\**\[[^\]]*\]\**\s*$"`. Pre-fix vs post-fix on the same JSONs:

   | Song | Gemini pre-fix | Gemini post-fix | WhisperX pre-fix | WhisperX post-fix |
   |---|---|---|---|---|
   | busy-invisible | 83.0% | 87.1% | 83.0% | 87.1% |
   | chronophobia | 86.1% | 88.5% | 80.3% | 82.5% |

## Where Gemini consistently wins (and where it doesn't)

- **chronophobia (+6 pp):** the largest lift. WhisperX produces
  multiple insertion-style errors here (14 insertions vs Gemini's 12)
  on what reads as denser, faster delivery. Gemini's reasoning seems
  to anchor it better on harder vocals.
- **my-little-blackbird (+1.7 pp):** small lift. The single most
  important Gemini correction (`why won't` vs WhisperX's `i want`) is
  still there. The smaller lift here vs the original single-song run
  (+3.9 pp) is because Gemini transcripts are non-deterministic — see
  next section.
- **busy-invisible (0 pp):** they tie at 87.1%. Gemini's reasoning
  doesn't help on this one. Both models drop ~28 words via deletion
  on similar segments. Likely a shared VAD / energy-threshold
  failure on quieter passages, not an STT failure per se.

## NEW FINDING — Gemini transcripts are non-deterministic

The first POC run got 91.4% on my-little-blackbird (WER 8.6%, 18
substitutions). The re-run got 89.2% (WER 10.8%, 22 substitutions)
on the same vocals stem with the same prompt. **2.2 pp variance on
identical input.**

This means single-fixture POC numbers from Gemini are noisier than
WhisperX's (which is deterministic at fixed temperature). Implications:

- Reported per-song Gemini numbers in this RESULT have ~±1 pp noise
  floor. The 0 pp tie on busy-invisible could be ±1 pp either way.
- Future Gemini POCs should average over N≥3 runs per fixture before
  declaring a result, or set `temperature=0` if the API exposes it
  for audio-input requests (it does for text — verify for audio).
- For production: variance across user re-renders may be visible.
  An "if you regenerate, you might get a slightly different
  transcript" disclosure may be needed in the editor UI.

## What carries over from the single-song RESULT

- **Reasoning-substitution error class is real.** Gemini still
  occasionally swaps rare correct words for frequent plausible ones
  (`gravid → laden` from the original run). This motivated story 15
  (transcript corrections in the editor).
- **Cost remains trivial.** ~$0.03 per ~4-min song at gemini-2.5-pro
  list rates.
- **Wall time still beats WhisperX** on the Mac (15 s vs 37 s per
  song, plus 6–7 s upload).
- **Privacy posture change** is unchanged: audio leaves the machine.
  Already accepted for the editor's filter chain (also Gemini), so
  no NEW dependency.

## What this DOES NOT show

- **Pass 2 (wav2vec2 alignment) timing precision** is not measured
  here. Gemini returns no word timestamps; the two-pass plan
  (Gemini → wav2vec2 force-align) hasn't been validated on real
  Gemini output. Should be a follow-up POC before story 14 commits.
- **Latency under load.** Three sequential single-song calls. No
  concurrency, no rate-limit behaviour, no retry/error analysis.
- **Flash tier not tested.** `gemini-2.5-flash` may give similar
  accuracy at much lower cost. Worth a probe before any production
  rollout.
- **Three songs, not a benchmark.** All three are the same writer's
  catalogue. A fourth song from a different artist/genre would
  meaningfully strengthen the conclusion. The numbers are a signal,
  not a SLA.

## Decisions back to story 14

1. **Use Gemini 2.5 Pro as the default Pass 1**, gated on
   `GEMINI_API_KEY` being present. WhisperX large-v3 stays as the
   local fallback when no key is set or the user opts out. Gemini
   wins on average by 2.6 pp and significantly on the hardest of
   the three songs (chronophobia). On the easiest two it's a wash.
2. **88.3% average accuracy is shippable IF and ONLY IF story 15
   (transcript corrections) ships alongside or shortly after.** A
   12% per-word error rate translates to ~1 wrong word every 8.
   Without a fast inline-correction loop, downstream stages
   (storyboard, scene prompts, keyframes) inherit wrong words for
   the user to find post-render.
3. **Add Gemini non-determinism to the user-visible mental model.**
   The editor should not promise "your transcript will be exactly
   this" — re-running may produce small differences.
4. **Drop the original RESULT.md's single-fixture conclusion.** The
   91.4% headline was an overestimate driven by both run-to-run
   variance and the easy-fixture artifact. The honest number is
   88.3% averaged over three songs.
5. **Re-measure if a fourth ground-truth song becomes available.**
   The current trio is from one writer's catalogue — confounds
   genre, vocal style, and recording approach.

## What got written

```
pocs/31-gemini-transcribe/
├── README.md
├── RESULT.md (this file)
├── outputs/
│   ├── my-little-blackbird/
│   │   ├── gemini.json + gemini.txt
│   │   ├── whisperx-noprompt.json + whisperx-noprompt.txt
│   │   ├── comparison.md
│   │   ├── stdout-{gemini,whisperx}.log
│   │   └── time-{gemini,whisperx}.txt
│   ├── busy-invisible/   (same shape)
│   └── chronophobia/     (same shape)
└── scripts/
    ├── transcribe_gemini.py
    └── run.sh
```

Patched (also recorded here for the audit trail):
- `pocs/30-whisper-timestamped/scripts/compare.py` —
  `SECTION_MARKER_RE` widened to handle both `**[X]**` and `[X]`.
