import { createJob, getAnalysis, getJob } from "../jobs";

describe("createJob", () => {
  it("should return the created job when the backend accepts the URL", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ id: "job-1", url: "https://youtu.be/dQw4w9WgXcQ", status: "queued" }),
    } as Response);

    const result = await createJob("http://localhost:8000", "https://youtu.be/dQw4w9WgXcQ");

    expect(result).toEqual({ id: "job-1", url: "https://youtu.be/dQw4w9WgXcQ", status: "queued" });
    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://youtu.be/dQw4w9WgXcQ" }),
    });
  });

  it("should throw the backend's error detail when the URL is rejected", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "'x' is not a supported YouTube URL" }),
    } as Response);

    await expect(createJob("http://localhost:8000", "x")).rejects.toThrow(
      "'x' is not a supported YouTube URL",
    );
  });
});

describe("getJob", () => {
  it("should return the current job state", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "job-1",
          url: "https://youtu.be/dQw4w9WgXcQ",
          status: "separating_stems",
        }),
    } as Response);

    const result = await getJob("http://localhost:8000", "job-1");

    expect(result).toEqual({
      id: "job-1",
      url: "https://youtu.be/dQw4w9WgXcQ",
      status: "separating_stems",
    });
    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/jobs/job-1");
  });

  it("should throw when the job cannot be found", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "Job not found" }),
    } as Response);

    await expect(getJob("http://localhost:8000", "missing")).rejects.toThrow("Job not found");
  });
});

describe("getAnalysis", () => {
  it("should return tempo and events", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          tempo_bpm: 128.0,
          events: [
            { id: "e1", time: 0.5, instrument: "kick", measure: 1, beat: 2, subdivision: 0 },
          ],
        }),
    } as Response);

    const result = await getAnalysis("http://localhost:8000", "job-1");

    expect(result).toEqual({
      tempo_bpm: 128.0,
      events: [{ id: "e1", time: 0.5, instrument: "kick", measure: 1, beat: 2, subdivision: 0 }],
    });
    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/jobs/job-1/analysis");
  });

  it("should throw when the analysis is not ready yet", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "Analysis not available yet: job status is queued" }),
    } as Response);

    await expect(getAnalysis("http://localhost:8000", "job-1")).rejects.toThrow(
      "Analysis not available yet: job status is queued",
    );
  });
});
