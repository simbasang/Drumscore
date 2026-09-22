# Transcription Engine Evaluation (Issue #47, V1-014)

## Purpose

This is desk research, not an install-and-benchmark exercise. Per the Epic 3
design doc (`docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md`,
"#47 — Engine evaluation") and the user's 2026-09-21 decision, no candidate
listed here was installed, no model weights were downloaded, and no
`pip`/`uv install` was run against this repository. Every claim below is
sourced from each project's own GitHub repository, PyPI page, or published
paper, fetched live during this session (dated 2026-09-22) rather than
recalled from training data. Sources are cited inline.

The question this doc answers: is there currently a maintained, real,
Python-callable alternative to `DrumScriptTranscriber` (behind the
`DrumTranscriber` protocol in `backend/app/transcription.py`) with enough
published evidence to justify a future integration spike? Per issue #47's
acceptance criteria, "no viable candidate found, documented with evidence" is
an acceptable outcome of this issue, not a failure to deliver it.

## A note on the benchmark number, so it isn't misread

This session also built a synthetic benchmark corpus
(`backend/tests/fixtures/benchmark_corpus.py`) and measured DrumScript's
real corpus-wide F1 at **0.0671** (`backend/tests/test_transcription_benchmark.py`).
That number is not used anywhere below as evidence that DrumScript is
generally poor. The corpus is synthetic sine-wave/noise-burst audio,
generated to exercise timing and matching logic, not the kind of real
multitrack or mixed-kit recordings any of DrumScript's or these candidates'
classifiers were tuned/trained against. A rule-based physics classifier
tuned on real transient spectra can legitimately perform far worse on
synthetic test tones than on the real audio it was designed for, and none of
the candidates below have been run against this corpus either — so it is not
a fair cross-engine comparison point and isn't treated as one here. It's
mentioned only so a future reader doesn't conflate "low score on a synthetic
timing-focused corpus" with "objectively bad transcription engine."

## What's currently integrated

`DrumScriptTranscriber` (`backend/app/drumscript_transcriber.py`) is a thin
subprocess wrapper around the third-party `drumscript` PyPI package. Reading
its installed source (`backend/drumscript_runner/.venv/Lib/site-packages/drumscript/drum_classifier/classify.py`)
confirms it is a **deterministic, rule-based** classifier: onsets are sliced,
physics features are computed (peak frequency, spectral centroid, low/high
frequency energy ratios, decay), and instrument labels are assigned via
hard-coded threshold functions (`classify_membranophone`,
`classify_idiophone`). There is no trained model, no probability, and no
confidence signal anywhere in the classification path — consistent with
`DrumEvent.confidence` staying `None` for every DrumScript-produced event
(see #48).

## Comparison table

| Candidate | License | Maintenance status (as of 2026-09-22) | Instrument coverage | Published accuracy | Integration cost estimate |
|---|---|---|---|---|---|
| **madmom** (`CPJKU/madmom`) | Source: BSD-2-Clause. Pretrained neural models: **CC BY-NC-SA 4.0** — commercial use requires separate written permission from the copyright holder. | Repo not archived, 1,753 commits, last commit to `main` 2024-08-25 (a CI/NumPy-2 compatibility PR). Last **PyPI release is 0.16.1, from 2018-11-14** — `pip install madmom` ships 2018-era code; anything newer requires installing from git. | Onset/beat/tempo detection only. It is **not a drum-instrument classifier** — it has no kick/snare/hi-hat/tom/cymbal output. It is a building block other tools (e.g. ADTLib) sit on top of. | Published onset/beat F-measures exist in the madmom papers, but none apply to per-instrument drum classification since the library doesn't do that task. | Not directly applicable — would only be useful as an onset-detection front end feeding a separately-built classifier, which is out of scope for a like-for-like `DrumTranscriber` swap. The pretrained-model license would also need Gerhard Widmer's written permission before any commercial use. |
| **ADTLib** (`CarlSouthall/ADTLib`) | BSD-2-Clause | **Abandoned.** Last commit and last PyPI release (`2.1.2`) both dated 2018-01-17 — over 8 years stale, no activity since. Depends on `madmom` and an unpinned old `tensorflow`, both of which have moved on substantially since 2018. | Kick, snare, hi-hat onsets only (3 classes) — no toms, no crash/ride, no open/closed hi-hat distinction. Falls well short of `DrumInstrument`'s 9-value taxonomy. | None published in the README; no F-measure numbers found anywhere in the repo. | High and getting worse over time: would require pinning a circa-2018 TensorFlow build (likely GPU/CUDA and Python-version friction against a current environment) for a library that outputs less than half the instrument taxonomy this project needs, with zero given accuracy evidence to justify the effort. |
| **omnizart** (`Music-and-Culture-Technology-Lab/omnizart`) | MIT | **Actively maintained** — last commit 2026-05-31 (a real feature/version-bump commit, `v0.6.3`), 626 commits, requires Python ≥3.8. The most currently-alive project evaluated here. | Toolbox covers multiple transcription tasks (pitched instruments, vocal, chord, beat, **drum**). Per the project's own docs, the drum model currently predicts 13 internal drum-related classes but only 3 are written out to MIDI, and training from scratch is documented by the maintainers as broken ("unknown bugs preventing loss convergence") — usage is checkpoint-inference only. | No F-measure or other accuracy numbers published in the docs or README for the drum-transcription checkpoint specifically; the referenced underlying paper (Wei, Wu, Su, "Improving Automatic Drum Transcription Using Large-Scale Audio-to-MIDI Aligned Data") is cited as "in submission" with no numbers surfaced in omnizart's own docs. | Medium-high: it's a live, MIT-licensed, pip-installable Python package (good protocol fit), but its own maintainers flag the drum model as only partially working (3-of-13 classes actually exposed) and training-from-scratch as broken, with no accuracy evidence for the shipped checkpoint. Would need a hands-on inference spike just to find out what the 3 exposed classes even map to before any real coverage/accuracy claim could be made. |
| **ADTOF** (`MZehren/ADTOF`, dataset + model release) | **CC BY-NC-SA 4.0 — non-commercial only.** | Repo active (pushed 2025-09-18), 100 stars, includes a maintained PyTorch reinterpretation (`ADTOF-pytorch`) reported at "approx. -0.2% F-measure" versus the original. | 5-class drum output (kick, snare, hi-hat, toms-as-one-class, cymbals-as-one-class); a related 2025-09-29 arXiv paper (2509.24853, no confirmed public code as of this research) proposes extending this to 7-8 classes by splitting crash/ride via source separation. | The project's papers report F-measure results on the ADTOF dataset, but the number quoted in the repo's own materials is a *relative* delta between two implementations of itself (-0.2%), not an absolute score comparable to DrumScript's corpus-wide F1. | Blocked before cost is even the question: the CC BY-NC-SA license is non-commercial-only, same category of blocker as madmom's pretrained models. Also ships as Colab/Jupyter-notebook-first, not a clean pip package behind a stable API — would need real integration engineering, not just a licensing waiver, to sit behind `DrumTranscriber`. |

## Also checked, ruled out quickly

- **DrummerScore** (`skittree/DrummerScore`, MIT) — small hobbyist project (51 commits, 31 stars), last pushed 2024-11-12. Shipped as a FastAPI web app plus training notebooks rather than an importable library with a stable inference API, and publishes no accuracy numbers. Not evidence-backed enough to include as a serious candidate.
- **arXiv 2509.24853** ("Enhanced Automatic Drum Transcription via Drum Stem Source Separation," 2025-09-29) — describes combining drum-stem source separation with ADT to go from 5 to 7-8 output classes and estimate MIDI velocity from separated stems. No public code/model repository was found during this research, so it is not currently a usable candidate — noted here as a direction worth re-checking in a future desk-research pass, not evaluated further.

## Recommendation

**No candidate is recommended for a future integration spike at this time.**
This is a "documented as infeasible with evidence" outcome under issue #47's
own acceptance criteria, not a gap in the research:

1. **madmom** doesn't do the task at all (onset/beat only, no instrument
   classification) and its usable pretrained models are non-commercial-only.
