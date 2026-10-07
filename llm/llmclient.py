# import google.generativeai as genai

import asyncio
import json
import re
import os
import sys
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Optional

from dotenv import load_dotenv
import openai
from langchain_core.messages import AIMessageChunk
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI

from tools import TOOLS

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)


load_dotenv()


def force_utf8_console() -> None:
    """Make console output tolerate model text outside the local codepage.

    Windows shells default to cp1252, so a single emoji or arrow in streamed
    model output otherwise raises UnicodeEncodeError and kills the run
    mid-stream. Streams differ across launchers (redirected pipes, IDE
    runners, pytest capture) and some expose no ``reconfigure`` at all, so a
    stream that cannot be adjusted is left alone rather than allowed to break
    the run.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


force_utf8_console()


StreamListener = Any
_stream_listener: ContextVar[StreamListener | None] = ContextVar(
    "tia_stream_listener",
    default=None,
)


def set_stream_listener(listener: StreamListener | None):
    return _stream_listener.set(listener)


def reset_stream_listener(token) -> None:
    _stream_listener.reset(token)


# =============================================================
# OMNIROUTE OPENAI-COMPATIBLE CLIENT
# =============================================================


_OMNIROUTE_DEFAULT_BASE_URL = "http://127.0.0.1:20128/v1"


def _omniroute_base_url() -> str:
    """Return the chat-completions base URL expected by OmniRoute."""

    base_url = os.getenv(
        "OMNIROUTE_BASE_URL",
        _OMNIROUTE_DEFAULT_BASE_URL,
    ).rstrip("/")

    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


@lru_cache(maxsize=8)
def _parse_omniroute_model_map(raw_model_map: str) -> dict[str, str]:
    """Decode and validate ``OMNIROUTE_MODEL_MAP``.

    Cached on the raw string so the map is parsed once per distinct
    configuration instead of on every request.
    """

    if not raw_model_map:
        return {}

    try:
        model_map = json.loads(raw_model_map)
    except json.JSONDecodeError as error:
        raise ValueError(
            "OMNIROUTE_MODEL_MAP must be a JSON object mapping TIA model "
            "IDs to OmniRoute model IDs, for example "
            '{"openai/gpt-oss-20b": "cfp/openai/gpt-oss-20b"}. '
            f"JSON decode failed: {error}"
        ) from error

    if not isinstance(model_map, dict):
        raise ValueError(
            "OMNIROUTE_MODEL_MAP must be a JSON object mapping TIA model "
            "IDs to OmniRoute model IDs, for example "
            '{"openai/gpt-oss-20b": "cfp/openai/gpt-oss-20b"}.'
        )

    return model_map


# Model IDs already announced as unmapped, so a long run warns once per model
# instead of on every request.
_UNMAPPED_MODEL_WARNED: set[str] = set()


def _omniroute_model(model: str) -> str:
    """Map legacy TIA model names to explicit OmniRoute targets when configured.

    TIA's existing call sites already use provider-prefixed model IDs (for
    example ``nvidia/nemotron-...``).  Passing those IDs through keeps each
    role on its intended provider.  ``OMNIROUTE_MODEL_MAP`` is an optional JSON
    object for deployments whose provider catalog uses different IDs; a map
    value may also be a configured OmniRoute combo/auto route.
    """

    model_map = _parse_omniroute_model_map(
        os.getenv("OMNIROUTE_MODEL_MAP", "")
    )

    if model not in model_map and model not in _UNMAPPED_MODEL_WARNED:
        _UNMAPPED_MODEL_WARNED.add(model)
        print(
            f"\n⚠️ [OmniRoute] No OMNIROUTE_MODEL_MAP entry for {model!r}; "
            "sending the raw ID. Add a mapping in .env if OmniRoute rejects "
            "it (TIA's catalog uses mapped targets such as "
            '"cfp/openai/gpt-oss-20b").'
        )

    mapped_model = model_map.get(model, model)
    if not isinstance(mapped_model, str) or not mapped_model.strip():
        raise ValueError(
            f"OMNIROUTE_MODEL_MAP entry for {model!r} must be a non-empty string."
        )

    return mapped_model.strip()


def _omniroute_reasoning_content(delta: dict[str, Any]) -> str:
    """Extract reasoning emitted by the common OpenAI-compatible shapes."""

    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning

    details = delta.get("reasoning_details")
    if not isinstance(details, list):
        return ""

    return "".join(
        detail.get("text", "")
        for detail in details
        if isinstance(detail, dict)
    )


def _omniroute_api_key() -> str:
    """Bearer token expected by the local OmniRoute gateway."""

    return (
        os.getenv("OMNIROUTE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "omniroute"
    )


class _OmniRouteChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps OmniRoute's non-standard reasoning fields.

    ChatOpenAI only extracts fields defined by the official OpenAI
    specification, so ``reasoning_content``/``reasoning``/``reasoning_details``
    from reasoning models behind the gateway would be dropped and the live
    thinking stream would go silent. Subclassing leaves every other behaviour
    (callbacks -> LangSmith tracing, tool calling, retries) untouched.
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )

        if generation_chunk is None:
            return None

        choices = chunk.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}

        reasoning = _omniroute_reasoning_content(delta)
        if reasoning and isinstance(generation_chunk.message, AIMessageChunk):
            generation_chunk.message.additional_kwargs["reasoning_content"] = (
                reasoning
            )

        return generation_chunk


def _omniroute_chat(
    model: str,
    *,
    temperature: float = 0.2,
    timeout: float = 60,
    stream_timeout: float = 600,
    top_p: float = 0.95,
    max_completion_tokens: int = 16384,
) -> ChatOpenAI:
    """Build a ChatOpenAI client wired to the local OmniRoute gateway.

    ``timeout`` is the HTTP read budget, which must be far larger for
    streaming than for a plain request because a reasoning model can stay
    silent while it works; ``stream_timeout`` is the silence allowed between
    two streamed chunks. SDK-level retries are disabled so the tenacity
    wrapper around ``_aexecute_nvidia_call`` stays the single retry layer and
    its restart banner keeps matching the restarted output.
    """

    return _OmniRouteChatOpenAI(
        name=f"omniroute/{model}",
        model=_omniroute_model(model),
        base_url=_omniroute_base_url(),
        api_key=_omniroute_api_key(),
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_completion_tokens,
        timeout=timeout,
        stream_chunk_timeout=stream_timeout,
        stream_usage=False,
        max_retries=0,
    )


# ==============================================================
# LLM CALL HELPERS
# ==============================================================


# def call_groq(
#     prompt: str,
#     subagent=False,
#     state_model=None,
# ) -> str:

#     llm = ChatGroq(
#         model="groq/compound-mini",
#         temperature=1.0,
#         max_tokens=1024,
#     )

#     if subagent:
#         structured_llm = llm.with_structured_output(
#             state_model
#         )

#         action = structured_llm.invoke(
#             [HumanMessage(content=prompt)]
#         )

#         return action

#     res = llm.invoke(
#         [HumanMessage(content=prompt)]
#     )

#     return res.content


# ==============================================================
# STRUCTURED OUTPUT CLEANING
# ==============================================================


def _remove_thinking_blocks(content: str) -> str:
    """
    Remove common reasoning/thinking blocks emitted by local
    reasoning models.

    Handles:
        <think>...</think>
        <thinking>...</thinking>
        <reasoning>...</reasoning>
    """

    if not content:
        return ""

    cleaned = content

    patterns = (
        r"<think>.*?</think>",
        r"<thinking>.*?</thinking>",
        r"<reasoning>.*?</reasoning>",
    )

    for pattern in patterns:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )

    return cleaned.strip()


def _remove_markdown_fences(content: str) -> str:
    """
    Remove markdown code fences without assuming that the entire
    response consists of a single fenced block.
    """

    if not content:
        return ""

    cleaned = content.strip()

    cleaned = re.sub(
        r"```(?:json|JSON)?\s*",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"\s*```",
        "",
        cleaned,
    )

    return cleaned.strip()


def _normalize_structured_output(content: str) -> str:
    """
    Perform safe, non-semantic normalization before parsing.
    """

    if not content:
        return ""

    cleaned = _remove_thinking_blocks(content)

    cleaned = _remove_markdown_fences(cleaned)

    # Remove common leading labels.
    cleaned = re.sub(
        r"^\s*(?:json|JSON)\s*:\s*",
        "",
        cleaned,
    )

    return cleaned.strip()


# ==============================================================
# BALANCED JSON EXTRACTION
# ==============================================================


def _extract_balanced_json_candidates(
    content: str,
) -> list[str]:
    """
    Extract balanced JSON objects/arrays from arbitrary model text.

    Unlike:

        re.search(r"({.*})", ...)

    this parser understands:
        - nested objects
        - nested arrays
        - braces inside JSON strings
        - escaped quotes
        - multiple JSON candidates
    """

    candidates: list[str] = []

    if not content:
        return candidates

    opening_to_closing = {
        "{": "}",
        "[": "]",
    }

    stack: list[str] = []

    start_index: Optional[int] = None

    in_string = False
    escaped = False

    for index, char in enumerate(content):

        if in_string:

            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char in opening_to_closing:

            if not stack:
                start_index = index

            stack.append(
                opening_to_closing[char]
            )

            continue

        if char in "}]":

            if not stack:
                continue

            if char != stack[-1]:

                # Invalid nesting. Reset this candidate.
                stack.clear()
                start_index = None
                continue

            stack.pop()

            if not stack and start_index is not None:

                candidate = content[
                    start_index : index + 1
                ].strip()

                if candidate:
                    candidates.append(candidate)

                start_index = None

    return candidates


# ==============================================================
# JSON CANDIDATE VALIDATION
# ==============================================================


def _try_json_loads(
    candidate: str,
) -> Optional[Any]:
    """
    Safely decode one JSON candidate.
    """

    try:
        return json.loads(candidate)

    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None


def _validate_candidate(
    parser: PydanticOutputParser,
    candidate: str,
):
    """
    Convert a JSON candidate into the requested Pydantic model.
    """

    data = _try_json_loads(candidate)

    if data is None:
        return None

    try:
        return parser.pydantic_object.model_validate(
            data
        )

    except Exception:
        return None


# ==============================================================
# ROBUST STRUCTURED OUTPUT PARSER
# ==============================================================


async def _robust_pydantic_parse_async(
    parser: PydanticOutputParser,
    raw_content: str,
    llm_instance=None,
    original_prompt: str = "",
):
    """
    Robust async parser for LLM structured output.

    Parsing strategy:

        1. Direct Pydantic parser
        2. Normalized direct Pydantic parser
        3. Direct JSON decode
        4. Balanced JSON extraction
        5. Candidate-by-candidate Pydantic validation
        6. Bounded healing attempt 1
        7. Bounded healing attempt 2
        8. Raise OutputParserException

    The parser never silently fabricates missing data.
    """

    if not raw_content:
        raw_content = ""

    # ----------------------------------------------------------
    # Preserve original output for diagnostics.
    # ----------------------------------------------------------

    original_content = raw_content

    # ----------------------------------------------------------
    # Stage 1
    # Direct parser
    # ----------------------------------------------------------

    try:
        return parser.parse(
            raw_content.strip()
        )

    except Exception:
        pass

    # ----------------------------------------------------------
    # Stage 2
    # Normalize reasoning/fences/labels.
    # ----------------------------------------------------------

    normalized_content = (
        _normalize_structured_output(
            raw_content
        )
    )

    if normalized_content:

        try:
            return parser.parse(
                normalized_content
            )

        except Exception:
            pass

    # ----------------------------------------------------------
    # Stage 3
    # Try the entire normalized response as JSON.
    # ----------------------------------------------------------

    if normalized_content:

        decoded = _try_json_loads(
            normalized_content
        )

        if decoded is not None:

            try:
                return parser.pydantic_object.model_validate(
                    decoded
                )

            except Exception:
                pass

    # ----------------------------------------------------------
    # Stage 4
    # Extract balanced JSON candidates.
    # ----------------------------------------------------------

    candidates = (
        _extract_balanced_json_candidates(
            normalized_content
        )
    )

    # Prefer larger candidates first.
    candidates.sort(
        key=len,
        reverse=True,
    )

    for candidate in candidates:

        parsed = _validate_candidate(
            parser,
            candidate,
        )

        if parsed is not None:
            return parsed

    # ----------------------------------------------------------
    # Stage 5
    # Healing
    # ----------------------------------------------------------

    if llm_instance and original_prompt:

        print(
            "\n🔄 [Parsing Failure] "
            "Structured output could not be parsed. "
            "Starting automatic healing..."
        )

        healed = await _heal_structured_output_async(
            parser=parser,
            llm_instance=llm_instance,
            original_prompt=original_prompt,
            raw_content=original_content,
        )

        if healed is not None:
            return healed

    raise OutputParserException(
        "Failed to parse or heal structured output.\n\n"
        f"Raw model output:\n{original_content}"
    )


# ==============================================================
# STRUCTURED OUTPUT HEALER
# ==============================================================


async def _heal_structured_output_async(
    parser: PydanticOutputParser,
    llm_instance,
    original_prompt: str,
    raw_content: str,
):
    """
    Multi-stage bounded structured-output healer.

    Attempt 1:
        Repair the exact malformed response.

    Attempt 2:
        Reconstruct the required schema from the original
        response while preserving its information.

    Every healed response is passed through the same local
    deterministic parser before being accepted.
    """

    format_instructions = (
        parser.get_format_instructions()
    )

    # ==========================================================
    # HEALING ATTEMPT 1
    # Precise repair
    # ==========================================================

    repair_prompt = f"""
