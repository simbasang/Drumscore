import { act, fireEvent, render, screen } from "@testing-library/react";

import { getAnalysis, getProject, getSavedScore, NotFoundError, retryProject, saveScore } from "@/lib/api/projects";
import ProjectView from "../ProjectView";

jest.mock("@/lib/api/projects");
jest.mock("@/components/Player", () => {
  return function MockPlayer({
    projectId,
    events,
    initialScore,
    onSave,
  }: {
    projectId: string;
    events: unknown[];
    initialScore: unknown;
    onSave: (score: unknown) => Promise<void>;
  }) {
    return (
      <div data-testid="player" data-project-id={projectId} data-events={events.length} data-initial={JSON.stringify(initialScore)}>
        <button type="button" onClick={() => void onSave({ measures: [["edited"]] })}>
          mock-save
        </button>
      </div>
    );
  };
});

const BASE = "http://localhost:8000";
const ANALYSIS = { tempo_bpm: 120, events: [{ id: "e1" }], beats: [] };

function project(status: string, error: string | null = null) {
  return { id: "p1", title: "My Song", source_url: "u", created_at: "", updated_at: "", latest_job: { id: "j1", status, attempts: 1, max_attempts: 3, error, created_at: "", finished_at: null } };
}

async function flush() {
  await act(async () => {});
}

async function tick() {
  await act(async () => {
    jest.advanceTimersByTime(2000);
  });
}

describe("ProjectView", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("should show progress while processing and the player once completed", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("separating_stems"))
      .mockResolvedValueOnce(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue(null);

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("heading", { name: "My Song" })).toBeInTheDocument();
    expect(screen.getByText("Separating drum stems...")).toBeInTheDocument();

    await tick();

    const player = await screen.findByTestId("player");
    expect(player).toHaveAttribute("data-events", "1");
    expect(player).toHaveAttribute("data-initial", "null");
  });

  it("should load the saved score instead of rebuilding from the analysis", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue({ version: 4, score: { measures: [["saved"]] } });

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(await screen.findByTestId("player")).toHaveAttribute("data-initial", JSON.stringify({ measures: [["saved"]] }));
  });

  it("should save with the loaded version and then with the returned one", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue({ version: 4, score: { measures: [] } });
    (saveScore as jest.Mock).mockResolvedValueOnce(5).mockResolvedValueOnce(6);
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();
    const save = await screen.findByRole("button", { name: "mock-save" });

    fireEvent.click(save);
    await flush();
    fireEvent.click(save);
    await flush();

    expect(saveScore).toHaveBeenNthCalledWith(1, BASE, "p1", { measures: [["edited"]] }, 4);
    expect(saveScore).toHaveBeenNthCalledWith(2, BASE, "p1", { measures: [["edited"]] }, 5);
  });

  it("should show the failure and requeue on retry", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("failed", "video unavailable"))
      .mockResolvedValueOnce(project("queued"));
    (retryProject as jest.Mock).mockResolvedValue({ id: "j1", status: "queued" });
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("video unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Retry processing" }));
    await flush();

    expect(retryProject).toHaveBeenCalledWith(BASE, "p1");
    expect(screen.getByText("Queued, waiting for a worker...")).toBeInTheDocument();
  });

  it("should show an error when the retry request fails", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("failed", "boom"));
    (retryProject as jest.Mock).mockRejectedValue(new Error("Only a failed job can be retried"));
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    fireEvent.click(screen.getByRole("button", { name: "Retry processing" }));
    await flush();

    expect(screen.getByText("Only a failed job can be retried")).toBeInTheDocument();
  });

  it("should show not found for a deleted or unknown project", async () => {
    (getProject as jest.Mock).mockRejectedValue(new NotFoundError("Project not found"));

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("Project not found");
  });

  it("should retry transient poll errors and give up after three in a row", async () => {
    (getProject as jest.Mock).mockRejectedValue(new Error("offline"));

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByText("Lost connection, retrying...")).toBeInTheDocument();

    await tick();
    await tick();

    expect(screen.getByRole("alert")).toHaveTextContent("Lost connection to the server");
    expect(getProject).toHaveBeenCalledTimes(3);
  });

  it("should show a load error when the analysis cannot be fetched", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockRejectedValue(new Error("Analysis not available yet"));
    (getSavedScore as jest.Mock).mockResolvedValue(null);

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("Analysis not available yet");
  });

  it("should stop polling after unmount", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("queued"));
    const { unmount } = render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    unmount();
    await tick();

    expect(getProject).toHaveBeenCalledTimes(1);
  });
});
