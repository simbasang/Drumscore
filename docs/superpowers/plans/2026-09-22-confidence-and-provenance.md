# Confidence and Provenance (V1-015 / #48) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add honest, documented confidence/provenance semantics to `DrumEvent` (GitHub issue #48 / V1-015) — `confidence` stays `None` for every DrumScript-produced event (no defensible signal exists, confirmed by reading `drumscript`'s classifier source), now explicitly documented and regression-tested as intentional rather than merely absent, and a new `provenance` field records which engine produced each event, exposed through the analysis API.

**Architecture:** One additive field on the existing `DrumEvent` frozen dataclass (`backend/app/transcription.py`), set by `DrumScriptTranscriber` (`backend/app/drumscript_transcriber.py`), threaded through `dataclasses.replace` call sites for free (Python's `dataclasses.replace` preserves any field not explicitly overridden — verified by reading `beat_mapping.py`'s and `job_processor.py`'s `dataclasses.replace` calls, neither of which touches `provenance` or `confidence`), and exposed via a new field on the existing `DrumEventResponse` API model (`backend/app/api/jobs.py`).

**Tech Stack:** Python 3.13, pytest, pydantic (existing dependency for API models). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md`, section "#48 — Confidence/provenance", GitHub issue #48, `CLAUDE.md`'s Transcription rules ("Never fabricate confidence values").

## Global Constraints

- `confidence` must never be synthesized from DrumScript's physics features (peak_freq/lfer/hfer/decay) or any other heuristic — `None` is the only honest value until an engine with a real confidence signal is integrated.
- The change is additive: no existing `DrumEvent`/`DrumEventResponse` field's meaning or default changes.
- Backend tests run via `cd backend && uv run pytest ...` (Python >=3.13, pytest). No new dependencies.
- Do not touch `drumscript`/`DrumScriptTranscriber`'s classification logic itself, `beat_mapping.py`, or `job_processor.py` — `dataclasses.replace`'s existing behavior already threads the new field through those files for free.

---

## File Structure

- Modify `backend/app/transcription.py` — add `provenance: str | None = None` to `DrumEvent`, document `confidence`'s honest-null semantics.
- Modify `backend/app/drumscript_transcriber.py` — set `provenance="drumscript"` on every produced event.
- Modify `backend/app/api/jobs.py` — add `confidence`/`provenance` fields to `DrumEventResponse` and its `from_event` mapping.
- Modify `backend/tests/test_drumscript_transcriber.py` — new regression test for the provenance/confidence contract.
- Modify `backend/tests/test_jobs_api.py` — update the shared `FakeTranscriber` fixture to set `provenance="drumscript"` (mirroring production), add a test asserting the API exposes both fields correctly.

---

### Task 1: Add provenance, document confidence, wire through to the API

**Files:**
- Modify: `backend/app/transcription.py` (the `DrumEvent` dataclass)
- Modify: `backend/app/drumscript_transcriber.py:33-44` (`_map_events`)
- Modify: `backend/app/api/jobs.py` (`DrumEventResponse` class and its `from_event` classmethod)
- Test: `backend/tests/test_drumscript_transcriber.py`, `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: nothing new from other tasks (this plan is a single task).
- Produces: `DrumEvent.provenance: str | None = None` (new field, positioned after `confidence` and before `measure` in the dataclass) — no other file in the codebase needs to know about this field beyond what's touched here, since `dataclasses.replace` preserves it automatically everywhere else `DrumEvent` is copied.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_drumscript_transcriber.py`, add this test (after the existing `test_transcribe_maps_known_instruments_and_splits_simultaneous_hits` test):

```python
def test_transcribe_sets_drumscript_as_provenance_and_leaves_confidence_null(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = _writes_events_file(
            [{"time_sec": 1.0, "instruments": ["kick", "snare"]}]
        )

        events = DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")

    assert len(events) == 2
    assert all(e.provenance == "drumscript" for e in events)
    assert all(e.confidence is None for e in events)
```

In `backend/tests/test_jobs_api.py`, change the `FakeTranscriber` class (near the top of the file, alongside the other fake dependency classes) from:

```python
class FakeTranscriber:
    def transcribe(self, audio_path):
        return [
            DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
            DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.HIHAT_CLOSED),
        ]
```

to:

```python
class FakeTranscriber:
    def transcribe(self, audio_path):
        return [
            DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK, provenance="drumscript"),
            DrumEvent(
                id="e2", time=0.5, instrument=DrumInstrument.HIHAT_CLOSED, provenance="drumscript"
            ),
        ]
```

(This mirrors real production behavior, where every event `DrumScriptTranscriber` produces carries `provenance="drumscript"`.)

Then add this new test to `backend/tests/test_jobs_api.py`, near `test_get_analysis_returns_tempo_and_events_when_job_is_tempo_mapped`:

```python
def test_get_analysis_exposes_confidence_and_provenance_fields():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/analysis")

    body = response.json()
    assert body["events"][0]["confidence"] is None
    assert body["events"][0]["provenance"] == "drumscript"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_drumscript_transcriber.py tests/test_jobs_api.py -v`
Expected: `test_transcribe_sets_drumscript_as_provenance_and_leaves_confidence_null` FAILS with `AttributeError: 'DrumEvent' object has no attribute 'provenance'` (the field doesn't exist yet). `test_get_analysis_exposes_confidence_and_provenance_fields` FAILS with a `KeyError`/`AssertionError` (the API response has no `confidence`/`provenance` keys yet). Other existing tests in `test_jobs_api.py` should still PASS (the `FakeTranscriber` change is additive — existing assertions on `id`/`time`/`instrument` are unaffected), unless one of them explicitly constructs a `DrumEvent(..., provenance=...)` call that would fail before the field exists — if so, that's expected too, and resolves once Step 3 lands.

- [ ] **Step 3: Add the `provenance` field to `DrumEvent`**

In `backend/app/transcription.py`, replace the `DrumEvent` dataclass:

```python
@dataclass(frozen=True)
class DrumEvent:
    id: str
    time: float
    instrument: DrumInstrument
    velocity: float | None = None
```

with:

```python
@dataclass(frozen=True)
class DrumEvent:
    id: str
    time: float
    instrument: DrumInstrument
    velocity: float | None = None
```

(keep this part unchanged), then replace the line immediately below it:

```python
    confidence: float | None = None
```

with:

```python
    # Confidence in this event's instrument classification, in [0, 1], or
    # None when the producing engine has no defensible confidence signal.
    # DrumScript (this v1.0's only transcriber) is a deterministic
    # rule-based physics/threshold classifier - see
    # backend/drumscript_runner/.venv/.../drum_classifier/classify.py,
    # which assigns instruments via hard-coded frequency/energy-ratio
    # thresholds with no probability or score-margin output anywhere in
    # its classification path - so DrumScriptTranscriber always leaves this
    # None. Never synthesize a confidence value (e.g. from a
    # threshold-distance heuristic) merely to populate this field; null is
    # the honest answer until an engine with a real signal is integrated.
    confidence: float | None = None
    # Which engine/stage produced this event, e.g. "drumscript". None for
    # events not yet attributed to a producing engine.
    provenance: str | None = None
```

The full `DrumEvent` dataclass after this step reads:

```python
@dataclass(frozen=True)
class DrumEvent:
    id: str
    time: float
    instrument: DrumInstrument
    velocity: float | None = None
    # Confidence in this event's instrument classification, in [0, 1], or
    # None when the producing engine has no defensible confidence signal.
    # DrumScript (this v1.0's only transcriber) is a deterministic
    # rule-based physics/threshold classifier - see
    # backend/drumscript_runner/.venv/.../drum_classifier/classify.py,
    # which assigns instruments via hard-coded frequency/energy-ratio
    # thresholds with no probability or score-margin output anywhere in
    # its classification path - so DrumScriptTranscriber always leaves this
    # None. Never synthesize a confidence value (e.g. from a
    # threshold-distance heuristic) merely to populate this field; null is
    # the honest answer until an engine with a real signal is integrated.
    confidence: float | None = None
    # Which engine/stage produced this event, e.g. "drumscript". None for
    # events not yet attributed to a producing engine.
    provenance: str | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None
```

- [ ] **Step 4: Set `provenance` in `DrumScriptTranscriber`**

In `backend/app/drumscript_transcriber.py`, change `_map_events` from:

```python
def _map_events(raw_events: list[dict]) -> list[DrumEvent]:
    events: list[DrumEvent] = []

    for raw_event in raw_events:
        time = raw_event["time_sec"]
        for raw_instrument in raw_event["instruments"]:
            instrument = _INSTRUMENT_MAP.get(raw_instrument)
            if instrument is None:
                continue
            events.append(DrumEvent(id=str(uuid.uuid4()), time=time, instrument=instrument))

    return events
```

to:

```python
def _map_events(raw_events: list[dict]) -> list[DrumEvent]:
    events: list[DrumEvent] = []

    for raw_event in raw_events:
        time = raw_event["time_sec"]
        for raw_instrument in raw_event["instruments"]:
            instrument = _INSTRUMENT_MAP.get(raw_instrument)
            if instrument is None:
                continue
            events.append(
                DrumEvent(
                    id=str(uuid.uuid4()),
                    time=time,
                    instrument=instrument,
                    provenance="drumscript",
                )
            )

    return events
```

- [ ] **Step 5: Expose `confidence`/`provenance` on the analysis API**

In `backend/app/api/jobs.py`, change the `DrumEventResponse` class from:

```python
class DrumEventResponse(BaseModel):
    id: str
    time: float
    instrument: DrumInstrument
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None

    @classmethod
    def from_event(cls, event: DrumEvent) -> "DrumEventResponse":
        return cls(
            id=event.id,
            time=event.time,
            instrument=event.instrument,
            measure=event.measure,
            beat=event.beat,
            subdivision=event.subdivision,
        )
```

to:

```python
class DrumEventResponse(BaseModel):
    id: str
    time: float
    instrument: DrumInstrument
    confidence: float | None = None
    provenance: str | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None

    @classmethod
    def from_event(cls, event: DrumEvent) -> "DrumEventResponse":
        return cls(
            id=event.id,
            time=event.time,
            instrument=event.instrument,
            confidence=event.confidence,
            provenance=event.provenance,
            measure=event.measure,
            beat=event.beat,
            subdivision=event.subdivision,
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_drumscript_transcriber.py tests/test_jobs_api.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS (this is a purely additive change — nothing that reads `DrumEvent` or `DrumEventResponse` positionally should break, since both are keyword-constructed everywhere in the codebase; confirm this holds).

- [ ] **Step 8: Commit**

```bash
git add backend/app/transcription.py backend/app/drumscript_transcriber.py backend/app/api/jobs.py backend/tests/test_drumscript_transcriber.py backend/tests/test_jobs_api.py
git commit -m "feat: add DrumEvent.provenance and document confidence's honest-null semantics"
```

---

## Self-Review Notes

- **Spec coverage:** "Confidence semantics are documented" → the new docstring on `DrumEvent.confidence`. "Unsupported engines return null rather than fake values" → `DrumScriptTranscriber` never sets `confidence`, tested explicitly. "Provenance identifies engine/stage" → `provenance="drumscript"`, tested. "API/domain tests cover fields" → both the domain-level test (`test_drumscript_transcriber.py`) and the API-level test (`test_jobs_api.py`) added. The API-exposure decision (adding `confidence` to `DrumEventResponse`, not just `provenance`, even though the design doc's prose only explicitly named `provenance`) is a ruling: the issue's own acceptance criteria says "API/domain tests cover fields" (plural) and a `null` confidence that's invisible from the API isn't meaningfully "honest" to API consumers — so both fields are exposed together. Cost if wrong: trivial to revert (delete two lines), no behavior depends on it being present.
- **Placeholder scan:** none — every step has complete code.
- **Type consistency:** `provenance: str | None = None` matches exactly between `DrumEvent` (Step 3), `DrumScriptTranscriber` (Step 4, string literal `"drumscript"`), `DrumEventResponse` (Step 5), and both tests (Step 1).
