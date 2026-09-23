import { act, fireEvent, render, screen } from "@testing-library/react";

import { loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { SyncedPlayer } from "@/lib/audio/SyncedPlayer";
import Player from "../Player";

jest.mock("@/lib/audio/loadAudioBuffer");
jest.mock("@/lib/audio/SyncedPlayer");
jest.mock("@/components/DrumScore", () => {
  return function MockDrumScore({
    currentTime,
    onSeek,
  }: {
    currentTime?: number;
    onSeek?: (time: number) => void;
  }) {
    return (
      <div data-testid="drum-score-mock" data-current-time={currentTime}>
        <button type="button" onClick={() => onSeek?.(12.5)}>
          mock-seek
        </button>
      </div>
    );
  };
});

const MockedSyncedPlayer = SyncedPlayer as jest.MockedClass<typeof SyncedPlayer>;

function fakeContextFactory() {
  return { close: jest.fn() } as never;
}

function fakeContextFactoryWithOscillator() {
  return {
    close: jest.fn(),
    currentTime: 0,
    destination: {},
    createGain: () => ({ gain: { value: 1 }, connect: jest.fn() }),
    createOscillator: () => ({ frequency: { value: 0 }, connect: jest.fn(), start: jest.fn(), stop: jest.fn() }),
  } as never;
}

describe("Player", () => {
  let rafCallback: FrameRequestCallback | null;

  beforeEach(() => {
    jest.clearAllMocks();
    rafCallback = null;
    (loadAudioBuffer as jest.Mock).mockResolvedValue({ duration: 30 });
    MockedSyncedPlayer.prototype.getCurrentTime = jest.fn().mockReturnValue(0);
    MockedSyncedPlayer.prototype.getPlaybackRate = jest.fn().mockReturnValue(1);
    jest.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });
    jest.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  });

  it("should show a loading state while audio is being fetched and decoded", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    expect(screen.getByText(/loading audio/i)).toBeInTheDocument();

    await screen.findByRole("button", { name: /play/i });
  });

  it("should ignore an in-flight audio load that resolves after unmount", async () => {
    let resolveLoad!: (value: { duration: number }) => void;
    (loadAudioBuffer as jest.Mock).mockReturnValue(
      new Promise((resolve) => {
        resolveLoad = resolve;
      }),
    );

    const { unmount } = render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    unmount();
    await act(async () => {
      resolveLoad({ duration: 30 });
    });

    expect(MockedSyncedPlayer).not.toHaveBeenCalled();
  });

  it("should not surface an error when an in-flight audio load rejects after unmount", async () => {
    const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    let rejectLoad!: (reason: unknown) => void;
    (loadAudioBuffer as jest.Mock).mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectLoad = reject;
      }),
    );

    const { unmount } = render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    unmount();
    await act(async () => {
      // Shaped like the AbortError a dev-only Fast Refresh/Strict Mode
      // remount can produce - see
      // docs/superpowers/plans/2026-09-20-abort-error-investigation.md.
      rejectLoad(new DOMException("The operation was aborted.", "AbortError"));
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });

  it("should close its AudioContext on unmount so contexts don't leak across job resubmissions", async () => {
    const closeContext = jest.fn();
    const fakeContext = { close: closeContext };

    const { unmount } = render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={() => fakeContext as never}
      />,
    );

    await screen.findByRole("button", { name: /play/i });
    unmount();

    expect(closeContext).toHaveBeenCalledTimes(1);
  });

  it("should show playback controls once audio has loaded", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    expect(await screen.findByRole("button", { name: /play/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/seek/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/master volume/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/drums volume/i)).toBeInTheDocument();
  });

  it("should show an error message when audio fails to load", async () => {
    const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    (loadAudioBuffer as jest.Mock).mockRejectedValue(new Error("network error"));

    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/failed to load audio/i);

    consoleErrorSpy.mockRestore();
  });

  it("should log the underlying error and job id when audio fails to load", async () => {
    const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    const loadError = new Error("network error");
    (loadAudioBuffer as jest.Mock).mockRejectedValue(loadError);

    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/failed to load audio/i);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      expect.stringContaining("job-1"),
      loadError,
    );

    consoleErrorSpy.mockRestore();
  });

  it("should play, run a raf tick, and update the drum score's currentTime", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    const playButton = await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(2.5);

    fireEvent.click(playButton);

    expect(playerInstance.play).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();

    act(() => {
      rafCallback?.(0);
    });

    expect(screen.getByTestId("drum-score-mock")).toHaveAttribute("data-current-time", "2.5");
  });

  it("should flip back to a Play button when the player stops itself at the end of the track", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    const playButton = await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];
    fireEvent.click(playButton);
    await screen.findByRole("button", { name: /pause/i });

    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(30);
    (playerInstance as unknown as { isPlaying: boolean }).isPlaying = false;
    act(() => {
      rafCallback?.(0);
    });

    expect(await screen.findByRole("button", { name: /play/i })).toBeInTheDocument();
  });

  it("should seek by calling player.seek with the slider value", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/seek/i), { target: { value: "15" } });

    expect(playerInstance.seek).toHaveBeenCalledWith(15);
  });

  it("should set master volume by calling player.setMasterVolume with a 0-1 value", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/master volume/i), { target: { value: "50" } });

    expect(playerInstance.setMasterVolume).toHaveBeenCalledWith(0.5);
  });

  it("should set drums volume by calling player.setDrumsVolume with a 0-1 value", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/drums volume/i), { target: { value: "0" } });

    expect(playerInstance.setDrumsVolume).toHaveBeenCalledWith(0);
  });

  it("should call player.seek when DrumScore's onSeek fires", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.click(screen.getByRole("button", { name: "mock-seek" }));

    expect(playerInstance.seek).toHaveBeenCalledWith(12.5);
  });

  it("should set a loop range on the transport when start and end are captured", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(3);

    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(9);
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    act(() => {
      rafCallback?.(0);
    });

    expect(screen.getByRole("button", { name: /clear loop/i })).toBeInTheDocument();
  });

  it("should clear the loop when Clear loop is clicked", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    fireEvent.click(screen.getByRole("button", { name: /clear loop/i }));

    expect(screen.queryByRole("button", { name: /clear loop/i })).not.toBeInTheDocument();
  });

  it("should set playback rate by calling player.setPlaybackRate when the speed select changes", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/playback speed/i), { target: { value: "1.5" } });

    expect(playerInstance.setPlaybackRate).toHaveBeenCalledWith(1.5);
  });

  it("should add a manually-created hit to the score when the add-hit form is submitted", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    expect(screen.getByTestId("drum-score-mock")).toBeInTheDocument();
  });

  it("should enable the undo button only after an edit has been made", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    expect(screen.getByRole("button", { name: /undo/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    expect(screen.getByRole("button", { name: /undo/i })).not.toBeDisabled();
  });

  it("should toggle the metronome checkbox on click", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByLabelText(/metronome/i));

    expect(screen.getByLabelText(/metronome/i)).toBeChecked();
  });

  it("should start playback via count-in when the Count-in button is clicked", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        beats={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByRole("button", { name: /count-in/i }));

    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();
  });
});
