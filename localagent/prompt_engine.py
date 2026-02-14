"""Dynamic prompt generation for subagent tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from localagent.schemas import DelegationRequest, InputRefType, ToolName


@dataclass
class PromptModifiers:
    """Detected characteristics of the input."""

    is_code: bool = False
    is_logs: bool = False
    is_docs: bool = False
    size_class: str = "small"  # small, medium, large
    language: str | None = None  # python, js, prose, etc.


def _detect_code_patterns(input_refs: list[dict[str, Any]]) -> bool:
    """Detect if input references are code files."""
    code_extensions = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp"}
    for ref in input_refs:
        if ref.get("type") == InputRefType.GLOB.value:
            pattern = ref.get("value", "")
            for ext in code_extensions:
                if ext in pattern:
                    return True
    return False


def _detect_log_patterns(input_refs: list[dict[str, Any]]) -> bool:
    """Detect if input references are log files."""
    log_indicators = {".log", "logs/", "log/", "syslog", "error.log", "access.log"}
    for ref in input_refs:
        if ref.get("type") == InputRefType.GLOB.value:
            pattern = ref.get("value", "").lower()
            for indicator in log_indicators:
                if indicator in pattern:
                    return True
    return False


def _detect_docs_patterns(input_refs: list[dict[str, Any]]) -> bool:
    """Detect if input references are documentation files."""
    doc_extensions = {".md", ".rst", ".txt", ".adoc", "README", "CHANGELOG"}
    for ref in input_refs:
        if ref.get("type") == InputRefType.GLOB.value:
            pattern = ref.get("value", "")
            for ext in doc_extensions:
                if ext in pattern:
                    return True
    return False


def _classify_size(input_refs: list[dict[str, Any]]) -> str:
    """Classify input size based on content length or pattern scope."""
    for ref in input_refs:
        if ref.get("type") == InputRefType.CONTENT.value:
            content_len = len(ref.get("value", ""))
            if content_len > 50000:
                return "large"
            elif content_len > 10000:
                return "medium"
    return "small"


def _detect_language(input_refs: list[dict[str, Any]]) -> str | None:
    """Detect programming language from file patterns."""
    language_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
    }
    for ref in input_refs:
        if ref.get("type") == InputRefType.GLOB.value:
            pattern = ref.get("value", "")
            for ext, lang in language_map.items():
                if ext in pattern:
                    return lang
    return None


def _analyze_input(input_refs: list[dict[str, Any]]) -> PromptModifiers:
    """Analyze input references to determine prompt modifiers."""
    # Convert InputRef objects to dicts if needed
    refs = []
    for ref in input_refs:
        if hasattr(ref, "model_dump"):
            refs.append(ref.model_dump())
        elif hasattr(ref, "dict"):
            refs.append(ref.dict())
        else:
            refs.append(ref)

    return PromptModifiers(
        is_code=_detect_code_patterns(refs),
        is_logs=_detect_log_patterns(refs),
        is_docs=_detect_docs_patterns(refs),
        size_class=_classify_size(refs),
        language=_detect_language(refs),
    )


def generate_prompt(
    task: DelegationRequest,
    content: str | None = None,
) -> str:
    """Generate an optimal prompt based on task type and context.

    Args:
        task: The delegation request
        content: Optional content to include in the prompt

    Returns:
        Generated prompt string
    """
    # Convert input_refs for analysis
    refs = [ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in task.input_refs]
    modifiers = _analyze_input(refs)

    # Build base prompt based on tool type
    if task.tool_name == ToolName.FILE_SCANNER:
        prompt = _build_file_scanner_prompt(task, modifiers)
    elif task.tool_name == ToolName.SUMMARIZER:
        prompt = _build_summarizer_prompt(task, modifiers, content)
    elif task.tool_name == ToolName.BASH_RUNNER:
        prompt = _build_bash_runner_prompt(task, modifiers)
    else:
        prompt = _build_generic_prompt(task, content)

    return prompt


def _build_file_scanner_prompt(task: DelegationRequest, modifiers: PromptModifiers) -> str:
    """Build prompt for file scanner tasks."""
    parts = ["Scan and analyze the following files."]

    if modifiers.is_code:
        parts.append("Focus on: function signatures, class hierarchies, import dependencies.")
        if modifiers.language:
            parts.append(f"Language: {modifiers.language}")
    elif modifiers.is_logs:
        parts.append("Focus on: error patterns, frequency, affected components, timestamps.")
    elif modifiers.is_docs:
        parts.append("Focus on: section structure, key concepts, TODOs, links.")

    parts.append(f"Summarize findings in under {task.max_summary_tokens} tokens.")

    return " ".join(parts)


def _build_summarizer_prompt(
    task: DelegationRequest,
    modifiers: PromptModifiers,
    content: str | None,
) -> str:
    """Build prompt for summarizer tasks."""
    parts = []

    if modifiers.size_class == "large":
        parts.append("Provide a hierarchical summary: overview first, then key details.")
    elif modifiers.size_class == "small":
        parts.append("Preserve technical precision with minimal compression.")
    else:
        parts.append("Summarize the key points.")

    if modifiers.is_code:
        parts.append("Focus on: purpose, key functions, dependencies, notable patterns.")
    elif modifiers.is_logs:
        parts.append("Focus on: error summary, affected services, timeline, root causes if apparent.")
    elif modifiers.is_docs:
        parts.append("Focus on: main topics, action items, key decisions.")

    parts.append(f"Keep summary under {task.max_summary_tokens} tokens.")
    parts.append("")
    parts.append("After summarizing, rate your confidence from 0.0 to 1.0:")
    parts.append("- 0.9-1.0: Complete understanding, captured all key points")
    parts.append("- 0.7-0.9: Good coverage, may have missed minor details")
    parts.append("- 0.5-0.7: Partial understanding, significant ambiguity")
    parts.append("- <0.5: Uncertain, content unclear or outside training")
    parts.append("")
    parts.append("Format your response as:")
    parts.append("SUMMARY: <your summary>")
    parts.append("CONFIDENCE: <0.0-1.0>")

    if content:
        parts.append("")
        parts.append("Content to summarize:")
        parts.append(content)

    return "\n".join(parts)


def _build_bash_runner_prompt(task: DelegationRequest, modifiers: PromptModifiers) -> str:
    """Build prompt for bash runner tasks."""
    parts = ["Execute the command in a sandboxed environment."]
    parts.append("Output should not include secrets or sensitive information.")
    parts.append(f"Maximum output length: 10KB (will be truncated).")

    return " ".join(parts)


def _build_generic_prompt(task: DelegationRequest, content: str | None) -> str:
    """Build generic prompt for unknown task types."""
    parts = [f"Process the following task: {task.tool_name.value}"]
    parts.append(f"Maximum summary tokens: {task.max_summary_tokens}")

    if content:
        parts.append("")
        parts.append("Content:")
        parts.append(content)

    return "\n".join(parts)
