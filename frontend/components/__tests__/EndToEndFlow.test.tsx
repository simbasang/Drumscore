import { act, fireEvent, render, screen } from "@testing-library/react";

import { createJob, getAnalysis, getJob } from "@/lib/api/jobs";
import JobForm from "../JobForm";

// Only the network boundary is mocked. JobForm, Player, DrumScore,
// SyncedPlayer, and the notation-building modules all run for real, so
// this test proves the whole submit -> poll -> analyze -> play -> render
// chain is actually wired together, not just each piece in isolation.
jest.mock("@/lib/api/jobs");

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

  it("goes from submitting a URL to a playable, rendered drum score", async () => {
    (createJob as jest.Mock).mockResolvedValue({
      id: "job-1",
      url: "https://youtu.be/dQw4w9WgXcQ",
      status: "queued",
    });
    (getJob as jest.Mock)
      .mockResolvedValueOnce({ id: "job-1", status: "downloading" })
      .mockResolvedValueOnce({ id: "job-1", status: "separating_stems" })
      .mockResolvedValueOnce({ id: "job-1", status: "transcribing" })
      .mockResolvedValueOnce({ id: "job-1", status: "mapping_tempo", event_count: 1 })
      .mockResolvedValueOnce({
        id: "job-1",
        status: "tempo_mapped",
        event_count: 1,
        tempo_bpm: 120,
      });
    (getAnalysis as jest.Mock).mockResolvedValue({
      tempo_bpm: 120,
      events: [{ id: "e1", time: 0, instrument: "kick", measure: 1, beat: 1, subdivision: 0 }],
    });

    render(<JobForm apiBaseUrl="http://localhost:8000" />);

    fireEvent.change(screen.getByLabelText(/youtube url/i), {
      target: { value: "https://youtu.be/dQw4w9WgXcQ" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate drum score/i }));
    await act(async () => {});
    expect(screen.getByText(/queued/i)).toBeInTheDocument();

    for (let i = 0; i < 5; i++) {
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
    }

    expect(getAnalysis).toHaveBeenCalledWith("http://localhost:8000", "job-1");

    // Player's audio load is pure promise chaining (fetch -> decode), not
    // timer-driven, so real timers + findBy*'s built-in retrying is the
    // reliable way to wait for it from here.
    jest.useRealTimers();

    const playButton = await screen.findByRole("button", { name: /play/i });
    expect(screen.getByLabelText(/master volume/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/drums volume/i)).toBeInTheDocument();

    const scoreContainer = screen.getByTestId("drum-score");
    expect(scoreContainer.querySelector("svg")).not.toBeNull();
    expect(scoreContainer.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);

    fireEvent.click(playButton);
    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();
  });
});
