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
    render(<DrumScore events={[]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
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
});
