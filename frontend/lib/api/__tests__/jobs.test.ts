import { createJob } from "../jobs";

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
