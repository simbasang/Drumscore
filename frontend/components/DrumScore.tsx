"use client";

import { useEffect, useRef, useState } from "react";
import { Formatter, Renderer, Stave, Voice } from "vexflow";

import { buildStaveNote } from "@/lib/notation/buildStaveNote";
import { buildBeams } from "@/lib/notation/beaming";
import { computeRowLayout } from "@/lib/notation/layout";
import { computeNoteJustifyWidth } from "@/lib/notation/staveFormatting";
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "@/lib/notation/timeline";
import type { Score } from "@/lib/score/types";

interface DrumScoreProps {
  score: Score;
  currentTime?: number;
  onSeek?: (time: number) => void;
}

const ROW_HEIGHT = 120;
const STAVE_X_START = 10;
// Trailing safety margin (beyond the real clef/time-signature prefix width,
// see computeNoteJustifyWidth) so the last note's glyph doesn't touch the
// stave's right edge/barline. Also folded into each measure's precalculated
// minimum width so a stave sized exactly at that minimum still has room.
const MEASURE_INNER_PADDING = 20;
const PLAYHEAD_ID = "drum-score-playhead";
// Only a real width change (not sub-pixel float jitter from ResizeObserver)
// should trigger a relayout.
const RESIZE_THRESHOLD_PX = 1;

function averageSourceTime(sourceTimes: number[]): number {
  return sourceTimes.reduce((sum, time) => sum + time, 0) / sourceTimes.length;
}

export default function DrumScore({ score, currentTime, onSeek }: DrumScoreProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<TimelinePoint[]>([]);
  const [containerWidth, setContainerWidth] = useState(0);

  // Tracks the container's real width so layout can adapt to the viewport.
  // Deliberately its own effect, independent of the score/playhead effect
  // below, so a resize can never be triggered by playback ticking and
  // playback ticking can never trigger a relayout.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    setContainerWidth(container.clientWidth);

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const width = entry.contentRect.width;
        setContainerWidth((previous) => (Math.abs(previous - width) > RESIZE_THRESHOLD_PX ? width : previous));
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";
    timelineRef.current = [];

    const { measures } = score;
    if (measures.length === 0) {
      return;
    }

    const built = measures.map((measure) => {
      const notes = measure.map(buildStaveNote);
      // beams must be constructed before Formatter/voice.draw() - see
      // TECHNICAL_DEBT.md / #52 review.
      const beams = buildBeams(measure, notes);
      const voice = new Voice({ numBeats: 4, beatValue: 4 }).setStrict(false);
      voice.addTickables(notes);
      const minWidth = new Formatter().joinVoices([voice]).preCalculateMinTotalWidth([voice]);
      return { measure, notes, beams, voice, minWidth: minWidth + MEASURE_INNER_PADDING };
    });

    const availableWidth = Math.max(containerWidth - STAVE_X_START * 2, 0);
    const placements = computeRowLayout(
      built.map((measure) => measure.minWidth),
      availableWidth,
      { startX: STAVE_X_START },
    );

    const rows = Math.max(...placements.map((placement) => placement.row)) + 1;
    const width = Math.max(...placements.map((placement) => placement.x + placement.width)) + STAVE_X_START;
    const height = rows * ROW_HEIGHT + 40;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(width, height);
    const context = renderer.getContext();

    placements.forEach(({ index, row, col, x, width: staveWidth }) => {
      const { measure, notes, beams, voice } = built[index];
      const y = 20 + row * ROW_HEIGHT;

      const stave = new Stave(x, y, staveWidth);
      if (col === 0) {
        stave.addClef("percussion");
      }
      if (index === 0) {
        stave.setTimeSignature("4/4");
      }
      stave.setContext(context).draw();

      const justifyWidth = computeNoteJustifyWidth(stave, staveWidth, MEASURE_INNER_PADDING);
      new Formatter().joinVoices([voice]).format([voice], justifyWidth);
      voice.draw(context, stave);
      beams.forEach((beam) => beam.setContext(context).draw());

      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption.
        if (slot.type !== "note") {
          return;
        }
        const times = slot.hits.map((hit) => hit.time).filter((time): time is number => time != null);
        if (times.length === 0) {
          return;
        }
        const time = averageSourceTime(times);
        timelineRef.current.push({ time, x: note.getAbsoluteX(), row });

        if (onSeek) {
          const svgElement = note.getSVGElement();
          if (svgElement) {
            svgElement.style.cursor = "pointer";
            svgElement.addEventListener("click", () => onSeek(time));
          }
        }
      });
    });
  }, [score, containerWidth, onSeek]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || currentTime == null) {
      return;
    }

    const svg = container.querySelector("svg");
    if (!svg) {
      return;
    }

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
