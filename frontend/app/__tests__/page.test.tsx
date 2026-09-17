import { render, screen } from "@testing-library/react";

import { getBackendHealth } from "@/lib/api/health";
import Home from "../page";

jest.mock("@/lib/api/health");

describe("Home", () => {
  it("should display the backend status when the health check succeeds", async () => {
    (getBackendHealth as jest.Mock).mockResolvedValue({ status: "ok" });

    render(await Home());

    expect(screen.getByText(/backend status: ok/i)).toBeInTheDocument();
  });

  it("should display an error message when the health check fails", async () => {
    (getBackendHealth as jest.Mock).mockRejectedValue(new Error("boom"));

    render(await Home());

    expect(screen.getByText(/backend status: unreachable/i)).toBeInTheDocument();
  });
});
