import { render, screen } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import DrumScore from "../DrumScore";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
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
    const events = [
      event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", measure: 4, beat: 4, subdivision: 3, time: 8 }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);

    const container = screen.getByTestId("drum-score");
    Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
    container.scrollLeft = 0;

    rerender(<DrumScore currentTime={8} events={events} />);

    expect(container.scrollLeft).toBeGreaterThan(0);
  });

  it("should never move the playhead backward in x while stepping through a real multi-row score", () => {
    // MEASURES_PER_ROW is 4, so measure 5 starts a second row.
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
});
