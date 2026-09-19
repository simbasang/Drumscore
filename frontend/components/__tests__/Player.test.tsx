import { act, fireEvent, render, screen } from "@testing-library/react";

import { loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { SyncedPlayer } from "@/lib/audio/SyncedPlayer";
import Player from "../Player";

jest.mock("@/lib/audio/loadAudioBuffer");
jest.mock("@/lib/audio/SyncedPlayer");
jest.mock("@/components/DrumScore", () => {
  return function MockDrumScore({ currentTime }: { currentTime?: number }) {
    return <div data-testid="drum-score-mock" data-current-time={currentTime} />;
  };
});

const MockedSyncedPlayer = SyncedPlayer as jest.MockedClass<typeof SyncedPlayer>;

function fakeContextFactory() {
  return { close: jest.fn() } as never;
}

describe("Player", () => {
  let rafCallback: FrameRequestCallback | null;

  beforeEach(() => {
    jest.clearAllMocks();
    rafCallback = null;
    (loadAudioBuffer as jest.Mock).mockResolvedValue({ duration: 30 });
    MockedSyncedPlayer.prototype.getCurrentTime = jest.fn().mockReturnValue(0);
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
        tempoBpm={120}
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
        tempoBpm={120}
        createAudioContext={fakeContextFactory}
      />,
    );

    unmount();
    await act(async () => {
      resolveLoad({ duration: 30 });
    });

    expect(MockedSyncedPlayer).not.toHaveBeenCalled();
  });

  it("should close its AudioContext on unmount so contexts don't leak across job resubmissions", async () => {
    const closeContext = jest.fn();
    const fakeContext = { close: closeContext };

    const { unmount } = render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
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
        tempoBpm={120}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/drums volume/i), { target: { value: "0" } });

    expect(playerInstance.setDrumsVolume).toHaveBeenCalledWith(0);
  });
});
