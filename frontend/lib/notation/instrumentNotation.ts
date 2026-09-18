import type { DrumInstrument } from "@/lib/api/jobs";

export interface InstrumentNotation {
  key: string;
  articulation?: string;
}

export const INSTRUMENT_NOTATION: Record<DrumInstrument, InstrumentNotation> = {
  kick: { key: "f/4" },
  snare: { key: "c/5" },
  hihat_closed: { key: "g/5/x2" },
  hihat_open: { key: "g/5/x2", articulation: "ah" },
  crash: { key: "a/5/x3" },
  ride: { key: "f/5/x2" },
  tom_low: { key: "e/4" },
  tom_mid: { key: "a/4" },
  tom_high: { key: "d/5" },
};
