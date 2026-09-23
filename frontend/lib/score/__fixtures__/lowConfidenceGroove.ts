import type { AnalysisEvent } from "@/lib/api/jobs";

// Synthetic fixture: real production jobs never populate confidence (see
// TECHNICAL_DEBT.md / Epic 3 - DrumScriptTranscriber never fabricates a
// confidence value it can't defend), so this is the only way to exercise
// the low-confidence review UI until a future transcription-engine change
// adds a real confidence signal.
export const LOW_CONFIDENCE_GROOVE_EVENTS: AnalysisEvent[] = [
  {
    id: "e1",
    time: 0,
    instrument: "kick",
    confidence: 0.9,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
  },
  {
    id: "e2",
    time: 0.5,
    instrument: "snare",
    confidence: 0.2,
    provenance: "drumscript",
    measure: 1,
    beat: 2,
    subdivision: 0,
  },
];
