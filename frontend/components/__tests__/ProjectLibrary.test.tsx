import { act, fireEvent, render, screen } from "@testing-library/react";

import { deleteProject, listProjects } from "@/lib/api/projects";
import ProjectLibrary from "../ProjectLibrary";

jest.mock("@/lib/api/projects");

const BASE = "http://localhost:8000";

function item(id: string, title: string, status: string | null, hasEdits = false) {
  return { id, title, source_url: "u", updated_at: "", latest_job_status: status, has_edits: hasEdits };
}

describe("ProjectLibrary", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("should list projects with links, status and edit marker", async () => {
    (listProjects as jest.Mock).mockResolvedValue([
      item("p1", "Song A", "completed", true),
      item("p2", "Song B", "transcribing"),
      item("p3", "Song C", "failed"),
      item("p4", "Song D", null),
    ]);

    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    expect(screen.getByRole("link", { name: "Song A" })).toHaveAttribute("href", "/projects/p1");
    expect(screen.getByText(/Ready/)).toBeInTheDocument();
    expect(screen.getByText(/edited/)).toBeInTheDocument();
    expect(screen.getByText(/Processing/)).toBeInTheDocument();
    expect(screen.getByText(/Failed/)).toBeInTheDocument();
  });

  it("should show a loading state and then an empty state", async () => {
    (listProjects as jest.Mock).mockResolvedValue([]);

    render(<ProjectLibrary apiBaseUrl={BASE} />);

    expect(screen.getByText("Loading projects...")).toBeInTheDocument();
    await act(async () => {});
    expect(screen.getByText(/No projects yet/)).toBeInTheDocument();
  });

  it("should show an error when the list cannot be loaded", async () => {
    (listProjects as jest.Mock).mockRejectedValue(new Error("offline"));

    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("offline");
  });

  it("should show a generic error when the list fails with a non-Error value", async () => {
    (listProjects as jest.Mock).mockRejectedValue("nope");

    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to load projects.");
  });

  it("should ignore a successful load after unmounting", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);

    const { unmount } = render(<ProjectLibrary apiBaseUrl={BASE} />);
    unmount();
    await act(async () => {});

    expect(listProjects).toHaveBeenCalledWith(BASE);
  });

  it("should ignore a failed load after unmounting", async () => {
    (listProjects as jest.Mock).mockRejectedValue(new Error("offline"));

    const { unmount } = render(<ProjectLibrary apiBaseUrl={BASE} />);
    unmount();
    await act(async () => {});

    expect(listProjects).toHaveBeenCalledWith(BASE);
  });

  it("should delete a project after confirmation", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    (deleteProject as jest.Mock).mockResolvedValue(undefined);
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));
    await act(async () => {});

    expect(deleteProject).toHaveBeenCalledWith(BASE, "p1");
    expect(screen.queryByRole("link", { name: "Song A" })).not.toBeInTheDocument();
  });

  it("should keep the project when deletion is not confirmed", async () => {
    (window.confirm as jest.Mock).mockReturnValue(false);
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));

    expect(deleteProject).not.toHaveBeenCalled();
  });

  it("should show an error when deletion fails", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    (deleteProject as jest.Mock).mockRejectedValue(new Error("Project not found"));
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("Project not found");
  });

  it("should show a generic error when deletion fails with a non-Error value", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    (deleteProject as jest.Mock).mockRejectedValue("nope");
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to delete project.");
  });
});
