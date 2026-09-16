"""Synchronous LLM helpers for TIA LangGraph nodes."""

from __future__ import annotations

import json
import re
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import load_dotenv
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama

_TIA_ROOT = Path(__file__).resolve().parent.parent
if str(_TIA_ROOT) not in sys.path:
    sys.path.insert(0, str(_TIA_ROOT))

load_dotenv()


StreamListener = Callable[[str, str, str], None]
_stream_listener: ContextVar[StreamListener | None] = ContextVar(
    "tia_stream_listener",
    default=None,
)


def set_stream_listener(listener: StreamListener | None):
    """Register a listener for NVIDIA/Ollama stream lifecycle updates."""

    return _stream_listener.set(listener)


def reset_stream_listener(token) -> None:
    _stream_listener.reset(token)


def _get_tools():
    from tools import TOOLS

    return TOOLS


def _response_content(response: Any) -> str:
    if hasattr(response, "content"):
        return response.content or ""
    return str(response)


def _chunk_content(chunk: Any) -> str:
    """Extract printable text from a streamed provider chunk."""

    reasoning = getattr(chunk, "reasoning_content", None)
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)

    content = getattr(chunk, "content", chunk)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            item.get("reasoning_content", item.get("text", ""))
            if isinstance(item, dict)
            else str(item)
            for item in content
        )

    return "" if content is None else str(content)


def _stream_invoke(
    llm: Any,
    prompt: Any,
    *,
    label: str,
    return_text: bool = False,
) -> Any:
    """Stream a synchronous LangChain response while retaining its final value."""

    streamed_response = None
    streamed_text: list[str] = []
    listener = _stream_listener.get()

    print(f"\n🧠 [{label}] Streaming started:\n", flush=True)
    if listener is not None:
        listener("started", label, "")

    for chunk in llm.stream(prompt):
        chunk_text = _chunk_content(chunk)

        if chunk_text:
            streamed_text.append(chunk_text)
            print(chunk_text, end="", flush=True)
            if listener is not None:
                listener("chunk", label, chunk_text)

        if streamed_response is None:
            streamed_response = chunk
        else:
            try:
                streamed_response = streamed_response + chunk
            except TypeError:
                streamed_response = chunk

    print("\n\n🏁 Streaming finished.", flush=True)
    if listener is not None:
        listener("finished", label, "")

    if return_text:
        return "".join(streamed_text)

    if streamed_response is not None:
        return streamed_response

    return "".join(streamed_text)


def _strip_thinking(raw_content: str) -> str:
    content = raw_content or ""
    return re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.DOTALL,
    ).strip()


def _parse_with_fallback(
    parser: PydanticOutputParser,
    raw_content: str,
    *,
    llm: Any,
    original_prompt: str,
) -> Any:
    raw_content = _strip_thinking(raw_content) or "{}"

    try:
        return parser.parse(raw_content)
    except Exception:
        pass

    try:
        match = re.search(r"(\{.*})", raw_content, re.DOTALL)
        if match:
            return parser.pydantic_object.model_validate(
                json.loads(match.group(1))
            )
    except Exception:
        pass

    print(
        "\n🔄 [Parsing Failure] Model output is invalid JSON. "
        "Triggering automatic healing..."
    )

    correction_prompt = (
        "You are a strict data-fixing agent. "
        f"The user prompt was:\n###\n{original_prompt}\n###\n\n"
        f"The model replied with invalid layout text:\n###\n{raw_content}\n###\n\n"
        "Fix it completely. Return ONLY valid JSON adhering strictly to "
        "this schema instruction. Do not include thoughts, introduction, "
        f"or text outside the JSON:\n{parser.get_format_instructions()}"
    )

    try:
        fixed_res = _stream_invoke(
            llm,
            correction_prompt,
            label="structured-output-repair",
            return_text=True,
        )
        fixed_content = _strip_thinking(_response_content(fixed_res))

        match_fixed = re.search(r"(\{.*})", fixed_content, re.DOTALL)
        if match_fixed:
            return parser.pydantic_object.model_validate(
                json.loads(match_fixed.group(1))
            )

        return parser.parse(fixed_content)
    except Exception as healing_err:
        raise OutputParserException(
            f"Failed to parse or heal output: {healing_err}. "
            f"Raw text: {raw_content}"
        ) from healing_err


