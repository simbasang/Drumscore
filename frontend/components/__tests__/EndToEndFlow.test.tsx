import { act, fireEvent, render, screen } from "@testing-library/react";

import { getAnalysis, getProject, getSavedScore, saveScore } from "@/lib/api/projects";
import ProjectView from "../ProjectView";

jest.mock("@/lib/api/projects");

class FakeGainNode {
  gain = { value: 1 };
  connect = jest.fn();
}

class FakeBufferSource {
  buffer: unknown = null;
  playbackRate = { value: 1 };
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}

class FakeAudioContext {
  currentTime = 0;
  destination = {};
  close = jest.fn();
  createBufferSource() {
    return new FakeBufferSource();
  }
  createGain() {
    return new FakeGainNode();
  }
  decodeAudioData() {
    return Promise.resolve({ duration: 4 });
  }
}

function project(status: string) {
  return {
    id: "project-1",
    title: "Song",
    source_url: "u",
    created_at: "",
    updated_at: "",
    latest_job: { id: "j1", status, attempts: 1, max_attempts: 3, error: null, created_at: "", finished_at: null },
  };
}

describe("End-to-end flow", () => {
  beforeEach(() => {
    // @ts-expect-error -- jsdom has no AudioContext; substitute a minimal fake for this test only.
    global.AudioContext = FakeAudioContext;
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    } as unknown as Response);
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("should go from a processing project to a playable score whose edits can be saved", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("transcribing"))
      .mockResolvedValueOnce(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue({
      tempo_bpm: 120,
      events: [{ id: "e1", time: 0, instrument: "kick", confidence: null, provenance: "drumscript", measure: 1, beat: 1, subdivision: 0 }],
      beats: [],
    });
    (getSavedScore as jest.Mock).mockResolvedValue(null);
    (saveScore as jest.Mock).mockResolvedValue(1);

    render(<ProjectView apiBaseUrl="http://localhost:8000" projectId="project-1" />);
    await act(async () => {});
    expect(screen.getByText("Transcribing drum hits...")).toBeInTheDocument();
    await act(async () => {
      jest.advanceTimersByTime(2000);
    });
    jest.useRealTimers();

    const playButton = await screen.findByRole("button", { name: /play/i });
    const scoreContainer = screen.getByTestId("drum-score");
    expect(scoreContainer.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
    fireEvent.click(playButton);
    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    expect(saveScore).toHaveBeenCalledWith("http://localhost:8000", "project-1", expect.objectContaining({ measures: expect.any(Array) }), null);
  });
});
