"use client";

import { useEffect, useRef } from "react";
import { Beam, Formatter, Fraction, Renderer, Stave, Voice } from "vexflow";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { buildMeasures } from "@/lib/notation/buildScore";
import { buildStaveNote } from "@/lib/notation/buildStaveNote";

interface DrumScoreProps {
  events: AnalysisEvent[];
}

const MEASURES_PER_ROW = 4;
const MEASURE_WIDTH = 200;
const ROW_HEIGHT = 120;
const STAVE_X_START = 10;

export default function DrumScore({ events }: DrumScoreProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";

    const measures = buildMeasures(events);
    if (measures.length === 0) {
      return;
    }

    const rows = Math.ceil(measures.length / MEASURES_PER_ROW);
    const width = MEASURES_PER_ROW * MEASURE_WIDTH + STAVE_X_START * 2;
    const height = rows * ROW_HEIGHT + 40;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(width, height);
    const context = renderer.getContext();

    measures.forEach((measure, index) => {
      const row = Math.floor(index / MEASURES_PER_ROW);
      const col = index % MEASURES_PER_ROW;
      const x = STAVE_X_START + col * MEASURE_WIDTH;
      const y = 20 + row * ROW_HEIGHT;

      const stave = new Stave(x, y, MEASURE_WIDTH);
      if (col === 0) {
        stave.addClef("percussion");
      }
      if (index === 0) {
        stave.setTimeSignature("4/4");
      }
      stave.setContext(context).draw();

      const notes = measure.map(buildStaveNote);
      const voice = new Voice({ numBeats: 4, beatValue: 4 }).setStrict(false);
      voice.addTickables(notes);

      new Formatter().joinVoices([voice]).format([voice], MEASURE_WIDTH - 20);
      voice.draw(context, stave);

      const beams = Beam.generateBeams(notes, {
        stemDirection: 1,
        maintainStemDirections: true,
        beamRests: false,
        groups: [new Fraction(1, 4)],
      });
      beams.forEach((beam) => beam.setContext(context).draw());
    });
  }, [events]);

  return (
    <div
      ref={containerRef}
      data-testid="drum-score"
      style={{ width: "100%", overflowX: "auto" }}
    />
  );
}
