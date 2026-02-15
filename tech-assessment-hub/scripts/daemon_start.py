#!/usr/bin/env python3
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _looks_like_our_server(pid: int) -> bool:
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except Exception:
        return False
    cmd = (out or "").strip()
    return ("uvicorn" in cmd) and ("src.server:app" in cmd)


def _find_free_port(host: str, start_port: int, tries: int) -> int:
    for port in range(start_port, start_port + max(1, tries)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Failed to find a free port starting at {start_port}.")


def _url_reachable(url: str, timeout_s: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            # Force headers/body to be received (some failures accept but never respond).
            _ = resp.read(1)
            return 200 <= getattr(resp, "status", 200) < 500
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
        return False


def _tail_lines(path: Path, n: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-n:])


def _find_existing_server_pid(host: str, start_port: int, tries: int) -> Optional[Tuple[int, int]]:
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=", "-o", "command="], text=True)
    except Exception:
        return None

    ports = {str(p) for p in range(start_port, start_port + max(1, tries))}
    for raw_line in (out or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        pid_s, cmd = parts
        if "uvicorn" not in cmd or "src.server:app" not in cmd:
            continue
        if f"--host {host}" not in cmd:
            continue
        # Match common variants: "--port 8080" or "--port=8080"
        for port_s in ports:
            if f"--port {port_s}" in cmd or f"--port={port_s}" in cmd:
                try:
                    return (int(pid_s), int(port_s))
                except ValueError:
                    return None
    return None


def main() -> int:
    root_dir = Path(__file__).resolve().parents[1]
    os.chdir(root_dir)

    pidfile = root_dir / "data" / "server.pid"
    urlfile = root_dir / "data" / "server.url"
    logfile = root_dir / "data" / "server.log"
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    host = (os.getenv("TECH_ASSESSMENT_HUB_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    start_port = int((os.getenv("TECH_ASSESSMENT_HUB_PORT") or "8080").strip() or "8080")

    if pidfile.exists():
        try:
            pid = int((pidfile.read_text() or "").strip())
        except ValueError:
            pid = 0
        if pid and _process_alive(pid) and _looks_like_our_server(pid):
            url = (urlfile.read_text() if urlfile.exists() else "").strip()
            if url:
                print(f"Already running (pid={pid}) at {url}")
            else:
                print(f"Already running (pid={pid}).")
            return 0
        pidfile.unlink(missing_ok=True)
        urlfile.unlink(missing_ok=True)

    # Recovery path: if the server is already running but the pidfile/urlfile were lost.
    existing = _find_existing_server_pid(host, start_port, tries=20)
    if existing:
        pid, port = existing
        url = f"http://{host}:{port}"
        if _process_alive(pid) and _looks_like_our_server(pid):
            if _url_reachable(url + "/api/mcp/health", timeout_s=0.5):
                pidfile.write_text(str(pid))
                urlfile.write_text(url)
                print(f"Recovered running server (pid={pid}) at {url}")
                return 0
            # Hung server: shut it down and proceed to start fresh.
            try:
                os.kill(pid, 15)  # SIGTERM
            except OSError:
                pass

    port = _find_free_port(host, start_port, tries=20)
    url = f"http://{host}:{port}"
    probe_url = url + "/api/mcp/health"

    python_bin = root_dir / "venv" / "bin" / "python"
    cmd = [
        str(python_bin),
        "-u",
        "-m",
        "uvicorn",
        "src.server:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "info",
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc: Optional[subprocess.Popen] = None
    try:
        with logfile.open("a", buffering=1) as log_fp:
            proc = subprocess.Popen(
                cmd,
                cwd=str(root_dir),
                env=env,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Poll for reachability.
        for _ in range(80):
            if proc.poll() is not None:
                print("Server exited during startup. Last logs:")
                tail = _tail_lines(logfile, 80)
                if tail:
                    print(tail)
                return 1
            if _url_reachable(probe_url, timeout_s=0.35):
                pidfile.write_text(str(proc.pid))
                urlfile.write_text(url)
                print(f"Started (pid={proc.pid}) at {url}")
                print(f"Logs: {logfile}")
                return 0
            time.sleep(0.1)

        print(f"Started (pid={proc.pid}) but did not become reachable at {url} yet.")
        print(f"Check logs: {logfile}")
        return 1
    finally:
        # Avoid leaking stray server processes on start failures/exceptions.
        if proc is not None and proc.poll() is None and not pidfile.exists():
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
