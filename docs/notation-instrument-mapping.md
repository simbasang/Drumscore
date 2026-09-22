# Instrument-to-notation mapping (V1-020)

How each `DrumInstrument` maps to a five-line percussion staff position and notehead in
`frontend/lib/notation/instrumentNotation.ts`. This is the single source of truth for
engraving conventions in Drumscore; the table below is a human-readable mirror of that
file, not a separate spec — if they disagree, the code is correct and this doc is stale.

## Mapping table

| Instrument     | Staff key | Notehead        | Notes                                   |
|----------------|-----------|------------------|------------------------------------------|
| `kick`         | `f/4`     | normal           | Bottom space                             |
| `snare`        | `c/5`     | normal           | Middle line                              |
| `hihat_closed` | `g/5`     | X (plain)        | Top line                                 |
| `hihat_open`   | `g/5`     | X in a circle    | Same pitch as closed hi-hat              |
| `crash`        | `a/5`     | X in a circle    | Above the staff                          |
| `ride`         | `f/5`     | X (plain)        | Above the top line                       |
| `tom_low`      | `e/4`     | normal           |                                           |
| `tom_mid`      | `a/4`     | normal           |                                           |
| `tom_high`     | `d/5`     | normal           |                                           |

## Closed vs. open hi-hat

Both share the same staff position (`g/5`) so a player reads them as "the hi-hat," not
two different instruments. They're distinguished by **notehead shape only**:

- **Closed**: plain X notehead.
- **Open**: X notehead inside a circle (VexFlow's `noteheadCircleX`, key suffix `/x3`).

This was chosen over marking open hi-hat with a floating articulation glyph above the
note (VexFlow's `Articulation` modifiers, e.g. `"ah"`/`"ao"`) because a notehead-shape
change reads unambiguously at a glance and matches common commercial drum-notation
software. The previous implementation used the `"ah"` articulation code, which renders
VexFlow's *string-harmonics* glyph (`Glyphs.stringsHarmonic`) — visually a small circle,
but semantically the wrong glyph, borrowed rather than purpose-built for percussion. It
has been removed along with the now-unused `articulation` field on `InstrumentNotation`.

## Crash vs. ride

Crash and ride already had distinct staff positions (`a/5` vs. `f/5`) before this issue;
no change was needed. Crash's circled-X notehead is shared with open hi-hat's shape, but
the two never collide visually because they sit at different staff positions.

## Regression coverage

`frontend/lib/notation/__tests__/instrumentNotation.test.ts` locks the full mapping
table (so an accidental edit fails a test instead of silently changing rendered
notation) and separately asserts that closed/open hi-hat share a pitch but differ in
notehead, and that crash/ride noteheads differ. `buildStaveNote.test.ts` covers the
notehead assignment at the `StaveNote`-construction level and the forced-upward-stem
requirement.
