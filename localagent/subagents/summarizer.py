"""Summarizer subagent for content compression using Ollama."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from localagent.schemas import SummarizeResult

logger = logging.getLogger(__name__)

# Ollama API endpoint
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_GENERATE_ENDPOINT = f"{OLLAMA_BASE_URL}/api/generate"

# Default model
DEFAULT_MODEL = "mistral:7b-instruct-q4_0"

# Timeouts
OLLAMA_TIMEOUT = 30.0  # seconds

# Chunking settings
MAX_CHUNK_TOKENS = 4000
LARGE_CONTENT_THRESHOLD = 50 * 1024  # 50KB

# Character limit for DelegationResponse.summary schema
MAX_SUMMARY_CHARS = 1500


class SubagentUnavailableError(Exception):
    """Raised when the subagent's backing service is unavailable."""

    pass


def _estimate_tokens(text: str) -> int:
    """Estimate token count using word-based heuristic."""
    return int(len(text.split()) * 1.33)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    words = text.split()
    max_words = int(max_tokens * 0.75)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _truncate_to_chars(text: str, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """Truncate text to max_chars, breaking at word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 3]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


def _build_summarization_prompt(content: str, max_tokens: int, context: str | None = None) -> str:
    """Build the prompt for summarization."""
    # Calculate character limit (roughly 4 chars per token, capped at schema limit)
    max_chars = min(max_tokens * 4, MAX_SUMMARY_CHARS - 100)  # Buffer for safety

    prompt = f"""Summarize the following content. STRICT LIMITS: under {max_tokens} tokens AND under {max_chars} characters. Be extremely concise.

Format your response EXACTLY as:
SUMMARY: <your concise summary here>
CONFIDENCE: <0.0-1.0>

Confidence guide: 0.9-1.0=captured all key points, 0.7-0.9=good coverage, 0.5-0.7=partial, <0.5=uncertain.

"""
    if context:
        prompt += f"Context: {context}\n\n"

    prompt += f"Content to summarize:\n{content}"
    return prompt


def _parse_llm_response(response_text: str) -> tuple[str, float]:
    """Parse LLM response to extract summary and confidence."""
    summary = response_text
    confidence = 0.8  # Default confidence

    # Try to extract structured response
    summary_match = re.search(r"SUMMARY:\s*(.+?)(?=CONFIDENCE:|$)", response_text, re.DOTALL)
    confidence_match = re.search(r"CONFIDENCE:\s*([\d.]+)", response_text)

    if summary_match:
        summary = summary_match.group(1).strip()
    if confidence_match:
        try:
            confidence = float(confidence_match.group(1))
            confidence = max(0.0, min(1.0, confidence))
        except ValueError:
            pass

    return summary, confidence


def _chunk_content(content: str, max_chunk_tokens: int = MAX_CHUNK_TOKENS) -> list[str]:
    """Split content into semantically meaningful chunks."""
    # Boundary patterns in order of preference
    boundaries = [
        r"\n\nclass ",  # Python class definitions
        r"\n\ndef ",  # Python function definitions
        r"\n## ",  # Markdown headers
        r"\n\n---\n",  # Section separators
        r"\n\n",  # Paragraph breaks
        r"\n",  # Line breaks (fallback)
    ]

    chunks = []
    remaining = content

    while remaining:
        if _estimate_tokens(remaining) <= max_chunk_tokens:
            chunks.append(remaining)
            break

        # Find best split point
        max_chars = int(max_chunk_tokens * 4)  # Rough chars estimate
        search_region = remaining[:max_chars]

        split_point = None
        for pattern in boundaries:
            matches = list(re.finditer(pattern, search_region))
            if matches:
                # Use the last match in the region
                split_point = matches[-1].start()
                break

        if split_point is None or split_point == 0:
            # Fallback: split at max_chars
            split_point = max_chars

        chunks.append(remaining[:split_point])
        remaining = remaining[split_point:].lstrip()

    return chunks


def _call_ollama(prompt: str, model: str, timeout: float = OLLAMA_TIMEOUT) -> str:
    """Call Ollama API and return the response text."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                OLLAMA_GENERATE_ENDPOINT,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            return response.json().get("response", "")

    except httpx.ConnectError as e:
        logger.error(f"Failed to connect to Ollama: {e}")
        raise SubagentUnavailableError("Ollama service unavailable") from e

    except httpx.TimeoutException as e:
        logger.warning(f"Ollama request timed out, retrying once...")
        # Retry once
        try:
            with httpx.Client(timeout=timeout * 1.5) as client:
                response = client.post(
                    OLLAMA_GENERATE_ENDPOINT,
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                return response.json().get("response", "")
        except Exception as retry_error:
            logger.error(f"Ollama retry failed: {retry_error}")
            raise SubagentUnavailableError("Ollama request timed out after retry") from e

    except httpx.HTTPStatusError as e:
        logger.error(f"Ollama HTTP error: {e}")
        raise SubagentUnavailableError(f"Ollama returned error: {e.response.status_code}") from e


def summarize_content(
    content: str,
    max_tokens: int = 200,
    model: str = DEFAULT_MODEL,
    context: str | None = None,
) -> SummarizeResult:
    """Summarize content using Ollama, respecting token limits.

    Args:
        content: The content to summarize
        max_tokens: Maximum tokens in the summary
        model: Ollama model to use
        context: Optional context to help guide summarization

    Returns:
        SummarizeResult with summary, token count, and metadata
    """
    content_tokens = _estimate_tokens(content)

    # If content is already under both token and character limits, return verbatim
    if content_tokens <= max_tokens and len(content) <= MAX_SUMMARY_CHARS:
        return SummarizeResult(
            summary=content,
            token_count=content_tokens,
            was_compressed=False,
            model_used=model,
            confidence=1.0,
        )

    # Handle large content with chunking
    if len(content) > LARGE_CONTENT_THRESHOLD:
        return _summarize_large_content(content, max_tokens, model, context)

    # Standard summarization
    prompt = _build_summarization_prompt(content, max_tokens, context)

    try:
        response_text = _call_ollama(prompt, model)
        summary, confidence = _parse_llm_response(response_text)

        # Ensure summary is within token and character limits
        summary = _truncate_to_tokens(summary, max_tokens)
        summary = _truncate_to_chars(summary)
        summary_tokens = _estimate_tokens(summary)

        return SummarizeResult(
            summary=summary,
            token_count=summary_tokens,
            was_compressed=True,
            model_used=model,
            confidence=confidence,
        )

    except SubagentUnavailableError:
        # Return a truncated version as fallback
        logger.warning("Ollama unavailable, returning truncated content as summary")
        summary = _truncate_to_tokens(content, max_tokens)
        summary = _truncate_to_chars(summary)
        return SummarizeResult(
            summary=summary,
            token_count=_estimate_tokens(summary),
            was_compressed=True,
            model_used="truncation-fallback",
            confidence=0.3,
        )


def _summarize_large_content(
    content: str,
    max_tokens: int,
    model: str,
    context: str | None = None,
) -> SummarizeResult:
    """Summarize content larger than threshold using hierarchical approach."""
    chunks = _chunk_content(content)
    logger.info(f"Processing large content in {len(chunks)} chunks")

    # Phase 1: Summarize each chunk
    chunk_summaries = []
    total_confidence = 0.0

    for i, chunk in enumerate(chunks):
        chunk_prompt = _build_summarization_prompt(
            chunk,
            max_tokens=300,  # Slightly larger for intermediate
            context=f"Chunk {i + 1} of {len(chunks)}. {context or ''}",
        )

        try:
            response_text = _call_ollama(chunk_prompt, model)
            summary, confidence = _parse_llm_response(response_text)
            chunk_summaries.append(summary)
            total_confidence += confidence
        except SubagentUnavailableError:
            chunk_summaries.append(_truncate_to_tokens(chunk, 100))
            total_confidence += 0.3

    # Phase 2: Merge summaries into final
    combined = "\n---\n".join(chunk_summaries)
    merge_prompt = f"""Synthesize these section summaries into a coherent overview of under {max_tokens} tokens.

Format your response as:
SUMMARY: <your summary>
CONFIDENCE: <0.0-1.0>

Section summaries:
{combined}"""

    try:
        response_text = _call_ollama(merge_prompt, model)
        final_summary, merge_confidence = _parse_llm_response(response_text)

        # Average confidence across chunks and merge
        avg_confidence = (total_confidence / len(chunks) + merge_confidence) / 2

    except SubagentUnavailableError:
        final_summary = _truncate_to_tokens(combined, max_tokens)
        avg_confidence = 0.3

    final_summary = _truncate_to_tokens(final_summary, max_tokens)
    final_summary = _truncate_to_chars(final_summary)

    return SummarizeResult(
        summary=final_summary,
        token_count=_estimate_tokens(final_summary),
        was_compressed=True,
        model_used=model,
        confidence=avg_confidence,
    )


def check_ollama_health() -> bool:
    """Check if Ollama service is available."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return response.status_code == 200
    except Exception:
        return False
