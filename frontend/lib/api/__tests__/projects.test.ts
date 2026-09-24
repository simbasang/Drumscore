import {
  audioUrl,
  createProject,
  deleteProject,
  DuplicateProjectError,
  getAnalysis,
  getProject,
  getSavedScore,
  listProjects,
  NotFoundError,
  retryProject,
  saveScore,
  ScoreConflictError,
} from "../projects";

const BASE = "http://localhost:8000";

function respond(status: number, body?: unknown) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: body === undefined ? () => Promise.reject(new Error("no body")) : () => Promise.resolve(body),
  } as Response);
}

describe("createProject", () => {
  it("should post the URL and return the created project", async () => {
    respond(201, { project: { id: "p1" }, job: { id: "j1", status: "queued" } });

    const result = await createProject(BASE, "https://youtu.be/x");

    expect(result.project.id).toBe("p1");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://youtu.be/x" }),
    });
  });

  it("should add the force flag when asked", async () => {
    respond(201, { project: { id: "p2" }, job: { id: "j2" } });

    await createProject(BASE, "https://youtu.be/x", { force: true });

    expect((global.fetch as jest.Mock).mock.calls[0][0]).toBe(`${BASE}/api/projects?force=true`);
  });

  it("should throw a DuplicateProjectError carrying the existing project id", async () => {
    respond(409, { detail: "A project for this song already exists", existing_project_id: "p1" });

    const error = await createProject(BASE, "https://youtu.be/x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DuplicateProjectError);
    expect((error as DuplicateProjectError).existingProjectId).toBe("p1");
  });

  it("should throw the backend detail for other errors", async () => {
    respond(422, { detail: "'x' is not a supported YouTube URL" });

    await expect(createProject(BASE, "x")).rejects.toThrow("'x' is not a supported YouTube URL");
  });
});

describe("listProjects", () => {
  it("should return the project list", async () => {
    respond(200, [{ id: "p1", title: "Song" }]);

    const result = await listProjects(BASE);

    expect(result).toEqual([{ id: "p1", title: "Song" }]);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects`);
  });
});

describe("getProject", () => {
  it("should return the project", async () => {
    respond(200, { id: "p1", latest_job: { status: "completed" } });

    const result = await getProject(BASE, "p1");

    expect(result.latest_job?.status).toBe("completed");
  });

  it("should throw NotFoundError on 404", async () => {
    respond(404, { detail: "Project not found" });

    await expect(getProject(BASE, "p1")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("should fall back to a generic message when the error body is not JSON", async () => {
    respond(500);

    await expect(getProject(BASE, "p1")).rejects.toThrow("Request failed (500)");
  });
});

describe("deleteProject", () => {
  it("should send DELETE and resolve on 204", async () => {
    respond(204);

    await deleteProject(BASE, "p1");

    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1`, { method: "DELETE" });
  });

  it("should throw when deletion fails", async () => {
    respond(404, { detail: "Project not found" });

    await expect(deleteProject(BASE, "p1")).rejects.toBeInstanceOf(NotFoundError);
  });
});

describe("retryProject", () => {
  it("should post to the retry endpoint", async () => {
    respond(202, { id: "j1", status: "queued" });

    const result = await retryProject(BASE, "p1");

    expect(result.status).toBe("queued");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/retry`, { method: "POST" });
  });
});

describe("getAnalysis", () => {
  it("should fetch the project analysis", async () => {
    respond(200, { tempo_bpm: 120, events: [], beats: [] });

    const result = await getAnalysis(BASE, "p1");

    expect(result.tempo_bpm).toBe(120);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/analysis`);
  });
});

describe("getSavedScore", () => {
  it("should return the saved score", async () => {
    respond(200, { version: 3, score: { measures: [] } });

    const result = await getSavedScore(BASE, "p1");

    expect(result).toEqual({ version: 3, score: { measures: [] } });
  });

  it("should return null when nothing was saved", async () => {
    respond(404, { detail: "No saved score for this project" });

    const result = await getSavedScore(BASE, "p1");

    expect(result).toBeNull();
  });
});

describe("saveScore", () => {
  it("should put the score with its base version and return the new version", async () => {
    respond(201, { version: 2 });

    const version = await saveScore(BASE, "p1", { measures: [] }, 1);

    expect(version).toBe(2);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/score`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ score: { measures: [] }, base_version: 1 }),
    });
  });

  it("should throw ScoreConflictError with the latest version on 409", async () => {
    respond(409, { detail: "A newer version of this score was saved elsewhere", latest_version: 4 });

    const error = await saveScore(BASE, "p1", { measures: [] }, 1).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ScoreConflictError);
    expect((error as ScoreConflictError).latestVersion).toBe(4);
  });

  it("should default the latest version to null when the conflict body lacks it", async () => {
    respond(409, {});

    const error = await saveScore(BASE, "p1", { measures: [] }, null).catch((e: unknown) => e);

    expect((error as ScoreConflictError).latestVersion).toBeNull();
  });
});

describe("audioUrl", () => {
  it("should build the stem URL", () => {
    expect(audioUrl(BASE, "p1", "drums")).toBe(`${BASE}/api/projects/p1/audio/drums`);
  });
});