def call_groq(prompt: str, subagent: bool = False, state_model=None) -> Any:
    llm = ChatGroq(  # type: ignore[call-arg]
        model="groq/compound-mini",
        temperature=1.0,
        max_tokens=1024,
    )

    if subagent:
        structured_llm = llm.with_structured_output(state_model)
        return structured_llm.invoke([HumanMessage(content=prompt)])

    res = llm.invoke([HumanMessage(content=prompt)])
    return res.content


def call_ollama(
    prompt: str,
    model: str,
    subagent: bool = False,
    state_model=None,
    tool: bool = False,
) -> Any:
    local_model = (
        model
        if "nvidia" not in model.lower() and "gpt" not in model.lower()
        else "deepseek-r1:8b"
    )

    llm = ChatOllama(
        model=local_model,
        temperature=0.0,
        num_ctx=16352,
        num_predict=2048,
        num_gpu=99,
        low_vram=True,  # pyright: ignore[reportCallIssue]
        keep_alive=0,
        reasoning=False,
    )

    if subagent and state_model:
        parser = PydanticOutputParser(pydantic_object=state_model)
        structured_prompt = (
            "nothink\n" + prompt + "\n\n" + parser.get_format_instructions()
        )

        print(f"\n🧠 [{local_model}] Thinking process started:\n")
        res = _stream_invoke(
            llm,
            structured_prompt,
            label=local_model,
            return_text=True,
        )
        print("Validating streamed structure...", flush=True)

        return _parse_with_fallback(
            parser,
            _response_content(res),
            llm=llm,
            original_prompt=structured_prompt,
        )

    if tool:
        return _stream_invoke(
            llm.bind_tools(_get_tools()),
            prompt,
            label=local_model,
        )

    return _response_content(
        _stream_invoke(
            llm,
            prompt,
            label=local_model,
            return_text=True,
        )
    )


def _execute_nvidia_call(
    prompt: str,
    model: str,
    subagent: bool,
    state_model: Any,
    tool: bool,
) -> Any:
    llm = ChatNVIDIA(
        model=model,
        temperature=0.2,
        timeout=60,
        top_p=0.95,
        max_completion_tokens=16384,
    )

    if subagent and state_model:
        parser = PydanticOutputParser(pydantic_object=state_model)
        structured_prompt = prompt + "\n\n" + parser.get_format_instructions()

        print(f"\n🧠 [{model}] Thinking process started:\n")
        res = _stream_invoke(
            llm,
            structured_prompt,
            label=model,
            return_text=True,
        )
        print("Validating streamed structure...", flush=True)

        return _parse_with_fallback(
            parser,
            _response_content(res),
            llm=llm,
            original_prompt=structured_prompt,
        )

    if tool:
        return _stream_invoke(
            llm.bind_tools(_get_tools()),
            prompt,
            label=model,
        )

    return _response_content(
        _stream_invoke(
            llm,
            prompt,
            label=model,
            return_text=True,
        )
    )


def _is_nvidia_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, OSError)):
        return True

    return isinstance(
        exc,
        (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ),
    )


def call_nvidia(
    prompt: str,
    model: str,
    subagent: bool = False,
    state_model=None,
    tool: bool = False,
) -> Any:
    last_error: BaseException | None = None

    for attempt in range(2):
        try:
            return _execute_nvidia_call(
                prompt,
                model,
                subagent,
                state_model,
                tool,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0 and _is_nvidia_retryable(exc):
                time.sleep(2)
                continue
            break

    print(
        "\n⚠️ [NVIDIA Error/Timeout] Swapping to local Ollama execution... "
        f"Reason: {last_error}"
    )

    # return call_ollama(
    #     prompt=prompt,
    #     model="freehuntx/qwen3-coder:8b",
    #     subagent=subagent,
    #     state_model=state_model,
    #     tool=tool,
    # )
    return call_nvidia(
        prompt=prompt,
        model="openai/gpt-oss-20b",
        subagent=subagent,
        state_model=state_model,
        tool=tool,
    )