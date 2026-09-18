import { act, fireEvent, render, screen } from "@testing-library/react";

import { createJob, getJob } from "@/lib/api/jobs";
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

  describe("polling", () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it("should poll for job status until it reaches tempo_mapped", async () => {
      (createJob as jest.Mock).mockResolvedValue({
        id: "job-1",
        url: "https://youtu.be/dQw4w9WgXcQ",
        status: "queued",
      });
      (getJob as jest.Mock)
        .mockResolvedValueOnce({ id: "job-1", status: "downloading" })
        .mockResolvedValueOnce({ id: "job-1", status: "separating_stems" })
        .mockResolvedValueOnce({ id: "job-1", status: "transcribing" })
        .mockResolvedValueOnce({ id: "job-1", status: "transcribed", event_count: 42 })
        .mockResolvedValueOnce({ id: "job-1", status: "mapping_tempo", event_count: 42 })
        .mockResolvedValueOnce({
          id: "job-1",
          status: "tempo_mapped",
          event_count: 42,
          tempo_bpm: 128.4,
        });

      render(<JobForm apiBaseUrl="http://localhost:8000" />);
      fillAndSubmit("https://youtu.be/dQw4w9WgXcQ");
      await act(async () => {});

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/downloading audio/i)).toBeInTheDocument();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/separating drum stems/i)).toBeInTheDocument();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/transcribing drum hits/i)).toBeInTheDocument();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/42 drum hits detected/i)).toBeInTheDocument();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/estimating tempo/i)).toBeInTheDocument();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(screen.getByText(/128 bpm/i)).toBeInTheDocument();

      const callsAfterDone = (getJob as jest.Mock).mock.calls.length;
      await act(async () => {
        jest.advanceTimersByTime(4000);
      });
      expect((getJob as jest.Mock).mock.calls.length).toBe(callsAfterDone);
    });

    it("should show the backend's error and stop polling once the job fails", async () => {
      (createJob as jest.Mock).mockResolvedValue({
        id: "job-1",
        url: "https://youtu.be/dQw4w9WgXcQ",
        status: "queued",
      });
      (getJob as jest.Mock).mockResolvedValue({
        id: "job-1",
        status: "failed",
        error: "video unavailable",
      });

      render(<JobForm apiBaseUrl="http://localhost:8000" />);
      fillAndSubmit("https://youtu.be/dQw4w9WgXcQ");
      await act(async () => {});

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });

      expect(await screen.findByRole("alert")).toHaveTextContent("video unavailable");

      const callsAfterFailure = (getJob as jest.Mock).mock.calls.length;
      await act(async () => {
        jest.advanceTimersByTime(4000);
      });
      expect((getJob as jest.Mock).mock.calls.length).toBe(callsAfterFailure);
    });
  });
});
