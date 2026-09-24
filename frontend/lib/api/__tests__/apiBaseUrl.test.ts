import { getApiBaseUrl } from "../apiBaseUrl";

describe("getApiBaseUrl", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.API_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it("should prefer the runtime API_URL", () => {
    process.env.API_URL = "https://api.drums.example";
    process.env.NEXT_PUBLIC_API_URL = "http://build-time.example";

    const result = getApiBaseUrl();

    expect(result).toBe("https://api.drums.example");
  });

  it("should fall back to NEXT_PUBLIC_API_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://build-time.example";

    const result = getApiBaseUrl();

    expect(result).toBe("http://build-time.example");
  });

  it("should default to the local development API", () => {
    const result = getApiBaseUrl();

    expect(result).toBe("http://localhost:8000");
  });
});
