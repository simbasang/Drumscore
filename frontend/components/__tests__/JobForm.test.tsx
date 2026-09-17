import { fireEvent, render, screen } from "@testing-library/react";

import { createJob } from "@/lib/api/jobs";
import JobForm from "../JobForm";

jest.mock("@/lib/api/jobs");

function fillAndSubmit(url: string) {
  fireEvent.change(screen.getByLabelText(/youtube url/i), { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: /generate drum score/i }));
}

describe("JobForm", () => {
  it("should show a validation error and not call the API when the URL is empty", () => {
    render(<JobForm apiBaseUrl="http://localhost:8000" />);

    fillAndSubmit("");

    expect(screen.getByRole("alert")).toHaveTextContent(/enter a youtube url/i);
    expect(createJob).not.toHaveBeenCalled();
  });

  it("should display the created job after a successful submission", async () => {
    (createJob as jest.Mock).mockResolvedValue({
      id: "job-1",
      url: "https://youtu.be/dQw4w9WgXcQ",
      status: "queued",
    });

    render(<JobForm apiBaseUrl="http://localhost:8000" />);

    fillAndSubmit("https://youtu.be/dQw4w9WgXcQ");

    expect(await screen.findByText(/job-1/)).toBeInTheDocument();
    expect(screen.getByText(/queued/i)).toBeInTheDocument();
    expect(createJob).toHaveBeenCalledWith(
      "http://localhost:8000",
      "https://youtu.be/dQw4w9WgXcQ",
    );
  });

  it("should display the backend's error message when job creation fails", async () => {
    (createJob as jest.Mock).mockRejectedValue(
      new Error("'x' is not a supported YouTube URL"),
    );

    render(<JobForm apiBaseUrl="http://localhost:8000" />);

    fillAndSubmit("x");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "'x' is not a supported YouTube URL",
    );
  });
});
