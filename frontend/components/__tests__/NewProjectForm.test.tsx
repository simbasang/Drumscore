import { act, fireEvent, render, screen } from "@testing-library/react";
import * as navigation from "next/navigation";

import { createProject, DuplicateProjectError } from "@/lib/api/projects";
import NewProjectForm from "../NewProjectForm";

jest.mock("next/navigation");
jest.mock("@/lib/api/projects");

const mockPush = (navigation as unknown as { mockPush: jest.Mock }).mockPush;
const BASE = "http://localhost:8000";

async function submit(url: string) {
  fireEvent.change(screen.getByLabelText(/youtube url/i), { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: /generate drum score/i }));
  await act(async () => {});
}

describe("NewProjectForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("should create a project and open it", async () => {
    (createProject as jest.Mock).mockResolvedValue({ project: { id: "p1" }, job: { id: "j1" } });
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("  https://youtu.be/x  ");

    expect(createProject).toHaveBeenCalledWith(BASE, "https://youtu.be/x", { force: false });
    expect(mockPush).toHaveBeenCalledWith("/projects/p1");
  });

  it("should ask for a URL when the field is empty", async () => {
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("   ");

    expect(screen.getByRole("alert")).toHaveTextContent("Please enter a YouTube URL.");
    expect(createProject).not.toHaveBeenCalled();
  });

  it("should show the backend error", async () => {
    (createProject as jest.Mock).mockRejectedValue(new Error("'x' is not a supported YouTube URL"));
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("x");

    expect(screen.getByRole("alert")).toHaveTextContent("'x' is not a supported YouTube URL");
  });

  it("should show a generic error for non-Error failures", async () => {
    (createProject as jest.Mock).mockRejectedValue("nope");
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("https://youtu.be/x");

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to create project.");
  });

  it("should offer to open the existing project for a duplicate song", async () => {
    (createProject as jest.Mock).mockRejectedValue(new DuplicateProjectError("exists", "p-old"));
    render(<NewProjectForm apiBaseUrl={BASE} />);
    await submit("https://youtu.be/x");

    fireEvent.click(screen.getByRole("button", { name: "Open existing" }));

    expect(screen.getByRole("dialog", { name: "Song already processed" })).toBeInTheDocument();
    expect(mockPush).toHaveBeenCalledWith("/projects/p-old");
  });

  it("should process a duplicate anyway when asked", async () => {
    (createProject as jest.Mock)
      .mockRejectedValueOnce(new DuplicateProjectError("exists", "p-old"))
      .mockResolvedValueOnce({ project: { id: "p-new" }, job: { id: "j2" } });
    render(<NewProjectForm apiBaseUrl={BASE} />);
    await submit("https://youtu.be/x");

    fireEvent.click(screen.getByRole("button", { name: "Process anyway" }));
    await act(async () => {});

    expect(createProject).toHaveBeenLastCalledWith(BASE, "https://youtu.be/x", { force: true });
    expect(mockPush).toHaveBeenCalledWith("/projects/p-new");
  });
});
