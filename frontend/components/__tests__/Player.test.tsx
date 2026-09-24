import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ScoreConflictError } from "@/lib/api/projects";
import { loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { PracticeTransport } from "@/lib/audio/PracticeTransport";
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

  afterEach(() => {
    // Some tests spy on PracticeTransport.prototype methods directly (it's
    // real, not module-mocked, so the spy patches the shared prototype).
    // jest.clearAllMocks() (in beforeEach) resets call history but does not
    // call mockRestore(), so an un-restored spy would leak the patched
    // prototype method into later tests. restoreAllMocks() only affects
    // jest.spyOn()-created mocks, so it's safe alongside the module-level
    // jest.mock("@/lib/audio/SyncedPlayer") automock used throughout.
    jest.restoreAllMocks();
  });

  it("should show a loading state while audio is being fetched and decoded", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/failed to load audio/i);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      expect.stringContaining("project-1"),
      loadError,
    );

    consoleErrorSpy.mockRestore();
  });

  it("should play, run a raf tick, and update the drum score's currentTime", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
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
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    const playButton = await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    // handleSetLoopStart/End read the component's `currentTime` React state,
    // not the transport's live getCurrentTime() - so that state has to be
    // driven forward with real tick() calls (as playback would) before
    // capturing loop points, exactly as it would happen during real
    // playback. Clicking Play first also captures a real rafCallback.
    fireEvent.click(playButton);

    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(3);
    act(() => {
      rafCallback?.(0);
    });
    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));

    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(9);
    act(() => {
      rafCallback?.(0);
    });
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    expect(screen.getByRole("button", { name: /clear loop/i })).toBeInTheDocument();

    // At (or past) the loop end, ticking the real PracticeTransport must
    // restart playback at the loop's start time - proving the loop is
    // functionally wired up end-to-end, not just that the UI shows a
    // "Clear loop" button.
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(9);
    act(() => {
      rafCallback?.(0);
    });

    expect(playerInstance.seek).toHaveBeenCalledWith(3);
  });

  it("should not wedge the transport when loop start and end are captured at the same currentTime", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    const playButton = await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    // currentTime hasn't advanced (still 0, paused) - capturing loop start
    // then immediately loop end yields a zero-length {0, 0} range. Without
    // a minimum-length guard, every subsequent tick would see
    // currentTime >= endTime and call player.seek() again, wedging the
    // transport in a seek loop.
    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    expect(screen.queryByRole("button", { name: /clear loop/i })).not.toBeInTheDocument();

    fireEvent.click(playButton);
    act(() => {
      rafCallback?.(0);
    });

    expect(playerInstance.seek).not.toHaveBeenCalled();
  });

  it("should clear the loop when Clear loop is clicked", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    const playButton = await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    // Loop start/end must be captured at different currentTime values -
    // otherwise the zero-length-range guard (see the "should not wedge the
    // transport" test) discards it and "Clear loop" never appears.
    fireEvent.click(playButton);
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(3);
    act(() => {
      rafCallback?.(0);
    });
    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));

    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(9);
    act(() => {
      rafCallback?.(0);
    });
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    fireEvent.click(screen.getByRole("button", { name: /clear loop/i }));

    expect(screen.queryByRole("button", { name: /clear loop/i })).not.toBeInTheDocument();
  });

  it("should set playback rate by calling player.setPlaybackRate when the speed select changes", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
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
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const hitSelect = screen.getByLabelText(/select hit to edit/i);

    expect(within(hitSelect).queryAllByRole("option")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    // useScoreEditor is not mocked in this file, so a real assertion here
    // (a new option reflecting the added hit's position) genuinely exercises
    // the addHit path, rather than just checking DrumScore rendered - which
    // it always does regardless of whether the add worked.
    const options = within(hitSelect).getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[1].textContent).toMatch(/m1 b1\.0/);
  });

  it("should enable the undo button only after an edit has been made", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    expect(screen.getByRole("button", { name: /undo/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    expect(screen.getByRole("button", { name: /undo/i })).not.toBeDisabled();
  });

  it("should clear a stale selectedHitId (and disable its dependent buttons) after undo removes the selected hit", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const hitSelect = screen.getByLabelText(/select hit to edit/i);

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));
    const addedOption = within(hitSelect).getAllByRole("option")[1];
    fireEvent.change(hitSelect, { target: { value: addedOption.getAttribute("value") } });

    expect(screen.getByRole("button", { name: /delete hit/i })).not.toBeDisabled();

    // Undo removes the hit that's currently selected - selectedHitId now
    // points at a hit that no longer exists in the score.
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));

    expect(hitSelect).toHaveValue("");
    expect(screen.getByRole("button", { name: /delete hit/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /change instrument/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^move hit$/i })).toBeDisabled();
  });

  it("should toggle the metronome checkbox on click", async () => {
    // PracticeTransport is real (only SyncedPlayer is mocked), so this spy
    // wraps the actual instance method - proving the checkbox really drives
    // the transport, not just its own displayed checked state. Beat data is
    // required here since the checkbox is now disabled when beats is empty.
    const setMetronomeEnabledSpy = jest.spyOn(PracticeTransport.prototype, "setMetronomeEnabled");
    const beats = [{ source_time: 0, measure: 1, beat: 1, is_downbeat: true, confidence: 1 }];

    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        beats={beats}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByLabelText(/metronome/i));

    expect(screen.getByLabelText(/metronome/i)).toBeChecked();
    expect(setMetronomeEnabledSpy).toHaveBeenCalledWith(true);
  });

  it("should disable the metronome checkbox when no beat data is available for the job", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        beats={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    expect(screen.getByLabelText(/metronome/i)).toBeDisabled();
  });

  it("should start playback via count-in when the Count-in button is clicked", async () => {
    // playWithCountIn is real (PracticeTransport is not module-mocked), so
    // this spy proves handleCountInPlay actually calls the count-in path
    // and not plain play() - which would also flip the button to "Pause".
    const playWithCountInSpy = jest.spyOn(PracticeTransport.prototype, "playWithCountIn");

    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        beats={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByRole("button", { name: /count-in/i }));

    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();
    expect(playWithCountInSpy).toHaveBeenCalled();
  });

  it("should disable Count-in while already playing, not just while counting in", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    const playButton = await screen.findByRole("button", { name: /play/i });

    fireEvent.click(playButton);

    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /count-in/i })).toBeDisabled();
  });

  it("should disable Play/Pause and Count-in while a count-in is pending, so a click can't start overlapping playback", async () => {
    // Two beats give countInClickTimes a non-zero period, so playWithCountIn
    // schedules a real setTimeout instead of calling play() synchronously -
    // this is the genuine "pending count-in" window the fix must guard.
    // Fake timers (matching PracticeTransport.test.ts's own pattern for its
    // count-in tests) keep that scheduled timer from ever firing past this
    // test, since it's never advanced or otherwise cleaned up here - a real
    // timer firing during a later test could surface as a stray act()
    // warning.
    jest.useFakeTimers();
    try {
      const beats = [
        { source_time: 0, measure: 1, beat: 1, is_downbeat: true, confidence: 1 },
        { source_time: 0.5, measure: 1, beat: 2, is_downbeat: false, confidence: 1 },
      ];

      render(
        <Player
          apiBaseUrl="http://localhost:8000"
          projectId="project-1"
          events={[]}
          beats={beats}
          createAudioContext={fakeContextFactoryWithOscillator}
        />,
      );
      await screen.findByRole("button", { name: /play/i });

      fireEvent.click(screen.getByRole("button", { name: /count-in/i }));

      const playPauseButton = await screen.findByRole("button", { name: /pause/i });
      expect(playPauseButton).toBeDisabled();
      expect(screen.getByRole("button", { name: /count-in/i })).toBeDisabled();
    } finally {
      jest.useRealTimers();
    }
  });

  it("should not throw, and should never call play, when the component unmounts while a count-in is pending", async () => {
    jest.useFakeTimers();
    try {
      const startLength = MockedSyncedPlayer.mock.instances.length;
      const beats = [
        { source_time: 0, measure: 1, beat: 1, is_downbeat: true, confidence: 1 },
        { source_time: 0.5, measure: 1, beat: 2, is_downbeat: false, confidence: 1 },
      ];

      const { unmount } = render(
        <Player
          apiBaseUrl="http://localhost:8000"
          projectId="project-1"
          events={[]}
          beats={beats}
          createAudioContext={fakeContextFactoryWithOscillator}
        />,
      );
      await screen.findByRole("button", { name: /play/i });
      const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

      fireEvent.click(screen.getByRole("button", { name: /count-in/i }));
      await screen.findByRole("button", { name: /pause/i });
      (playerInstance.play as jest.Mock).mockClear();

      // Unmounting before the count-in's setTimeout fires calls pause()
      // (via the load effect's cleanup) then closes the AudioContext. If
      // the pending count-in timer weren't cancelled, it would later call
      // play() -> startSources() -> context.createBufferSource() on an
      // already-closed context, throwing from inside a timer callback -
      // unrecoverable, outside any React error boundary.
      expect(() => unmount()).not.toThrow();

      expect(() => jest.advanceTimersByTime(10000)).not.toThrow();
      expect(playerInstance.play).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });

  describe("correction editor position inputs", () => {
    it("should clamp an out-of-range typed measure so adding a hit neither throws nor silently discards it", async () => {
      render(
        <Player
          apiBaseUrl="http://localhost:8000"
          projectId="project-1"
          events={[]}
          createAudioContext={fakeContextFactory}
        />,
      );
      await screen.findByRole("button", { name: /play/i });
      const hitSelect = screen.getByLabelText(/select hit to edit/i);

      fireEvent.change(screen.getByLabelText(/^add at measure$/i), { target: { value: "99" } });

      expect(screen.getByLabelText(/^add at measure$/i)).toHaveValue(1);

      expect(() => {
        fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));
      }).not.toThrow();

      const options = within(hitSelect).getAllByRole("option");
      expect(options).toHaveLength(2);
      expect(options[1].textContent).toMatch(/m1 b1\.0/);
    });

    it("should clamp an out-of-range typed beat so moving a hit neither throws nor exceeds beat 4", async () => {
      render(
        <Player
          apiBaseUrl="http://localhost:8000"
          projectId="project-1"
          events={[]}
          createAudioContext={fakeContextFactory}
        />,
      );
      await screen.findByRole("button", { name: /play/i });

      fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));
      const hitSelect = screen.getByLabelText(/select hit to edit/i);
      const addedOption = within(hitSelect).getAllByRole("option")[1];
      fireEvent.change(hitSelect, { target: { value: addedOption.getAttribute("value") } });

      fireEvent.change(screen.getByLabelText(/^move to beat$/i), { target: { value: "9" } });

      expect(screen.getByLabelText(/^move to beat$/i)).toHaveValue(4);

      expect(() => {
        fireEvent.click(screen.getByRole("button", { name: /^move hit$/i }));
      }).not.toThrow();

      const movedOptions = within(hitSelect).getAllByRole("option");
      expect(movedOptions[1].textContent).toMatch(/m1 b4\./);
    });
  });
});

