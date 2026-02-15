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


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP stdio-to-HTTP bridge")
    parser.add_argument("--port", type=int, default=8080, help="App port (default: 8080)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="App host (default: 127.0.0.1)")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/mcp"

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
