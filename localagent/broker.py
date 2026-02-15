"""HTTP broker for LocalAgent task delegation."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from localagent.cache import ArtifactCache, compute_content_hash, get_cache
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
from localagent.subagents.file_scanner import scan_files
from localagent.subagents.summarizer import (
    check_ollama_health,
    summarize_content,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="LocalAgent Broker",
    description="HTTP broker for delegating tasks to local subagents",
    version="0.2.0",
)


def _compute_audit_hash(task_id: str, operation: str, result_hash: str) -> str:
    """Compute hash for audit log entry."""
    content = f"{task_id}:{operation}:{result_hash}:{time.time()}"
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


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

    result_hash = compute_content_hash(result.summary)
    audit_hash = _compute_audit_hash(request.task_id, "file_scanner", result_hash)

    return DelegationResponse(
        task_id=request.task_id,
        status=TaskStatus.COMPLETED,
        summary=result.summary,
        result_refs=result.result_refs,
        confidence=result.confidence,
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
            cached = cache.get(ref.value)
            if cached and "content" in cached:
                content = cached["content"]
                break

    if not content:
        return DelegationResponse(
            task_id=request.task_id,
            status=TaskStatus.FAILED,
            summary="No content provided for summarization",
            result_refs=[],
            confidence=0.0,
        )

    # Check cache first
    content_hash = compute_content_hash(content)
    cached_result = cache.get(content_hash)
    if cached_result:
        logger.info(f"Cache hit for {request.task_id}")
        return DelegationResponse(
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
        )

    result = summarize_content(
        content=content,
        max_tokens=request.max_summary_tokens,
    )

    # Cache the result
    cache.store(content_hash, {
        "summary": result.summary,
        "confidence": result.confidence,
    })

    return DelegationResponse(
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
    )


@app.post("/delegate", response_model=DelegationResponse)
async def delegate(request: DelegationRequest) -> DelegationResponse:
    """Delegate a task to a subagent."""
    logger.info(f"Received delegation: task_id={request.task_id}, tool={request.tool_name}")

    cache = get_cache()

    if request.tool_name == ToolName.FILE_SCANNER:
        response = _dispatch_file_scanner(request, cache)
    elif request.tool_name == ToolName.SUMMARIZER:
        response = _dispatch_summarizer(request, cache)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool: {request.tool_name.value}",
        )

    logger.info(f"Completed: task_id={request.task_id}, status={response.status}")
    return response


@app.post("/fetch_detail", response_model=FetchDetailResponse)
async def fetch_detail(request: FetchDetailRequest) -> FetchDetailResponse:
    """Fetch full content for a result reference."""
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
    ollama_healthy = check_ollama_health()

    return HealthResponse(
        broker="healthy",
        ollama="healthy" if ollama_healthy else "unhealthy",
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
