# import google.generativeai as genai

import asyncio
import json
import re
import os
from contextvars import ContextVar
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException

from tools import TOOLS

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)


load_dotenv()


StreamListener = Any
_stream_listener: ContextVar[StreamListener | None] = ContextVar(
    "tia_stream_listener",
    default=None,
)


def set_stream_listener(listener: StreamListener | None):
    return _stream_listener.set(listener)


def reset_stream_listener(token) -> None:
    _stream_listener.reset(token)


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

    local_model = (
        model
        if (
            "nvidia" not in model.lower()
            and "gpt" not in model.lower()
        )
        else "deepseek-r1:8b"
    )

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


@retry(
    retry=retry_if_exception_type(
        requests.exceptions.ReadTimeout
    ),
    stop=stop_after_attempt(2),
    wait=wait_exponential(
        multiplier=2,
        min=2,
        max=6,
    ),
    reraise=True,
)
async def _aexecute_nvidia_call(
    prompt,
    model,
    subagent,
    state_model,
    tool,
):

    llm = ChatNVIDIA(
        model=model,
        temperature=0.2,
        timeout=60,
        top_p=0.95,
        max_completion_tokens=16384,
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
    # Tool call
    # ----------------------------------------------------------

    if tool:

        llm_with_tools = llm.bind_tools(
            TOOLS
        )

        return await llm_with_tools.ainvoke(
            prompt
        )

    # ----------------------------------------------------------
    # Standard streamed output
    # ----------------------------------------------------------

    return await _stream_llm_response(
        llm=llm,
        prompt=prompt,
        show_reasoning=True,
        model_label=model,
    )


async def call_nvidia(
    prompt: str,
    model: str,
    subagent=False,
    state_model=None,
    tool=False,
):

    try:

        return await _aexecute_nvidia_call(
            prompt,
            model,
            subagent,
            state_model,
            tool,
        )

    except Exception as e:

        print(
            "\n⚠️ [NVIDIA Error/Timeout] "
            "Swapping to local Ollama execution... "
            f"Reason: {e}"
        )

        fallback_local_model = (
            "openai/gpt-oss-20b"
            # "freehuntx/qwen3-coder:8b"
        )

        # return await call_ollama(
        #     prompt=prompt,
        #     model=fallback_local_model,
        #     subagent=subagent,
        #     state_model=state_model,
        #     tool=tool,
        # )
        return await call_nvidia(
            prompt=prompt,
            model=fallback_local_model,
            subagent=subagent,
            state_model=state_model,
            tool=tool,
        )
