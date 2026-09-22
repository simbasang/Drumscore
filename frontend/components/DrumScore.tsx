"use client";

import { useEffect, useRef } from "react";
import { Beam, Formatter, Fraction, Renderer, Stave, Voice } from "vexflow";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "@/lib/score/buildScore";
import { buildStaveNote } from "@/lib/notation/buildStaveNote";
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "@/lib/notation/timeline";

interface DrumScoreProps {
  events: AnalysisEvent[];
  currentTime?: number;
}

const MEASURES_PER_ROW = 4;
const MEASURE_WIDTH = 200;
const ROW_HEIGHT = 120;
const STAVE_X_START = 10;
const PLAYHEAD_ID = "drum-score-playhead";

function averageSourceTime(sourceTimes: number[]): number {
  return sourceTimes.reduce((sum, time) => sum + time, 0) / sourceTimes.length;
}

export default function DrumScore({ events, currentTime }: DrumScoreProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<TimelinePoint[]>([]);

  useEffect(() => {
    // containerRef is attached to the div this component always renders,
    // so React guarantees it's set before this effect runs; this guard only
    // satisfies the nullable ref type.
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";
    timelineRef.current = [];

    const { measures } = fromAnalysisEvents(events);
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

      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption (see
        // interpolatePlayheadX in lib/notation/timeline.ts).
        if (slot.type !== "note") {
          return;
        }
        const times = slot.hits.map((hit) => hit.time).filter((time): time is number => time != null);
        if (times.length === 0) {
          return;
        }
        timelineRef.current.push({
          time: averageSourceTime(times),
          x: note.getAbsoluteX(),
          row,
        });
      });
    });
  }, [events]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || currentTime == null) {
      return;
    }

    const svg = container.querySelector("svg");
    if (!svg) {
      return;
    }

    // point is only null when no note slots exist anywhere in the score (an
    // all-rest measure contributes zero timeline points, since only note
    // slots get pushed) - the svg guard above already returns in that case.
    // Kept as a defensive type narrowing.
    const point = interpolatePlayheadX(timelineRef.current, currentTime);
    if (!point) {
      return;
    }

    const yTop = 15 + point.row * ROW_HEIGHT;
    const yBottom = yTop + ROW_HEIGHT - 25;

    let line = svg.querySelector(`#${PLAYHEAD_ID}`);
    if (!line) {
      line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("id", PLAYHEAD_ID);
      line.setAttribute("stroke", "#e53e3e");
      line.setAttribute("stroke-width", "2");
      svg.appendChild(line);
    }
    line.setAttribute("x1", String(point.x));
    line.setAttribute("x2", String(point.x));
    line.setAttribute("y1", String(yTop));
    line.setAttribute("y2", String(yBottom));

    container.scrollLeft = computeAutoScrollLeft(container.scrollLeft, container.clientWidth, point.x);
  }, [currentTime]);

  return (
    <div
      ref={containerRef}
      data-testid="drum-score"
      style={{ width: "100%", overflowX: "auto" }}
    />
  );
}
