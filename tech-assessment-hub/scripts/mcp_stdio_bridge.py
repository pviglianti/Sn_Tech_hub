#!/usr/bin/env python3
"""MCP stdio-to-HTTP bridge.

Reads JSON-RPC messages from stdin (one per line), POSTs them to the
Tech Assessment Hub's /mcp endpoint, and writes responses to stdout.

This enables Claude Desktop / IDE integration via standard MCP stdio transport.

Usage:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 scripts/mcp_stdio_bridge.py
    python3 scripts/mcp_stdio_bridge.py --port 8080
"""

import sys
import json
import argparse
import urllib.request
import urllib.error


def _detect_server_url() -> str:
    """Read the actual running server URL from data/server.url."""
    from pathlib import Path
    url_file = Path(__file__).resolve().parent.parent / "data" / "server.url"
    try:
        live = url_file.read_text().strip().rstrip("/")
        if live:
            return f"{live}/mcp"
    except (OSError, ValueError):
        pass
    return "http://127.0.0.1:8080/mcp"


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP stdio-to-HTTP bridge")
    parser.add_argument("--port", type=int, default=None, help="App port (auto-detected from server.url if omitted)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="App host (default: 127.0.0.1)")
    args = parser.parse_args()

    if args.port:
        url = f"http://{args.host}:{args.port}/mcp"
    else:
        url = _detect_server_url()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            # Validate it's JSON
            json.loads(line)
        except json.JSONDecodeError:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()
            continue

        try:
            req = urllib.request.Request(
                url,
                data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                sys.stdout.write(body.strip() + "\n")
                sys.stdout.flush()
        except urllib.error.URLError as exc:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": f"Server unreachable: {exc}"},
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": str(exc)},
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
