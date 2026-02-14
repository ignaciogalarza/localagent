"""Content-addressable artifact cache with SQLite backend."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 1000
DEFAULT_DB_PATH = Path.home() / ".localagent" / "cache.db"


@dataclass
class CacheStats:
    """Cache statistics."""

    hit_count: int = 0
    miss_count: int = 0
    entry_count: int = 0
    total_bytes: int = 0


class ArtifactCache:
    """Content-addressable cache with SQLite backend and LRU eviction."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        """Initialize the cache.

        Args:
            db_path: Path to SQLite database file
            max_entries: Maximum number of entries before LRU eviction
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._stats = CacheStats()

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    content_hash TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_accessed INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_accessed
                ON cache (last_accessed)
            """)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def store(self, content_hash: str, result: dict[str, Any]) -> None:
        """Store a result in the cache.

        Args:
            content_hash: SHA256 hash of the content (e.g., "sha256:abc...")
            result: Dictionary to store
        """
        result_json = json.dumps(result)
        size_bytes = len(result_json.encode("utf-8"))
        now = int(time.time() * 1000000)  # Microseconds for better precision

        with self._lock:
            with self._get_connection() as conn:
                # Upsert the entry
                conn.execute(
                    """
                    INSERT INTO cache (content_hash, result_json, size_bytes, created_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(content_hash) DO UPDATE SET
                        result_json = excluded.result_json,
                        size_bytes = excluded.size_bytes,
                        last_accessed = excluded.last_accessed
                    """,
                    (content_hash, result_json, size_bytes, now, now),
                )
                conn.commit()

                # Check if eviction needed
                count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                if count > self.max_entries:
                    self._evict_lru(conn, count - self.max_entries)

        logger.debug(f"Cached result for {content_hash[:20]}...")

    def get(self, content_hash: str) -> dict[str, Any] | None:
        """Retrieve a result from the cache.

        Args:
            content_hash: SHA256 hash to look up

        Returns:
            Cached result dictionary, or None if not found
        """
        now = int(time.time() * 1000000)  # Microseconds for better precision

        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT result_json FROM cache WHERE content_hash = ?",
                    (content_hash,),
                ).fetchone()

                if row is None:
                    self._stats.miss_count += 1
                    return None

                # Update last_accessed
                conn.execute(
                    "UPDATE cache SET last_accessed = ? WHERE content_hash = ?",
                    (now, content_hash),
                )
                conn.commit()

                self._stats.hit_count += 1
                return json.loads(row["result_json"])

    def invalidate(self, content_hash: str) -> None:
        """Remove an entry from the cache.

        Args:
            content_hash: SHA256 hash to invalidate
        """
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM cache WHERE content_hash = ?",
                    (content_hash,),
                )
                conn.commit()

        logger.debug(f"Invalidated cache entry: {content_hash[:20]}...")

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM cache")
                conn.commit()
                self._stats = CacheStats()

        logger.info("Cache cleared")

    def stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats with hit/miss counts and entry count
        """
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as total_bytes FROM cache"
                ).fetchone()
                self._stats.entry_count = row["count"]
                self._stats.total_bytes = row["total_bytes"]

        return CacheStats(
            hit_count=self._stats.hit_count,
            miss_count=self._stats.miss_count,
            entry_count=self._stats.entry_count,
            total_bytes=self._stats.total_bytes,
        )

    def _evict_lru(self, conn: sqlite3.Connection, count: int) -> None:
        """Evict the least recently used entries.

        Args:
            conn: Database connection
            count: Number of entries to evict
        """
        conn.execute(
            """
            DELETE FROM cache
            WHERE content_hash IN (
                SELECT content_hash FROM cache
                ORDER BY last_accessed ASC
                LIMIT ?
            )
            """,
            (count,),
        )
        conn.commit()
        logger.debug(f"Evicted {count} LRU entries from cache")


def compute_content_hash(content: str | bytes) -> str:
    """Compute SHA256 hash for content.

    Args:
        content: String or bytes content

    Returns:
        Hash string in format "sha256:..."
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


# Global cache instance
_cache_instance: ArtifactCache | None = None


def get_cache(db_path: Path | str | None = None) -> ArtifactCache:
    """Get or create the global cache instance.

    Args:
        db_path: Optional path to database file

    Returns:
        ArtifactCache instance
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ArtifactCache(db_path=db_path)
    return _cache_instance
