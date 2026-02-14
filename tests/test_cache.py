"""Tests for artifact cache."""

import pytest
import time
from pathlib import Path

from localagent.cache import ArtifactCache, compute_content_hash


class TestComputeContentHash:
    """Test content hash computation."""

    def test_hash_string_content(self):
        """Hash string content."""
        result = compute_content_hash("test content")
        assert result.startswith("sha256:")
        assert len(result) == 7 + 64

    def test_hash_bytes_content(self):
        """Hash bytes content."""
        result = compute_content_hash(b"test content")
        assert result.startswith("sha256:")

    def test_hash_deterministic(self):
        """Same content produces same hash."""
        content = "hello world"
        assert compute_content_hash(content) == compute_content_hash(content)

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        assert compute_content_hash("hello") != compute_content_hash("world")


class TestArtifactCache:
    """Test content-addressable cache behavior."""

    def test_store_and_get(self, cache_db_path):
        """Basic store and retrieve."""
        cache = ArtifactCache(db_path=cache_db_path)
        content_hash = "sha256:abc123def456" + "0" * 52
        stored_result = {
            "summary": "Test summary",
            "confidence": 0.95,
            "result_refs": [],
        }

        cache.store(content_hash, stored_result)
        retrieved = cache.get(content_hash)

        assert retrieved is not None
        assert retrieved["summary"] == stored_result["summary"]
        assert retrieved["confidence"] == stored_result["confidence"]

    def test_cache_miss_returns_none(self, cache_db_path):
        """Missing entries should return None."""
        cache = ArtifactCache(db_path=cache_db_path)
        assert cache.get("sha256:nonexistent" + "0" * 54) is None

    def test_cache_invalidate(self, cache_db_path):
        """Invalidate removes entry."""
        cache = ArtifactCache(db_path=cache_db_path)
        content_hash = "sha256:toremove" + "0" * 56

        cache.store(content_hash, {"data": "test"})
        assert cache.get(content_hash) is not None

        cache.invalidate(content_hash)
        assert cache.get(content_hash) is None

    def test_cache_clear(self, cache_db_path):
        """Clear removes all entries."""
        cache = ArtifactCache(db_path=cache_db_path)

        for i in range(5):
            cache.store(f"sha256:hash{i}" + "0" * 58, {"data": i})

        stats = cache.stats()
        assert stats.entry_count == 5

        cache.clear()
        stats = cache.stats()
        assert stats.entry_count == 0

    def test_cache_eviction_on_size_limit(self, cache_db_path):
        """LRU eviction when cache exceeds size limit."""
        cache = ArtifactCache(db_path=cache_db_path, max_entries=3)

        # Add 3 entries
        cache.store("sha256:hash1" + "0" * 59, {"summary": "one"})
        time.sleep(0.01)
        cache.store("sha256:hash2" + "0" * 59, {"summary": "two"})
        time.sleep(0.01)
        cache.store("sha256:hash3" + "0" * 59, {"summary": "three"})

        # Access hash1 to make it recently used
        cache.get("sha256:hash1" + "0" * 59)
        time.sleep(0.01)

        # Add 4th entry, should evict hash2 (LRU)
        cache.store("sha256:hash4" + "0" * 59, {"summary": "four"})

        # hash2 should be evicted
        assert cache.get("sha256:hash2" + "0" * 59) is None
        # hash1 and hash3 should still exist
        assert cache.get("sha256:hash1" + "0" * 59) is not None
        assert cache.get("sha256:hash4" + "0" * 59) is not None

    def test_cache_stats(self, cache_db_path):
        """Stats track hits and misses."""
        cache = ArtifactCache(db_path=cache_db_path)
        content_hash = "sha256:statstest" + "0" * 54

        cache.store(content_hash, {"data": "test"})

        # One hit
        cache.get(content_hash)
        # One miss
        cache.get("sha256:missing" + "0" * 57)

        stats = cache.stats()
        assert stats.hit_count == 1
        assert stats.miss_count == 1
        assert stats.entry_count == 1

    def test_cache_upsert(self, cache_db_path):
        """Storing same hash updates the value."""
        cache = ArtifactCache(db_path=cache_db_path)
        content_hash = "sha256:upserttest" + "0" * 52

        cache.store(content_hash, {"version": 1})
        cache.store(content_hash, {"version": 2})

        retrieved = cache.get(content_hash)
        assert retrieved["version"] == 2

        stats = cache.stats()
        assert stats.entry_count == 1  # Still one entry

    def test_cache_thread_safety(self, cache_db_path):
        """Cache should handle concurrent access."""
        import threading

        cache = ArtifactCache(db_path=cache_db_path)
        errors = []

        def worker(thread_id):
            try:
                for i in range(10):
                    content_hash = f"sha256:thread{thread_id}item{i}" + "0" * 44
                    cache.store(content_hash, {"thread": thread_id, "item": i})
                    cache.get(content_hash)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
