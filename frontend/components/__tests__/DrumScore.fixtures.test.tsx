import { render, screen } from "@testing-library/react";

import { GROOVE_FIXTURES } from "@/lib/notation/__fixtures__/grooves";
import { fromAnalysisEvents } from "@/lib/score/buildScore";
import DrumScore from "../DrumScore";

describe("DrumScore golden fixtures", () => {
  it.each(GROOVE_FIXTURES.map((fixture) => [fixture.name, fixture] as const))(
    "should render %s as an SVG score with one stave-note element per slot (note or rest)",
    (_name, fixture) => {
      const expectedSlotCount = fromAnalysisEvents(fixture.events).measures.flat().length;

      render(<DrumScore events={fixture.events} />);

      const container = screen.getByTestId("drum-score");
      const svg = container.querySelector("svg");

      expect(svg).not.toBeNull();
      expect(container.querySelectorAll(".vf-stavenote").length).toBe(expectedSlotCount);
    },
  );
});