You are a JSON repair engine.

Your task is to repair the model output below so that it becomes
valid JSON matching the required Pydantic schema.

IMPORTANT RULES:

1. Preserve the original information.
2. Do not invent facts.
3. Do not remove required information.
4. Do not explain your changes.
5. Do not include markdown.
6. Do not include code fences.
7. Return ONLY the JSON object.
8. The result must be valid JSON.
9. Follow the schema exactly.

REQUIRED SCHEMA:
{format_instructions}

ORIGINAL REQUEST:
{original_prompt}

MALFORMED MODEL OUTPUT:
{raw_content}

Return ONLY the corrected JSON object.
""".strip()

    try:

        repair_response = (
            await llm_instance.ainvoke(
                repair_prompt
            )
        )

        repaired_content = getattr(
            repair_response,
            "content",
            "",
        )

        parsed = _parse_healed_content(
            parser,
            repaired_content,
        )

        if parsed is not None:

            print(
                "✅ [Healing] "
                "Structured output repaired successfully "
                "on attempt 1."
            )

            return parsed

    except Exception as repair_error:

        print(
            "⚠️ [Healing Attempt 1 Failed] "
            f"{repair_error}"
        )

    # ==========================================================
    # HEALING ATTEMPT 2
    # Schema reconstruction
    # ==========================================================

    reconstruction_prompt = f"""
