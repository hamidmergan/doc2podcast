"""Running ffmpeg in its own session, so a timeout kills the whole process group."""

import os
import subprocess


def run_proc(cmd, timeout: int) -> subprocess.CompletedProcess:
    """Run a command in a new session (killable process group)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            proc.kill()
        stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(
        cmd, proc.returncode,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )
