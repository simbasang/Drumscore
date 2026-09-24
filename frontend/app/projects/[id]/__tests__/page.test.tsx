import { render, screen } from "@testing-library/react";

import ProjectPage from "../page";

jest.mock("@/components/ProjectView", () => {
  return function MockProjectView({ apiBaseUrl, projectId }: { apiBaseUrl: string; projectId: string }) {
    return <div data-testid="project-view" data-api-base-url={apiBaseUrl} data-project-id={projectId} />;
  };
});

describe("ProjectPage", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.API_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it("should render the project view for the route id", async () => {
    render(await ProjectPage({ params: Promise.resolve({ id: "p1" }) }));

    expect(screen.getByTestId("project-view")).toHaveAttribute("data-project-id", "p1");
    expect(screen.getByTestId("project-view")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
  });

  it("should pass the runtime API_URL to the project view", async () => {
    process.env.API_URL = "https://api.drums.example";

    render(await ProjectPage({ params: Promise.resolve({ id: "p1" }) }));

    expect(screen.getByTestId("project-view")).toHaveAttribute("data-api-base-url", "https://api.drums.example");
  });

  it("should link back to the project library", async () => {
    render(await ProjectPage({ params: Promise.resolve({ id: "p1" }) }));

    expect(screen.getByRole("link", { name: /all projects/i })).toHaveAttribute("href", "/");
  });
});