You are a strict structured-output reconstruction engine.

The previous model response failed schema validation.

Reconstruct the response using ONLY information contained in
the original model output.

Do NOT:
- invent information,
- add assumptions,
- add explanations,
- add markdown,
- add code fences,
- change the meaning,
- omit information that is required by the schema.

You MUST:
- produce one valid JSON object,
- satisfy the schema,
- preserve the original meaning,
- use null/default values only where the schema explicitly allows
  them.

REQUIRED SCHEMA:
{format_instructions}

ORIGINAL REQUEST:
{original_prompt}

PREVIOUS MODEL OUTPUT:
{raw_content}

Return ONLY the final JSON object.
""".strip()

    try:

        reconstruction_response = (
            await llm_instance.ainvoke(
                reconstruction_prompt
            )
        )

        reconstructed_content = getattr(
            reconstruction_response,
            "content",
            "",
        )

        parsed = _parse_healed_content(
            parser,
            reconstructed_content,
        )

        if parsed is not None:

            print(
                "✅ [Healing] "
                "Structured output reconstructed successfully "
                "on attempt 2."
            )

            return parsed

    except Exception as reconstruction_error:

        print(
            "⚠️ [Healing Attempt 2 Failed] "
            f"{reconstruction_error}"
        )

    print(
        "❌ [Healing Failed] "
        "All structured-output healing attempts failed."
    )

    return None


def _parse_healed_content(
    parser: PydanticOutputParser,
    content: str,
):
    """
    Parse healed model output using the same robust local
    extraction rules as normal model output.
    """

    if not content:
        return None

    normalized = (
        _normalize_structured_output(
            content
        )
    )

    # ----------------------------------------------------------
    # Direct Pydantic parsing
    # ----------------------------------------------------------

    try:
        return parser.parse(
            normalized
        )

    except Exception:
        pass

    # ----------------------------------------------------------
    # Entire-response JSON
    # ----------------------------------------------------------

    decoded = _try_json_loads(
        normalized
    )

    if decoded is not None:

        try:
            return parser.pydantic_object.model_validate(
                decoded
            )

        except Exception:
            pass

    # ----------------------------------------------------------
    # Balanced candidates
    # ----------------------------------------------------------

    candidates = (
        _extract_balanced_json_candidates(
            normalized
        )
    )

    candidates.sort(
        key=len,
        reverse=True,
    )

    for candidate in candidates:

        parsed = _validate_candidate(
            parser,
            candidate,
        )

        if parsed is not None:
            return parsed

    return None


# ==============================================================
# STREAMING
# ==============================================================


async def _stream_llm_response(
    llm,
    prompt: str,
    show_reasoning: bool = True,
    model_label: str = "model",
) -> str:
    """
    Stream an LLM response live while accumulating the final
    content.
    """

    full_content = ""
    tagged_reasoning = ""
    listener = _stream_listener.get()

    if listener is not None:
        listener("started", model_label, "")

    async for chunk in llm.astream(
        prompt
    ):

        additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
        reasoning_chunk = additional_kwargs.get("reasoning_content")
        if not reasoning_chunk:
            reasoning_chunk = getattr(chunk, "reasoning_content", None)

        if (
            show_reasoning
            and reasoning_chunk
        ):
            print(
                reasoning_chunk,
                end="",
                flush=True,
            )
            if listener is not None:
                listener("chunk", model_label, str(reasoning_chunk))

        content = getattr(chunk, "content", "") or ""
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )

        if content:

            tagged_reasoning += content
            for match in re.finditer(
                r"<(?:think|thinking|reasoning)>(.*?)</(?:think|thinking|reasoning)>",
                tagged_reasoning,
                flags=re.DOTALL | re.IGNORECASE,
            ):
                if listener is not None and match.group(1).strip():
                    listener("chunk", model_label, match.group(1).strip())
                tagged_reasoning = tagged_reasoning[match.end():]

            if len(tagged_reasoning) > 4096:
                tagged_reasoning = tagged_reasoning[-4096:]

            print(
                content,
                end="",
                flush=True,
            )

            full_content += content

    if listener is not None:
        listener("finished", model_label, "")

    return full_content


# ==============================================================
# OLLAMA
# ==============================================================


class OllamaMemoryError(Exception):
    """Raised when llama-server cannot allocate memory while loading a model
    and the automatic recovery sequence was exhausted."""


_MEMORY_ERROR_PATTERNS = (
    "out of memory",
    "out-of-memory",
    "failed to allocate",
    "unable to allocate",
    "alloc_tensor_range",
    "cuda_host",
    "llama_memory",
)


def _is_memory_error(message: str) -> bool:
    lowered = message.lower()
    return any(pattern in lowered for pattern in _MEMORY_ERROR_PATTERNS)


def _is_connection_error(message: str) -> bool:
    return (
        "All connection attempts failed" in message
        or "Connection refused" in message
        or "ConnectError" in message
        or "connect_error" in message
    )


_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _unload_ollama_models() -> int:
    """Ask the local Ollama server to unload every loaded model to free RAM/VRAM."""
    try:
        tags = requests.get(f"{_OLLAMA_BASE_URL}/api/tags", timeout=5).json()
        count = 0
        for model in tags.get("models", []):
            name = model.get("name")
            if not name:
                continue
            try:
                requests.post(
                    f"{_OLLAMA_BASE_URL}/api/generate",
                    json={"model": name, "keep_alive": 0},
                    timeout=30,
                )
                count += 1
            except Exception:
                continue
        return count
    except Exception:
        return 0


async def _recover_from_ollama_memory_error(
    prompt: str,
    model: str,
    subagent: bool,
    state_model: Any,
    tool: bool,
) -> str:
    """Recover from a llama-server out-of-memory failure by freeing memory and
    retrying with progressively reduced resource settings, so the agent run
    is not interrupted."""

    print(
        "\n[TIA] llama-server reported out-of-memory during model load -- "
        "starting automatic recovery...\n"
    )

    last_error: Exception | None = None

    unloaded = await asyncio.to_thread(_unload_ollama_models)
    await asyncio.sleep(2)
    print(
        f"[TIA] Recovery 1/3: unloaded {unloaded} model(s) to free memory, "
        "retrying with original settings...\n"
    )
    try:
        return await _execute_ollama_call(prompt, model, subagent, state_model, tool)
    except Exception as retry_error:
        last_error = retry_error
        if not _is_memory_error(str(retry_error)):
            raise

    print(
        "[TIA] Recovery 2/3: retrying with num_gpu=0, num_ctx=8192 "
        "(CPU-only, reduced context)...\n"
    )
    try:
        return await _execute_ollama_call(
            prompt, model, subagent, state_model, tool, num_gpu=0, num_ctx=8192
        )
    except Exception as retry_error:
        last_error = retry_error
        if not _is_memory_error(str(retry_error)):
            raise

    print(
        "[TIA] Recovery 3/3: retrying with num_gpu=0, num_ctx=4096 "
        "(CPU-only, minimal context)...\n"
    )
    try:
        return await _execute_ollama_call(
            prompt, model, subagent, state_model, tool, num_gpu=0, num_ctx=4096
        )
    except Exception as retry_error:
        last_error = retry_error
        if not _is_memory_error(str(retry_error)):
            raise

    raise OllamaMemoryError(
        "llama-server out-of-memory persists after automatic recovery "
        "(models unloaded + num_gpu/num_ctx downgrades). "
        "Free host RAM/VRAM or switch to a smaller model."
    ) from last_error


@retry(
    retry=retry_if_exception_type(ConnectionError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(
        multiplier=1,
        min=2,
        max=6,
    ),
    reraise=True,
)
async def call_ollama(
    prompt: str,
    model: str,
    subagent=False,
    state_model=None,
    tool=False,
) -> str:

    try:

        return await _execute_ollama_call(
            prompt,
            model,
            subagent,
            state_model,
            tool,
        )

    except Exception as e:

        message = str(e)

        if _is_connection_error(message):
            raise ConnectionError(
                "Ollama is not reachable at http://127.0.0.1:11434 -- "
                "restart run_tia.ps1 (it auto-starts Ollama) "
                "or run 'ollama serve' manually."
            ) from e

        if not _is_memory_error(message):
            raise

    return await _recover_from_ollama_memory_error(
        prompt,
        model,
        subagent,
        state_model,
        tool,
    )


async def _execute_ollama_call(
    prompt: str,
    model: str,
    subagent=False,
    state_model=None,
    tool=False,
    num_ctx: int = 16352,
    num_gpu: int = 99,
) -> str:

    llm = ChatOllama(
        model=model.lower(),
        temperature=0.0,
        num_ctx=num_ctx,
        num_predict=2048,
        num_gpu=num_gpu,
        # low_vram=True,
        keep_alive=0,
        reasoning=False,
    )

    # ----------------------------------------------------------
    # Structured subagent output
    # ----------------------------------------------------------

    if subagent and state_model:

        parser = PydanticOutputParser(
            pydantic_object=state_model
        )

        structured_prompt = (
            "nothink\n"
            + prompt
            + "\n\n"
            + parser.get_format_instructions()
        )

        print(
            f"\n🧠 [{model}] "
            "Thinking process started:\n"
        )

        full_content = (
            await _stream_llm_response(
                llm=llm,
                prompt=structured_prompt,
                show_reasoning=True,
                model_label=model,
            )
        )

        print(
            "\n\n🏁 Thinking finished. "
            "Validating structure..."
        )

        return await _robust_pydantic_parse_async(
            parser=parser,
            raw_content=full_content,
            llm_instance=llm,
            original_prompt=structured_prompt,
        )

    # ----------------------------------------------------------
    # Tool-enabled invocation
    # ----------------------------------------------------------

    # if tool:

    #     res = await llm.ainvoke(
    #         prompt
    #     )

    #     print(
    #         f"\nFULL CONTENT--> {res}\n"
    #     )

    #     return res

    # ----------------------------------------------------------
    # Standard streamed output
    # ----------------------------------------------------------

    return await _stream_llm_response(
        llm=llm,
        prompt=prompt,
        show_reasoning=True,
        model_label=model,
    )


# ==============================================================
# NVIDIA
# ==============================================================


def _log_omniroute_retry(retry_state) -> None:
    """Announce a retry so restarted stream output is not mistaken for a
    continuation of the previous attempt."""

    error = retry_state.outcome.exception()
    print(
        "\n🔄 [OmniRoute] Transient transport failure on "
        f"attempt {retry_state.attempt_number}. Retrying... "
        f"Reason: {error}"
    )


@retry(
    retry=retry_if_exception_type(
        (
            openai.APIConnectionError,
            TimeoutError,
        )
    ),
    stop=stop_after_attempt(2),
    wait=wait_exponential(
        multiplier=2,
        min=2,
        max=6,
    ),
    before_sleep=_log_omniroute_retry,
    reraise=True,
)
async def _aexecute_nvidia_call(
    prompt,
    model,
    subagent,
    state_model,
    tool,
):

    stream_llm = _omniroute_chat(
        model,
        timeout=600,
    )

    invoke_llm = _omniroute_chat(
        model,
    )

    # ----------------------------------------------------------
    # Structured output
    # ----------------------------------------------------------

    if subagent and state_model:

        parser = PydanticOutputParser(
            pydantic_object=state_model
        )

        structured_prompt = (
            prompt
            + "\n\n"
            + parser.get_format_instructions()
        )

        print(
            f"\n🧠 [{model}] "
            "Thinking process started:\n"
        )

        full_content = (
            await _stream_llm_response(
                llm=stream_llm,
                prompt=structured_prompt,
                show_reasoning=True,
                model_label=model,
            )
        )

        print(
            "\n\n🏁 Thinking finished. "
            "Validating structure..."
        )

        return await _robust_pydantic_parse_async(
            parser=parser,
            raw_content=full_content,
            llm_instance=invoke_llm,
            original_prompt=structured_prompt,
        )

    # ----------------------------------------------------------
    # Tool call
    # ----------------------------------------------------------

    if tool:

        llm_with_tools = invoke_llm.bind_tools(
            TOOLS
        )

        return await llm_with_tools.ainvoke(
            prompt
        )

    # ----------------------------------------------------------
    # Standard streamed output
    # ----------------------------------------------------------

    return await _stream_llm_response(
        llm=stream_llm,
        prompt=prompt,
        show_reasoning=True,
        model_label=model,
    )


_OMNIROUTE_FALLBACK_MODEL = "openai/gpt-oss-20b"


async def call_nvidia(
    prompt: str,
    model: str,
    subagent=False,
    state_model=None,
    tool=False,
    *,
    allow_fallback: bool = True,
):
    """Run a prompt through OmniRoute, degrading to a fallback model once.

    Failures that are not provider failures -- malformed model output or an
    invalid OMNIROUTE_MODEL_MAP -- are re-raised instead of being disguised
    as transport errors, so a bad schema never looks like a network problem.
    """

    try:

        return await _aexecute_nvidia_call(
            prompt,
            model,
            subagent,
            state_model,
            tool,
        )

    except (OutputParserException, ValueError):
        raise

    except Exception as e:

        if not allow_fallback or model == _OMNIROUTE_FALLBACK_MODEL:
            print(
                f"\n❌ [OmniRoute Error] '{model}' failed and no further "
                f"fallback is available. Reason: {e}"
            )
            raise

        print(
            "\n⚠️ [OmniRoute Call Failed] "
            f"'{model}' failed. Swapping to "
            f"'{_OMNIROUTE_FALLBACK_MODEL}'... "
            f"Reason: {e}"
        )

        return await call_nvidia(
            prompt=prompt,
            model=_OMNIROUTE_FALLBACK_MODEL,
            subagent=subagent,
            state_model=state_model,
            tool=tool,
            allow_fallback=False,
        )
