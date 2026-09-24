"""`python -m app.worker`: starts WORKER_CONCURRENCY worker processes.

This module is OS-process and signal glue around build_worker and
Worker.run_forever (both unit-tested). It is exercised by running the
worker, not by pytest, hence the no-cover pragmas."""

import logging
import multiprocessing
import signal

from app.config import get_settings
from app.worker.factory import build_worker


def run_worker_process() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = build_worker(get_settings())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop())
    worker.run_forever()


def main() -> None:  # pragma: no cover - spawns OS processes
    concurrency = get_settings().worker_concurrency
    if concurrency <= 1:
        run_worker_process()
        return

    processes = [
        multiprocessing.Process(target=run_worker_process, name=f"drumscore-worker-{index}")
        for index in range(concurrency)
    ]
    for process in processes:
        process.start()

    def forward(*_: object) -> None:
        for process in processes:
            process.terminate()  # SIGTERM -> each child's graceful stop

    signal.signal(signal.SIGTERM, forward)
    for process in processes:
        process.join()


if __name__ == "__main__":  # pragma: no cover
    main()
