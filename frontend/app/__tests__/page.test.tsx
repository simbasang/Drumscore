import { render, screen } from "@testing-library/react";

import Home from "../page";

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
  it("should render the page heading and description", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /drumscore/i })).toBeInTheDocument();
    expect(screen.getByText(/generate playable drum notation/i)).toBeInTheDocument();
  });

  it("should render the submit form and the library with the configured API base URL", () => {
    render(<Home />);

    expect(screen.getByTestId("new-project-form")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
    expect(screen.getByTestId("project-library")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
  });
});
