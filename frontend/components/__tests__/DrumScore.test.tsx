import { act, fireEvent, render, screen } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "@/lib/score/buildScore";
import DrumScore from "../DrumScore";

function installFakeResizeObserver() {
  const registry = new Map<Element, ResizeObserverCallback>();

  class FakeResizeObserver {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      registry.set(target, this.callback);
    }
    unobserve(target: Element) {
      registry.delete(target);
    }
    disconnect() {}
  }

  const original = global.ResizeObserver;
  global.ResizeObserver = FakeResizeObserver;

  return {
    resize(target: Element, width: number) {
      Object.defineProperty(target, "clientWidth", { value: width, configurable: true });
      const callback = registry.get(target);
      callback?.([{ target, contentRect: { width } } as ResizeObserverEntry], undefined as unknown as ResizeObserver);
    },
    restore() {
      global.ResizeObserver = original;
    },
  };
}

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

function buildScore(events: AnalysisEvent[]) {
  return fromAnalysisEvents(events);
}

describe("DrumScore", () => {
  it("should render an SVG score without throwing for a simple beat", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "3", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_open", beat: 3, subdivision: 2, time: 1.25 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(container.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
  });

  it("should render nothing extra for an empty score", () => {
    render(<DrumScore score={buildScore([])} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should not throw when given a currentTime but an empty score", () => {
    render(<DrumScore score={buildScore([])} currentTime={5} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stemPaths = container.querySelectorAll(".vf-stem");

    expect(stemPaths.length).toBeGreaterThan(0);
  });

  it("should not draw a playhead line when currentTime is not provided", () => {
    render(<DrumScore score={buildScore([event({ id: "1", beat: 1, subdivision: 0, time: 0 })])} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("#drum-score-playhead")).toBeNull();
  });

  it("should draw a playhead line positioned at the current time, driven by each event's own source time", () => {
    const score = buildScore([
      event({ id: "1", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", beat: 3, subdivision: 0, time: 7.3 }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);

    const container = screen.getByTestId("drum-score");
    const lineAtStart = container.querySelector("#drum-score-playhead");
    expect(lineAtStart).not.toBeNull();
    const xAtStart = Number(lineAtStart?.getAttribute("x1"));

    rerender(<DrumScore currentTime={7.3} score={score} />);

    const lineLater = container.querySelector("#drum-score-playhead");
    const xLater = Number(lineLater?.getAttribute("x1"));

    expect(xLater).toBeGreaterThan(xAtStart);
  });

  it("should auto-scroll the container horizontally to keep the playhead in view", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
    Object.defineProperty(Element.prototype, "clientWidth", { value: 2000, configurable: true });

    try {
      const score = buildScore([
        event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
        event({ id: "2", measure: 4, beat: 4, subdivision: 3, time: 8 }),
      ]);

      const { rerender } = render(<DrumScore currentTime={0} score={score} />);

      const container = screen.getByTestId("drum-score");
      Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
      container.scrollLeft = 0;

      rerender(<DrumScore currentTime={8} score={score} />);

      expect(container.scrollLeft).toBeGreaterThan(0);
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(Element.prototype, "clientWidth", originalDescriptor);
      } else {
        delete (Element.prototype as { clientWidth?: number }).clientWidth;
      }
    }
  });

  it("should never move the playhead backward in x while stepping through a real multi-row score", () => {
    const lastRowZeroTime = 3.95;
    const firstRowOneTime = 4.2;
    const score = buildScore([
      event({ id: "1", measure: 4, beat: 4, subdivision: 3, instrument: "kick", time: lastRowZeroTime }),
      event({ id: "2", measure: 5, beat: 1, subdivision: 0, instrument: "snare", time: firstRowOneTime }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);
    const container = screen.getByTestId("drum-score");

    const sampleTimes = [
      lastRowZeroTime - 0.05,
      lastRowZeroTime,
      (lastRowZeroTime + firstRowOneTime) / 2,
      firstRowOneTime,
    ];

    let previousX: number | null = null;
    let previousY: number | null = null;
    for (const time of sampleTimes) {
      rerender(<DrumScore currentTime={time} score={score} />);
      const line = container.querySelector("#drum-score-playhead")!;
      const x = Number(line.getAttribute("x1"));
      const y = Number(line.getAttribute("y1"));

      if (previousX !== null && previousY === y) {
        expect(x).toBeGreaterThanOrEqual(previousX);
      }
      previousX = x;
      previousY = y;
    }

    rerender(<DrumScore currentTime={lastRowZeroTime} score={score} />);
    const yBeforeBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    rerender(<DrumScore currentTime={firstRowOneTime} score={score} />);
    const yAfterBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    expect(yAfterBoundary).not.toBe(yBeforeBoundary);
  });

  it("should not require a tempoBpm prop", () => {
    // @ts-expect-error tempoBpm is not part of DrumScoreProps
    render(<DrumScore score={buildScore([])} tempoBpm={120} />);

    expect(screen.getByTestId("drum-score")).toBeInTheDocument();
  });

  it("should render a separate beam per beat for a straight eighth-note groove, not one beam per measure", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const beamGroups = container.querySelectorAll("g.vf-beam");

    expect(beamGroups.length).toBe(2);
  });

  it("should draw exactly one stem per beamed note, not a duplicate unbeamed stem underneath the beam", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stems = container.querySelectorAll(".vf-stem");

    expect(stems.length).toBe(4);
  });

  it("should reflow into more rows (a taller score) when the container becomes narrower after a resize", () => {
    const fakeResizeObserver = installFakeResizeObserver();
    try {
      const score = buildScore(
        Array.from({ length: 8 }, (_, i) => event({ id: String(i), measure: i + 1, beat: 1, subdivision: 0, time: i })),
      );

      render(<DrumScore score={score} />);
      const container = screen.getByTestId("drum-score");

      act(() => {
        fakeResizeObserver.resize(container, 2000);
      });
      const wideHeight = Number(container.querySelector("svg")!.getAttribute("height"));

      act(() => {
        fakeResizeObserver.resize(container, 250);
      });
      const narrowHeight = Number(container.querySelector("svg")!.getAttribute("height"));

      expect(narrowHeight).toBeGreaterThan(wideHeight);
    } finally {
      fakeResizeObserver.restore();
    }
  });

  it("should not rebuild the score when only currentTime changes, keeping row breaks stable during playback", () => {
    const score = buildScore([
      event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", measure: 2, beat: 1, subdivision: 0, time: 1 }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);
    const container = screen.getByTestId("drum-score");
    const svgBefore = container.querySelector("svg");

    rerender(<DrumScore currentTime={0.5} score={score} />);
    const svgAfter = container.querySelector("svg");

    expect(svgAfter).toBe(svgBefore);
  });

  it("should call onSeek with a note's source time when it is clicked", () => {
    const onSeek = jest.fn();
    const score = buildScore([event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 3.5 })]);

    render(<DrumScore score={score} onSeek={onSeek} />);

    const container = screen.getByTestId("drum-score");
    const note = container.querySelector(".vf-stavenote")!;
    fireEvent.click(note);

    expect(onSeek).toHaveBeenCalledWith(3.5);
  });

  it("should not call onSeek when a rest slot is clicked", () => {
    const onSeek = jest.fn();
    // A single hit placed mid-measure (beat 2), rather than at beat 1,
    // so the note's duration-extension (see consolidateDurations /
    // V1-018 in lib/score/grid.ts) can't absorb the whole rest of the
    // measure into the note itself - it stops at the next valid aligned
    // duration boundary, leaving a real trailing rest slot to click.
    const score = buildScore([event({ id: "1", instrument: "kick", beat: 2, subdivision: 0, time: 1 })]);

    render(<DrumScore score={score} onSeek={onSeek} />);

    const container = screen.getByTestId("drum-score");
    const staveNotes = container.querySelectorAll(".vf-stavenote");
    const lastRest = staveNotes[staveNotes.length - 1];
    fireEvent.click(lastRest);

    expect(onSeek).not.toHaveBeenCalled();
  });
});
