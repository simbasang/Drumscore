import { render, screen } from "@testing-library/react";
import { connection } from "next/server";

import Home from "../page";

jest.mock("next/server");
jest.mock("@/components/NewProjectForm", () => {
  return function MockNewProjectForm({ apiBaseUrl }: { apiBaseUrl: string }) {
    return <div data-testid="new-project-form" data-api-base-url={apiBaseUrl} />;
  };
});
jest.mock("@/components/ProjectLibrary", () => {
  return function MockProjectLibrary({ apiBaseUrl }: { apiBaseUrl: string }) {
    return <div data-testid="project-library" data-api-base-url={apiBaseUrl} />;
  };
});

describe("Home", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.API_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it("should render the page heading and description", async () => {
    render(await Home());

    expect(screen.getByRole("heading", { name: /drumscore/i })).toBeInTheDocument();
    expect(screen.getByText(/generate playable drum notation/i)).toBeInTheDocument();
  });

  it("should render the submit form and the library with the default API base URL", async () => {
    render(await Home());

    expect(screen.getByTestId("new-project-form")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
    expect(screen.getByTestId("project-library")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
  });

  it("should pass the runtime API_URL to the form and the library", async () => {
    process.env.API_URL = "https://api.drums.example";

    render(await Home());

    expect(screen.getByTestId("new-project-form")).toHaveAttribute("data-api-base-url", "https://api.drums.example");
    expect(screen.getByTestId("project-library")).toHaveAttribute("data-api-base-url", "https://api.drums.example");
  });

  it("should render per request so the API URL is not frozen at build time", async () => {
    render(await Home());

    expect(connection).toHaveBeenCalled();
  });
});
