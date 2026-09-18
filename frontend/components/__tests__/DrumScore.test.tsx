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
        tempoBpm={120}
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 0 }),
          event({ id: "3", instrument: "snare", beat: 2, subdivision: 0 }),
          event({ id: "4", instrument: "hihat_open", beat: 3, subdivision: 2 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(container.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
  });

  it("should render nothing extra for an empty event list", () => {
    render(<DrumScore tempoBpm={120} events={[]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should not throw when given a currentTime but no events to build a score from", () => {
    render(<DrumScore tempoBpm={120} events={[]} currentTime={5} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
        tempoBpm={120}
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0 }),
          event({ id: "2", instrument: "snare", beat: 2, subdivision: 0 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stemPaths = container.querySelectorAll(".vf-stem");

    expect(stemPaths.length).toBeGreaterThan(0);
  });

  it("should not draw a playhead line when currentTime is not provided", () => {
    render(
      <DrumScore tempoBpm={120} events={[event({ id: "1", beat: 1, subdivision: 0 })]} />,
    );

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("#drum-score-playhead")).toBeNull();
  });

  it("should draw a playhead line positioned at the current time", () => {
    const { rerender } = render(
      <DrumScore
        tempoBpm={120}
        currentTime={0}
        events={[event({ id: "1", beat: 1, subdivision: 0 })]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const lineAtStart = container.querySelector("#drum-score-playhead");
    expect(lineAtStart).not.toBeNull();
    const xAtStart = Number(lineAtStart?.getAttribute("x1"));

    rerender(
      <DrumScore
        tempoBpm={120}
        currentTime={1}
        events={[event({ id: "1", beat: 1, subdivision: 0 })]}
      />,
    );

    const lineLater = container.querySelector("#drum-score-playhead");
    const xLater = Number(lineLater?.getAttribute("x1"));

    expect(xLater).toBeGreaterThan(xAtStart);
  });

  it("should auto-scroll the container horizontally to keep the playhead in view", () => {
    const events = [
      event({ id: "1", measure: 1, beat: 1, subdivision: 0 }),
      event({ id: "2", measure: 4, beat: 4, subdivision: 3 }),
    ];

    const { rerender } = render(<DrumScore tempoBpm={120} currentTime={0} events={events} />);

    const container = screen.getByTestId("drum-score");
    Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
    container.scrollLeft = 0;

    rerender(<DrumScore tempoBpm={120} currentTime={8} events={events} />);

    expect(container.scrollLeft).toBeGreaterThan(0);
  });
});
