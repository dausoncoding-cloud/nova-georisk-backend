"""Usage counters. Recording is best-effort and never affects the request: any Redis error is ignored.

Buffer: one Redis hash, field "<YYYY-MM-DD>|<organization_id>|<metric>" -> count. `flush()` renames the
hash (atomic), so counts arriving during a flush go to a fresh buffer, then adds the snapshot to
`organization_usage_daily` with one upsert per organisation-day. Runs when the console reads usage and
from `python -m app.services.usage.cli flush` (cron). A Redis restart loses at most the counts since
the last flush.
"""
from __future__ import annotations

import logging
import secrets
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.billing import ledger

logger = logging.getLogger(__name__)

METRICS = ("api_requests", "downloads", "download_bytes")
BUFFER_TTL_SECONDS = 40 * 24 * 3600
# A slow or unreachable Redis must never delay a request (security review L7): short timeouts, and writes
# happen off the request path (a background task for API requests, a small worker pool for downloads).
REDIS_TIMEOUT_SECONDS = 0.05
_MAX_PENDING_DOWNLOADS = 1000
_download_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="usage-counter")
_pending_downloads = 0
_pending_lock = threading.Lock()


def buffer_key() -> str:
    return f"{get_settings().session_redis_prefix.split(':')[0]}:usage:buffer"


def today() -> date:
    return datetime.now(timezone.utc).astimezone(ledger._zone()).date()


def _field(organization_id: uuid.UUID, metric: str, day: date | None = None) -> str:
    return f"{(day or today()).isoformat()}|{organization_id}|{metric}"


@lru_cache
def _sync_client():
    import redis

    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True,
                                socket_connect_timeout=REDIS_TIMEOUT_SECONDS, socket_timeout=REDIS_TIMEOUT_SECONDS)


@lru_cache
def _flush_client():
    """Off the request path (console reads, cron), so it may wait longer than the counters."""
    import redis

    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True,
                                socket_connect_timeout=2, socket_timeout=5)


@lru_cache
def _async_client():
    import redis.asyncio as redis_asyncio

    return redis_asyncio.Redis.from_url(get_settings().redis_url, decode_responses=True,
                                        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
                                        socket_timeout=REDIS_TIMEOUT_SECONDS)


def record_download(organization_id: uuid.UUID | None, size_bytes: int | None, client=None) -> None:
    """One protected file delivered to an organisation member (full file, not a byte range). Returns at once:
    the Redis write runs in a small worker pool and is dropped when Redis is backed up. Never raises."""
    global _pending_downloads
    try:
        if organization_id is None or not get_settings().usage_counting_enabled:
            return
        with _pending_lock:
            if _pending_downloads >= _MAX_PENDING_DOWNLOADS:
                return
            _pending_downloads += 1
        future = _download_pool.submit(_write_download, organization_id, size_bytes, client)
        future.add_done_callback(_download_done)
    except Exception:
        logger.debug("Usage counter unavailable (download)")


def _download_done(_future) -> None:
    global _pending_downloads
    with _pending_lock:
        _pending_downloads = max(0, _pending_downloads - 1)


def _write_download(organization_id: uuid.UUID, size_bytes: int | None, client=None) -> None:
    try:
        client = client or _sync_client()
        pipe = client.pipeline()
        pipe.hincrby(buffer_key(), _field(organization_id, "downloads"), 1)
        if size_bytes:
            pipe.hincrby(buffer_key(), _field(organization_id, "download_bytes"), int(size_bytes))
        pipe.expire(buffer_key(), BUFFER_TTL_SECONDS)
        pipe.execute()
    except Exception:
        logger.debug("Usage counter unavailable (download)")


async def record_api_request(organization_id: uuid.UUID, client=None) -> None:
    try:
        client = client or _async_client()
        await client.hincrby(buffer_key(), _field(organization_id, "api_requests"), 1)
    except Exception:
        logger.debug("Usage counter unavailable (API request)")


_UPSERT = text("""
    INSERT INTO organization_usage_daily (organization_id, day, api_requests, downloads, download_bytes)
    SELECT :organization_id, :day, :api_requests, :downloads, :download_bytes
    WHERE EXISTS (SELECT 1 FROM organizations WHERE id = :organization_id)
    ON CONFLICT (organization_id, day) DO UPDATE SET
        api_requests = organization_usage_daily.api_requests + EXCLUDED.api_requests,
        downloads = organization_usage_daily.downloads + EXCLUDED.downloads,
        download_bytes = organization_usage_daily.download_bytes + EXCLUDED.download_bytes
""")


def flush(db: Session, client=None) -> int:
    """Move the Redis buffer into Postgres. Returns the number of organisation-days written. Commits.
    If the database write fails, the snapshot is put back into the buffer."""
    if not get_settings().usage_counting_enabled:
        return 0
    try:
        client = client or _flush_client()
        snapshot_key = f"{buffer_key()}:flush:{secrets.token_hex(6)}"
        try:
            client.rename(buffer_key(), snapshot_key)
        except Exception as exc:  # no buffer yet ("no such key")
            if "no such key" in str(exc).lower():
                return 0
            raise
        raw = client.hgetall(snapshot_key)
    except Exception:
        logger.warning("Usage buffer could not be read; console usage may lag")
        return 0
    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: dict.fromkeys(METRICS, 0))
    for field, value in raw.items():
        try:
            day, organization, metric = field.split("|")
            uuid.UUID(organization)
            date.fromisoformat(day)
        except ValueError:
            continue
        if metric in METRICS:
            totals[(day, organization)][metric] += int(value)
    try:
        for (day, organization), values in totals.items():
            db.execute(_UPSERT, {"organization_id": organization, "day": day, **values})
        db.commit()
    except Exception:
        db.rollback()
        pipe = client.pipeline()
        for field, value in raw.items():
            pipe.hincrby(buffer_key(), field, int(value))
        pipe.delete(snapshot_key)
        pipe.execute()
        raise
    client.delete(snapshot_key)
    return len(totals)
