"""HTTP broker for LocalAgent task delegation."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from localagent.cache import ArtifactCache, compute_content_hash, get_cache
from localagent.policies import get_policy, is_tool_allowed
from localagent.schemas import (
    DelegationRequest,
    DelegationResponse,
    ErrorResponse,
    FetchDetailRequest,
    FetchDetailResponse,
    HealthResponse,
    InputRefType,
    ResultRef,
    ResultRefType,
    TaskStatus,
    ToolName,
)
from localagent.subagents.bash_runner import CommandBlockedError, run_bash
from localagent.subagents.file_scanner import scan_files
from localagent.subagents.summarizer import (
    SubagentUnavailableError,
    check_ollama_health,
    summarize_content,
)

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="LocalAgent Broker",
    description="HTTP broker for delegating tasks to local subagents",
    version="0.1.0",
)


# --- Retry Queue for Ollama unavailability ---


@dataclass
class QueuedTask:
    """Task queued for retry when Ollama is unavailable."""

    task_id: str
    request: DelegationRequest
    queued_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    retry_timeout_seconds: int = 120


class RetryQueue:
    """Queue for tasks waiting on Ollama availability."""

    def __init__(self, max_size: int = 100):
        self._queue: deque[QueuedTask] = deque(maxlen=max_size)
        self._lock = Lock()

    def add(self, task: QueuedTask) -> int:
        """Add task to queue, return position."""
        with self._lock:
            self._queue.append(task)
            return len(self._queue)

    def pop(self) -> QueuedTask | None:
        """Pop oldest task from queue."""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def size(self) -> int:
        """Get queue size."""
        with self._lock:
            return len(self._queue)

    def cleanup_expired(self) -> list[QueuedTask]:
        """Remove and return expired tasks."""
        now = time.time()
        expired = []
        with self._lock:
            remaining = deque()
            for task in self._queue:
                if now - task.queued_at > task.retry_timeout_seconds:
                    expired.append(task)
                else:
                    remaining.append(task)
            self._queue = remaining
        return expired


# Global instances
_retry_queue = RetryQueue()
_last_ollama_check: datetime | None = None
_ollama_status = "healthy"


# --- Provenance Hash Chain ---


def _compute_audit_hash(task_id: str, operation: str, result_hash: str) -> str:
    """Compute hash for audit log entry."""
    content = f"{task_id}:{operation}:{result_hash}:{time.time()}"
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


# --- Session Management ---


@dataclass
class Session:
    """Session state for context continuity."""

    session_id: str
    created_at: float
    task_history: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def add_task(self, task_id: str, tool_name: str, summary_snippet: str) -> None:
        """Add task to history."""
        self.task_history.append({
            "task_id": task_id,
            "tool_name": tool_name,
            "summary_snippet": summary_snippet[:100],
            "completed_at": time.time(),
        })
        # Keep only last 20 tasks
        if len(self.task_history) > 20:
            self.task_history = self.task_history[-20:]


_sessions: dict[str, Session] = {}
_sessions_lock = Lock()


def _get_or_create_session(session_id: str | None) -> Session:
    """Get existing session or create new one."""
    if session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"

    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = Session(
                session_id=session_id,
                created_at=time.time(),
            )
        return _sessions[session_id]


# --- Subagent Dispatchers ---


def _dispatch_file_scanner(
    request: DelegationRequest,
    cache: ArtifactCache,
) -> DelegationResponse:
    """Dispatch to file_scanner subagent."""
    patterns = []
    root_dir = str(Path.cwd())

    for ref in request.input_refs:
        if ref.type == InputRefType.GLOB:
            patterns.append(ref.value)

    if not patterns:
        patterns = ["*"]

    result = scan_files(
        patterns=patterns,
        root_dir=root_dir,
        max_summary_tokens=request.max_summary_tokens,
    )

    # Compute audit hash
    result_hash = compute_content_hash(result.summary)
    audit_hash = _compute_audit_hash(request.task_id, "file_scanner", result_hash)

    return DelegationResponse(
        session_id=request.session_id,
        task_id=request.task_id,
        status=TaskStatus.COMPLETED,
        summary=result.summary,
        result_refs=result.result_refs,
        confidence=result.confidence,
        audit_log_hashes=[audit_hash],
    )


def _dispatch_summarizer(
    request: DelegationRequest,
    cache: ArtifactCache,
) -> DelegationResponse:
    """Dispatch to summarizer subagent."""
    content = ""

    for ref in request.input_refs:
        if ref.type == InputRefType.CONTENT:
            content = ref.value
            break
        elif ref.type == InputRefType.HASH:
            # Try to get from cache
            cached = cache.get(ref.value)
            if cached and "content" in cached:
                content = cached["content"]
                break

    if not content:
        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=TaskStatus.FAILED,
            summary="No content provided for summarization",
            result_refs=[],
            confidence=0.0,
            audit_log_hashes=[],
        )

    # Check cache first
    content_hash = compute_content_hash(content)
    cached_result = cache.get(content_hash)
    if cached_result:
        logger.info(f"Cache hit for {request.task_id}")
        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=TaskStatus.COMPLETED,
            summary=cached_result.get("summary", ""),
            result_refs=[
                ResultRef(
                    type=ResultRefType.CACHE,
                    hash=content_hash,
                )
            ],
            confidence=cached_result.get("confidence", 0.9),
            audit_log_hashes=cached_result.get("audit_log_hashes", []),
        )

    # Call summarizer
    try:
        result = summarize_content(
            content=content,
            max_tokens=request.max_summary_tokens,
        )
    except SubagentUnavailableError:
        # Queue for retry
        queued_task = QueuedTask(
            task_id=request.task_id,
            request=request,
        )
        position = _retry_queue.add(queued_task)

        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=TaskStatus.QUEUED,
            queue_position=position,
            summary="Task queued: Ollama service unavailable",
            result_refs=[],
            confidence=0.0,
            audit_log_hashes=[],
        )

    # Cache the result
    audit_hash = _compute_audit_hash(request.task_id, "summarizer", content_hash)
    cache.store(content_hash, {
        "summary": result.summary,
        "confidence": result.confidence,
        "audit_log_hashes": [audit_hash],
    })

    return DelegationResponse(
        session_id=request.session_id,
        task_id=request.task_id,
        status=TaskStatus.COMPLETED,
        summary=result.summary,
        result_refs=[
            ResultRef(
                type=ResultRefType.CACHE,
                hash=content_hash,
            )
        ],
        confidence=result.confidence,
        audit_log_hashes=[audit_hash],
    )


def _dispatch_bash_runner(
    request: DelegationRequest,
    cache: ArtifactCache,
) -> DelegationResponse:
    """Dispatch to bash_runner subagent."""
    command = ""

    for ref in request.input_refs:
        if ref.type == InputRefType.COMMAND:
            command = ref.value
            break

    if not command:
        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=TaskStatus.FAILED,
            summary="No command provided for bash_runner",
            result_refs=[],
            confidence=0.0,
            audit_log_hashes=[],
        )

    try:
        result = run_bash(
            command=command,
            policy_id=request.policy_id,
        )

        # Build summary
        summary_parts = [f"Command: {command}"]
        summary_parts.append(f"Exit code: {result.exit_code}")
        if result.stdout:
            stdout_preview = result.stdout[:200] + "..." if len(result.stdout) > 200 else result.stdout
            summary_parts.append(f"Output: {stdout_preview}")
        if result.stderr:
            stderr_preview = result.stderr[:100] + "..." if len(result.stderr) > 100 else result.stderr
            summary_parts.append(f"Errors: {stderr_preview}")

        summary = " | ".join(summary_parts)

        # Compute audit hash
        output_hash = compute_content_hash(result.stdout + result.stderr)
        audit_hash = _compute_audit_hash(request.task_id, "bash_runner", output_hash)

        status = TaskStatus.COMPLETED if result.exit_code == 0 else TaskStatus.PARTIAL

        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=status,
            summary=summary,
            result_refs=[
                ResultRef(
                    type=ResultRefType.MEMORY,
                    hash=output_hash,
                )
            ],
            confidence=result.confidence,
            audit_log_hashes=[audit_hash],
        )

    except CommandBlockedError as e:
        return DelegationResponse(
            session_id=request.session_id,
            task_id=request.task_id,
            status=TaskStatus.FAILED,
            summary=f"Command blocked: {e}",
            result_refs=[],
            confidence=1.0,
            audit_log_hashes=[],
        )


# --- HTTP Endpoints ---


@app.post("/delegate", response_model=DelegationResponse)
async def delegate(request: DelegationRequest) -> DelegationResponse:
    """Delegate a task to a subagent.

    Args:
        request: DelegationRequest with task details

    Returns:
        DelegationResponse with results
    """
    logger.info(f"Received delegation request: task_id={request.task_id}, tool={request.tool_name}")

    # Validate tool against policy
    if not is_tool_allowed(request.policy_id, request.tool_name.value):
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{request.tool_name.value}' not allowed under policy '{request.policy_id.value}'",
        )

    # Get cache
    cache = get_cache()

    # Get or create session
    session = _get_or_create_session(request.session_id)
    request.session_id = session.session_id

    # Dispatch to appropriate subagent
    if request.tool_name == ToolName.FILE_SCANNER:
        response = _dispatch_file_scanner(request, cache)
    elif request.tool_name == ToolName.SUMMARIZER:
        response = _dispatch_summarizer(request, cache)
    elif request.tool_name == ToolName.BASH_RUNNER:
        response = _dispatch_bash_runner(request, cache)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool: {request.tool_name.value}",
        )

    # Update session
    session.add_task(request.task_id, request.tool_name.value, response.summary)

    logger.info(f"Completed delegation: task_id={request.task_id}, status={response.status}")
    return response


@app.post("/fetch_detail", response_model=FetchDetailResponse)
async def fetch_detail(request: FetchDetailRequest) -> FetchDetailResponse:
    """Fetch full content for a result reference.

    Args:
        request: FetchDetailRequest with hash and format

    Returns:
        FetchDetailResponse with content
    """
    cache = get_cache()
    cached = cache.get(request.hash)

    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"Content not found for hash: {request.hash}",
        )

    content = cached.get("content", cached.get("summary", ""))

    return FetchDetailResponse(
        task_id=request.task_id,
        status=TaskStatus.COMPLETED,
        content=content,
        content_type="text/plain",
        size_bytes=len(content.encode("utf-8")),
        hash=request.hash,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check broker and dependency health."""
    global _last_ollama_check, _ollama_status

    # Check Ollama
    ollama_healthy = check_ollama_health()
    _last_ollama_check = datetime.now()

    if ollama_healthy:
        _ollama_status = "healthy"
    elif _ollama_status == "healthy":
        _ollama_status = "unhealthy"
    else:
        _ollama_status = "recovering" if _retry_queue.size() > 0 else "unhealthy"

    return HealthResponse(
        broker="healthy",
        ollama=_ollama_status,  # type: ignore
        queue_depth=_retry_queue.size(),
        last_ollama_check=_last_ollama_check.isoformat() if _last_ollama_check else None,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail=str(exc),
            error_code="INTERNAL_ERROR",
        ).model_dump(),
    )
