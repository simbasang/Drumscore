import type { AnalysisEvent, DrumInstrument } from "@/lib/api/types";

export interface GrooveFixture {
  name: string;
  description: string;
  events: AnalysisEvent[];
}

let nextId = 0;

function hit(
  measure: number,
  beat: number,
  subdivision: number,
  instrument: DrumInstrument,
  time: number,
): AnalysisEvent {
  nextId += 1;
  return {
    id: `fixture-${nextId}`,
    time,
    instrument,
    confidence: null,
    provenance: "drumscript",
    measure,
    beat,
    subdivision,
  };
}

// Representative grooves covering V1-022's (#73) acceptance criteria: sparse
// and dense grooves, rest consolidation, simultaneous hits, open hi-hat and a
// fill. Consumed by goldenFixtures.test.ts (structural engraving-property
// assertions) and DrumScore's own fixture smoke-render test, and documented
// for manual visual review in docs/notation-golden-fixtures.md.
export const GROOVE_FIXTURES: GrooveFixture[] = [
  {
    name: "sparseBackbeat",
    description: "Classic kick/snare backbeat, one hit per beat, nothing else - the sparse case.",
    events: [
      hit(1, 1, 0, "kick", 0.0),
      hit(1, 2, 0, "snare", 0.5),
      hit(1, 3, 0, "kick", 1.0),
      hit(1, 4, 0, "snare", 1.5),
    ],
  },
  {
    name: "denseSixteenths",
    description: "Continuous closed hi-hat on every sixteenth-note slot of one measure - the dense case.",
    events: Array.from({ length: 16 }, (_, index) =>
      hit(1, Math.floor(index / 4) + 1, index % 4, "hihat_closed", index * 0.125),
    ),
  },
  {
    name: "restStretch",
    description: "A single isolated kick on beat 2, silence before and after - exercises rest consolidation.",
    events: [hit(1, 2, 0, "kick", 0.5)],
  },
  {
    name: "simultaneousHits",
    description: "Kick, snare and closed hi-hat struck together on beat 1 - one grouped note, not three.",
    events: [
      hit(1, 1, 0, "kick", 0.0),
      hit(1, 1, 0, "snare", 0.0),
      hit(1, 1, 0, "hihat_closed", 0.0),
    ],
  },
  {
    name: "openHihatAlternation",
    description: "Closed/open hi-hat alternating on each beat - exercises the notehead-only distinction.",
    events: [
      hit(1, 1, 0, "hihat_closed", 0.0),
      hit(1, 2, 0, "hihat_open", 0.5),
      hit(1, 3, 0, "hihat_closed", 1.0),
      hit(1, 4, 0, "hihat_open", 1.5),
    ],
  },
  {
    name: "tomFill",
    description: "Kick/snare backbeat on beats 1-3, then a descending tom fill across beat 4's sixteenths.",
    events: [
      hit(1, 1, 0, "kick", 0.0),
      hit(1, 2, 0, "snare", 0.5),
      hit(1, 3, 0, "kick", 1.0),
      hit(1, 4, 0, "tom_high", 1.5),
      hit(1, 4, 1, "tom_mid", 1.625),
      hit(1, 4, 2, "tom_low", 1.75),
      hit(1, 4, 3, "snare", 1.875),
    ],
  },
];

export function groove(name: string): GrooveFixture {
  const fixture = GROOVE_FIXTURES.find((candidate) => candidate.name === name);
  if (!fixture) {
    throw new Error(`No groove fixture named "${name}"`);
  }
  return fixture;
}
