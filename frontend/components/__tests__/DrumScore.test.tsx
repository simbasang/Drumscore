import { act, render, screen } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
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

describe("DrumScore", () => {
  it("should render an SVG score without throwing for a simple beat", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "3", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_open", beat: 3, subdivision: 2, time: 1.25 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(container.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
  });

  it("should render nothing extra for an empty event list", () => {
    render(<DrumScore events={[]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should not throw when given a currentTime but no events to build a score from", () => {
    render(<DrumScore events={[]} currentTime={5} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stemPaths = container.querySelectorAll(".vf-stem");

    expect(stemPaths.length).toBeGreaterThan(0);
  });

  it("should not draw a playhead line when currentTime is not provided", () => {
    render(<DrumScore events={[event({ id: "1", beat: 1, subdivision: 0, time: 0 })]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("#drum-score-playhead")).toBeNull();
  });

  it("should draw a playhead line positioned at the current time, driven by each event's own source time", () => {
    const events = [
      event({ id: "1", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", beat: 3, subdivision: 0, time: 7.3 }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);

    const container = screen.getByTestId("drum-score");
    const lineAtStart = container.querySelector("#drum-score-playhead");
    expect(lineAtStart).not.toBeNull();
    const xAtStart = Number(lineAtStart?.getAttribute("x1"));

    // 7.3s is event 2's own real source time, not anything computeSlotTimeSeconds
    // would derive from a BPM - this is what "source-linked" means here.
    rerender(<DrumScore currentTime={7.3} events={events} />);

    const lineLater = container.querySelector("#drum-score-playhead");
    const xLater = Number(lineLater?.getAttribute("x1"));

    expect(xLater).toBeGreaterThan(xAtStart);
  });

  it("should auto-scroll the container horizontally to keep the playhead in view", () => {
    // Adaptive layout sizes rows from the container's real clientWidth at
    // mount, so it must be mocked wide (as a real browser's would be) before
    // rendering - a narrow-container layout would place measure 4 close
    // enough to x=0 that no scroll would be needed at all.
    // jsdom defines clientWidth on Element.prototype, not HTMLElement.prototype
    // - getOwnPropertyDescriptor on HTMLElement.prototype would find nothing
    // to restore, permanently leaking this mock into every later test in the
    // file. Mock (and restore) it where it's actually defined.
    const originalDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
    Object.defineProperty(Element.prototype, "clientWidth", { value: 2000, configurable: true });

    try {
      const events = [
        event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
        event({ id: "2", measure: 4, beat: 4, subdivision: 3, time: 8 }),
      ];

      const { rerender } = render(<DrumScore currentTime={0} events={events} />);

      const container = screen.getByTestId("drum-score");
      // Narrows just the container's own clientWidth for the auto-scroll
      // viewport calculation itself (read live on every currentTime update),
      // independent of the wide mount-time layout width above.
      Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
      container.scrollLeft = 0;

      rerender(<DrumScore currentTime={8} events={events} />);

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
    // With no container width mocked, jsdom's clientWidth stays 0, so adaptive
    // layout's greedy packer places every measure on its own row - measure 5
    // still lands on a different row than measure 4, just not row 1 anymore.
    const lastRowZeroTime = 3.95;
    const firstRowOneTime = 4.2;
    const events = [
      event({ id: "1", measure: 4, beat: 4, subdivision: 3, instrument: "kick", time: lastRowZeroTime }),
      event({ id: "2", measure: 5, beat: 1, subdivision: 0, instrument: "snare", time: firstRowOneTime }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);
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
      rerender(<DrumScore currentTime={time} events={events} />);
      const line = container.querySelector("#drum-score-playhead")!;
      const x = Number(line.getAttribute("x1"));
      const y = Number(line.getAttribute("y1"));

      if (previousX !== null && previousY === y) {
        expect(x).toBeGreaterThanOrEqual(previousX);
      }
      previousX = x;
      previousY = y;
    }

    // Sanity check the boundary was actually exercised across two rows.
    rerender(<DrumScore currentTime={lastRowZeroTime} events={events} />);
    const yBeforeBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    rerender(<DrumScore currentTime={firstRowOneTime} events={events} />);
    const yAfterBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    expect(yAfterBoundary).not.toBe(yBeforeBoundary);
  });

  it("should not require a tempoBpm prop", () => {
    // @ts-expect-error tempoBpm is no longer part of DrumScoreProps
    render(<DrumScore events={[]} tempoBpm={120} />);

    expect(screen.getByTestId("drum-score")).toBeInTheDocument();
  });

  it("should render a separate beam per beat for a straight eighth-note groove, not one beam per measure", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    // VexFlow 5 puts the "vf-beam" class on the wrapping <g> for each beam
    // group (the inner connecting <path> is unclassed), so querying on the
    // group element is what actually counts distinct beams.
    const beamGroups = container.querySelectorAll("g.vf-beam");

    expect(beamGroups.length).toBe(2);
  });

  it("should draw exactly one stem per beamed note, not a duplicate unbeamed stem underneath the beam", () => {
    // Regression test for building Beams AFTER Formatter/voice.draw(): VexFlow's
    // Beam constructor calls note.setBeam(this), and StaveNote only skips
    // drawing its own (un-extended) stem when that beam reference is already
    // set at draw time (see StaveNote.draw(): shouldRenderStem = hasStem() &&
    // !this.beam). Building beams too late left every beamed note with two
    // .vf-stem elements - its own short stem plus the beam's extended one.
    // Verified empirically: with the buggy call order this count is 8 (2 per
    // note x 4 notes); with beams built before Formatter/draw it is 4.
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stems = container.querySelectorAll(".vf-stem");

    expect(stems.length).toBe(4);
  });

  it("should reflow into more rows (a taller score) when the container becomes narrower after a resize", () => {
    const fakeResizeObserver = installFakeResizeObserver();
    try {
      const events = Array.from({ length: 8 }, (_, i) =>
        event({ id: String(i), measure: i + 1, beat: 1, subdivision: 0, time: i }),
      );

      render(<DrumScore events={events} />);
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
    const events = [
      event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", measure: 2, beat: 1, subdivision: 0, time: 1 }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);
    const container = screen.getByTestId("drum-score");
    const svgBefore = container.querySelector("svg");

    rerender(<DrumScore currentTime={0.5} events={events} />);
    const svgAfter = container.querySelector("svg");

    expect(svgAfter).toBe(svgBefore);
  });
});
