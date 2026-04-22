"""Web route — GET /api/assessments/{id}/ai-stream.

Server-Sent Events feed that tails the per-run .stream.jsonl file the
subprocess adapter is writing. One SSE event per JSONL line. The stream
closes when the adapter writes the `_stream_end` sentinel (or on a hard
timeout if something hangs).

If `stream_id` is omitted we default to the newest .stream.jsonl under
the assessment's log directory — so the UI can just open the stream
without tracking the id manually.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...database import DATA_DIR


logger = logging.getLogger(__name__)


ai_stream_router = APIRouter(tags=["ai-stream"])


# Match the naming convention used by skill_dispatcher:
#   <stage>-<stream_id>.stream.jsonl
# where stream_id is <YYYYMMDDTHHMMSS>-<8 hex chars>
_STREAM_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{6,16}$")


def _assessment_log_dir(assessment_id: int) -> Path:
    return DATA_DIR / "logs" / "ai_prompts" / f"assessment_{assessment_id}"


def _locate_stream_file(assessment_id: int, stream_id: Optional[str]) -> Optional[Path]:
    log_dir = _assessment_log_dir(assessment_id)
    if not log_dir.is_dir():
        return None

    if stream_id:
        if not _STREAM_ID_RE.match(stream_id):
            # Guard against path traversal and junk
            return None
        # Any stage matching this stream_id wins.
        matches = sorted(log_dir.glob(f"*-{stream_id}.stream.jsonl"))
        return matches[0] if matches else None

    # Default = newest .stream.jsonl in the directory.
    candidates = sorted(
        log_dir.glob("*.stream.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def _tail_as_sse(
    stream_path: Path,
    request: Request,
    *,
    idle_timeout_seconds: int = 1800,
    max_wait_start_seconds: int = 20,
) -> AsyncIterator[bytes]:
    """Async generator: tail stream_path; emit one SSE event per JSONL line.

    - Sends `: keepalive` comment pings every ~15s so proxies don't reap the
      connection.
    - Terminates cleanly when it sees `_stream_end` in the file, when the
      client disconnects, or after idle_timeout_seconds with no new data.
    - If the file doesn't exist yet, polls for up to max_wait_start_seconds
      before giving up (covers the tiny race between 202 response and
      subprocess creating the file).
    """
    # Wait briefly for the file to appear if the run just started.
    waited = 0.0
    while not stream_path.exists() and waited < max_wait_start_seconds:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25)
        waited += 0.25
    if not stream_path.exists():
        yield b"event: error\ndata: {\"error\":\"stream file not found\"}\n\n"
        return

    last_activity = asyncio.get_event_loop().time()
    keepalive_at = last_activity + 15.0
    ended = False

    # Open and read incrementally. `seek(0, 2)` would skip existing content;
    # we want to REPLAY existing lines for clients that subscribe after a
    # run is already underway.
    f = stream_path.open("r", encoding="utf-8")
    try:
        while True:
            if await request.is_disconnected():
                break

            line = f.readline()
            if line:
                last_activity = asyncio.get_event_loop().time()
                # One SSE event per JSONL line. Event type = the JSON "type"
                # field if we can parse it; otherwise "message".
                event_type = "message"
                stripped = line.rstrip("\n")
                try:
                    import json as _json
                    parsed = _json.loads(stripped)
                    if isinstance(parsed, dict) and parsed.get("type"):
                        event_type = str(parsed["type"])
                except Exception:
                    pass
                yield f"event: {event_type}\ndata: {stripped}\n\n".encode("utf-8")
                if event_type in ("_stream_end", "_stream_error"):
                    ended = True
                    break
                continue

            # No new data: maybe emit a keepalive, maybe time out.
            now = asyncio.get_event_loop().time()
            if now - last_activity > idle_timeout_seconds:
                yield b"event: _stream_timeout\ndata: {\"reason\":\"idle\"}\n\n"
                break
            if now >= keepalive_at:
                yield b": keepalive\n\n"
                keepalive_at = now + 15.0
            await asyncio.sleep(0.5)
    finally:
        try:
            f.close()
        except Exception:
            pass
        if not ended:
            try:
                yield b"event: _stream_end\ndata: {\"reason\":\"closed\"}\n\n"
            except Exception:
                pass


@ai_stream_router.get("/api/assessments/{assessment_id}/ai-stream")
async def api_ai_stream(
    assessment_id: int,
    request: Request,
    stream_id: Optional[str] = Query(default=None),
) -> StreamingResponse:
    path = _locate_stream_file(assessment_id, stream_id)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No stream file for assessment {assessment_id}"
                + (f" stream_id={stream_id}" if stream_id else "")
            ),
        )

    async def event_source() -> AsyncIterator[bytes]:
        try:
            async for chunk in _tail_as_sse(path, request):
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected — normal.
            return
        except Exception:
            logger.exception("ai-stream tail crashed for %s", path)
            yield b"event: error\ndata: {\"error\":\"stream reader crashed\"}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer
            "Connection": "keep-alive",
        },
    )
