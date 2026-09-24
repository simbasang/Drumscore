# Claude instructions — Drumscore v1.0

Before changing code, read the GitHub issue you were asked to implement, PROJECT.md, docs/ARCHITECTURE_V1.md and the **index** at the top of TECHNICAL_DEBT.md (not the whole file — open only the entries for areas you touch). The issue is the immediate scope; the project and architecture documents define constraints. Read each of these once per session; subagents get the relevant excerpts in their prompt instead of re-reading them.

## Token budget
Keep token use low; this repo's sessions have been very expensive.

- **Plans** (overrides superpowers:writing-plans' "complete code in every step"): per task state goal, files, interfaces/signatures, test names with the key assertion, and any non-obvious detail. No full implementation code; full test/code bodies only for genuinely tricky logic. Aim for under ~15 KB per plan.
- **Execution:** inline by default. Use subagent-driven development only for plans with many (roughly 6+) independent tasks. Then: implementers on `model: "sonnet"`, one combined spec+quality review per task, and keep the final whole-branch review (it has caught real bugs). Dispatch prompts carry the task text and file paths, not "read the plan/docs".
- **Tests:** run quietly and targeted while iterating; the full suites only before commit/PR.
  - Backend: `uv run pytest -q --tb=short` (add a path or `-k` while iterating).
  - Frontend: `npx jest <path> --silent --reporters=summary` (path first; drop it for the full suite).
- **Reading:** use Grep and `offset`/`limit` for large files; don't re-read files already in context. `.rgignore` hides `docs/superpowers/plans/` and `.superpowers/` from searches; read only the current plan/ledger, by exact path.

## Working method
Work one implementation issue at a time unless explicitly instructed otherwise.

For every bug or behavioral defect:
1. reproduce it
2. add targeted instrumentation if the cause is not proven
3. identify/document the root cause
4. add a regression test where practical
5. implement the smallest root-cause fix
6. run relevant checks
7. verify the original reproduction

Do not patch symptoms. Never smooth/debounce a jumping playhead merely to hide incorrect timing data.

For every issue: inspect current code first; state a short plan; keep changes scoped; preserve contracts unless the issue changes them; add/update tests; run relevant frontend/backend checks; report changes/tests/limitations; then stop unless explicitly told to continue.

## Critical timing model
Source audio time is authoritative. Every event keeps an immutable original source timestamp.

Keep sourceTime, musicalPosition and renderedPosition separate. Quantization assigns musical position but never overwrites source time. Audio playback time comes from the Web Audio transport. requestAnimationFrame refreshes visuals only.

A scalar BPM is not sufficient for v1.0. Timing must support a tempo map plus phase/downbeat alignment.

## Architecture boundaries
Keep media acquisition, normalization, stem separation, transcription, timing analysis, quantization, editable score model, engraving, playback/mixing, persistence/jobs and UI independent. Third-party outputs never become frontend/domain contracts. DrumScript, Demucs, librosa, VexFlow and yt-dlp are implementation details.

## Transcription
Do not claim quality improvements from one visual example. Use labelled/controlled fixtures and per-instrument metrics. Preserve raw engine output for diagnostics where useful. Never fabricate confidence values.

## Notation
Mandatory: five-line percussion staff; all stems upward; simultaneous hits aligned/grouped; clear open/closed hi-hat; musical note/rest durations instead of every hit as a sixteenth; layout adapts to musical density. Do not regress the existing explicit upward-stem implementation.

## Player
Web Audio remains authoritative. Stems stay synchronized through play, pause, seek, loop and playback-rate changes. Score following maps audio time through source-timestamp-linked score/timing data; it must not reconstruct time from one BPM.

## Production
Do not introduce production infrastructure before its epic. When productionization starts: jobs must be durable/recoverable, resources bounded, artifacts lifecycle-managed, logs/metrics useful, retries idempotent and secrets never committed.

## Task completion
An issue is complete only when acceptance criteria are met, relevant tests pass, no known regression was introduced, changed contracts are documented, and newly discovered debt is recorded. If evidence contradicts a proposed implementation, stop and explain before making a major architectural substitution.
