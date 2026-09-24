import subprocess
import sys

# subprocess.CREATE_NEW_PROCESS_GROUP only exists on Windows builds of Python;
# 0x00000200 is its documented value.
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def detached_process_kwargs() -> dict[str, object]:
    """subprocess.run keyword arguments that start an engine child (Demucs,
    DrumScript) outside the terminal's signal group. Ctrl+C / SIGTERM aimed
    at the worker then reaches only the worker, which finishes or abandons
    the current stage (docs/PERSISTENCE.md §4) instead of seeing the child
    die and failing the job."""
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}