describe("Player saving", () => {
  // This describe is a sibling of describe("Player", ...) above, not nested
  // inside it, so it does not inherit that block's beforeEach - set up the
  // same audio-resolves-successfully default here rather than relying on
  // the other describe's last beforeEach run leaking into this one.
  beforeEach(() => {
    jest.clearAllMocks();
    (loadAudioBuffer as jest.Mock).mockResolvedValue({ duration: 30 });
  });

  // Player renders only "Loading audio..." until its audio load effect
  // resolves, so every test below must wait for that before it can see the
  // Save button/controls - awaiting the Save button's appearance (present
  // whenever onSave is given) is the simplest reliable readiness signal.
  async function renderWithSave(onSave = jest.fn().mockResolvedValue(undefined), onReloadRequested = jest.fn()) {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
        onSave={onSave}
        onReloadRequested={onReloadRequested}
      />,
    );
    await screen.findByRole("button", { name: "Save" });
    return { onSave, onReloadRequested };
  }

  it("should not render save controls without an onSave handler", async () => {
    render(<Player apiBaseUrl="http://localhost:8000" projectId="project-1" events={[]} createAudioContext={fakeContextFactory} />);
    await screen.findByRole("button", { name: /play/i });

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("should load audio from the project's stem URLs", async () => {
    await renderWithSave();

    expect(loadAudioBuffer).toHaveBeenCalledWith("http://localhost:8000/api/projects/project-1/audio/drums", expect.anything());
    expect(loadAudioBuffer).toHaveBeenCalledWith("http://localhost:8000/api/projects/project-1/audio/accompaniment", expect.anything());
  });

  it("should disable Save until the score has unsaved changes", async () => {
    await renderWithSave();

    const save = screen.getByRole("button", { name: "Save" });

    expect(save).toBeDisabled();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("should save the edited score and show it as saved", async () => {
    const { onSave } = await renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ measures: expect.any(Array) }));
    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("should save with Ctrl+S", async () => {
    const { onSave } = await renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.keyDown(window, { key: "s", ctrlKey: true });

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });

  it("should ignore Ctrl+S when there is nothing to save", async () => {
    const { onSave } = await renderWithSave();

    fireEvent.keyDown(window, { key: "s", metaKey: true });
    fireEvent.keyDown(window, { key: "x", ctrlKey: true });

    expect(onSave).not.toHaveBeenCalled();
  });

  it("should warn before leaving the page with unsaved changes", async () => {
    await renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    const event = new Event("beforeunload", { cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("should not warn before leaving when everything is saved", async () => {
    await renderWithSave();
    const event = new Event("beforeunload", { cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("should show a save error and keep the changes unsaved", async () => {
    await renderWithSave(jest.fn().mockRejectedValue(new Error("Network down")));
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
  });

  it("should offer a reload when a newer version was saved elsewhere", async () => {
    const { onReloadRequested } = await renderWithSave(
      jest.fn().mockRejectedValue(new ScoreConflictError("A newer version was saved elsewhere", 3)),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    fireEvent.click(await screen.findByRole("button", { name: "Reload" }));

    expect(onReloadRequested).toHaveBeenCalled();
  });

  it("should use a generic message when a non-Error is thrown", async () => {
    await renderWithSave(jest.fn().mockRejectedValue("nope"));
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed.");
  });

  it("should start from the provided initial score", async () => {
    const initialScore = {
      measures: [[{ type: "note" as const, id: "n1", position: { measure: 1, beat: 1, subdivision: 0 }, duration: "w", hits: [{ id: "h1", sourceEventId: null, time: null, instrument: "snare" as const, confidence: null, provenance: "manual" }] }]],
    };

    render(<Player apiBaseUrl="http://localhost:8000" projectId="project-1" events={[]} createAudioContext={fakeContextFactory} initialScore={initialScore} />);
    const hitSelect = await screen.findByLabelText(/select hit to edit/i);

    expect(within(hitSelect).getByRole("option", { name: /snare/i })).toBeInTheDocument();
  });
});
