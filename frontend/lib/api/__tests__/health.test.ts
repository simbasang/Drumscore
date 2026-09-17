import { getBackendHealth } from "../health";

describe("getBackendHealth", () => {
  it("should return the parsed status from the backend health endpoint", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "ok" }),
    } as Response);

    const result = await getBackendHealth("http://localhost:8000");

    expect(result).toEqual({ status: "ok" });
    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/api/health");
  });

  it("should throw when the backend responds with a non-ok status", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
    } as Response);

    await expect(getBackendHealth("http://localhost:8000")).rejects.toThrow(
      "Backend health check failed",
    );
  });
});