2. **ADTLib** does the task but is abandoned (no activity since January
   2018), covers only 3 of the 9 required instrument classes, and publishes
   no accuracy evidence.
3. **omnizart** is the one candidate that is both actively maintained and
   MIT-licensed, but its own maintainers document the drum model as only
   partially exposed (3 of 13 classes) and broken for from-scratch training,
   with no published accuracy numbers for the shipped drum checkpoint. There
   is no evidence here to weigh against DrumScript, only an open question
   that would require a real spike (outside this issue's desk-research scope)
   to even answer.
4. **ADTOF** and its extensions are non-commercial-licensed and shipped as
   research notebooks rather than an integration-ready package.

None of this is evidence that DrumScript is the best possible engine forever
— it's evidence that none of the currently-real alternatives clear the bar
of "maintained, license-compatible, instrument-coverage-complete, and
accuracy-evidenced enough to justify displacing an already-integrated engine
without further work." Per the design doc's #49 strategy selection,
`DrumScriptTranscriber` remains the production `DrumTranscriber` implementation.
If omnizart's drum model is revisited later, the concrete next step would be
a small, separately-scoped integration spike (installing it in an isolated
environment, actually running its drum checkpoint, and recording real
per-instrument metrics against the #45/#46 benchmark corpus) rather than a
further desk-research pass — the open questions here (what do the 3 exposed
classes map to, what's the real accuracy) can only be answered by running it.

## Sources

- https://github.com/CPJKU/madmom (repo metadata, commits, LICENSE)
- https://pypi.org/project/madmom/
- https://github.com/CarlSouthall/ADTLib (README, commits, tags, branches)
- https://pypi.org/project/ADTLib/
- https://github.com/Music-and-Culture-Technology-Lab/omnizart (repo metadata, commits)
- https://music-and-culture-technology-lab.github.io/omnizart-doc/drum/api.html
- https://pypi.org/project/omnizart/
- https://github.com/MZehren/ADTOF (README, repo metadata)
- https://arxiv.org/abs/2509.24853
- https://github.com/skittree/DrummerScore (repo metadata)
