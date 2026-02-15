#!/usr/bin/env python3
"""
Tech Assessment Hub - Main Entry Point

A desktop application for ServiceNow technical assessments.
Run this file to start the web server and open the browser.
"""

import uvicorn
import webbrowser
import threading
import time
import sys
import socket
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

HOST = (os.getenv("TECH_ASSESSMENT_HUB_HOST") or "127.0.0.1").strip()
DEFAULT_PORT = int((os.getenv("TECH_ASSESSMENT_HUB_PORT") or "8080").strip())


def _find_available_port(host: str, start_port: int, tries: int = 20) -> int:
    for port in range(start_port, start_port + max(1, tries)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError(f"No available port found starting at {start_port} (tries={tries})")


PORT = _find_available_port(HOST, DEFAULT_PORT, tries=20)
URL = f"http://{HOST}:{PORT}"


def open_browser():
    """Open browser after a short delay to let server start"""
    time.sleep(1.5)
    print(f"\n>>> Opening browser at {URL}")
    webbrowser.open(URL)


def main():
    """Main entry point"""
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║           Tech Assessment Hub v0.1.0                  ║
    ║         ServiceNow Technical Assessment Tool          ║
    ╚═══════════════════════════════════════════════════════╝
    """)

    if PORT != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} is in use; using {PORT} instead.")
        print("Tip: set TECH_ASSESSMENT_HUB_PORT to choose a specific port.")

    print(f"Starting server at {URL}")
    print("Press Ctrl+C to stop the server\n")

    # Open browser in a separate thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Start the server
    uvicorn.run(
        "src.server:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
