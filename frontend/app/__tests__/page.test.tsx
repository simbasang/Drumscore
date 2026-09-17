import { render, screen } from "@testing-library/react";

import Home from "../page";

jest.mock("@/components/JobForm", () => {
  return function MockJobForm({ apiBaseUrl }: { apiBaseUrl: string }) {
    return <div data-testid="job-form" data-api-base-url={apiBaseUrl} />;
  };
});

describe("Home", () => {
  it("should render the page heading and description", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /drumscore/i })).toBeInTheDocument();
    expect(screen.getByText(/generate playable drum notation/i)).toBeInTheDocument();
  });

  it("should render the job form with the configured API base URL", () => {
    render(<Home />);

    expect(screen.getByTestId("job-form")).toHaveAttribute(
      "data-api-base-url",
      "http://localhost:8000",
    );
  });
});
