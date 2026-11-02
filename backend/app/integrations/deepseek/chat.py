"""DeepSeek Chat client with OpenAI-compatible function calling."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any]], Any]


class DeepSeekChatClient:
    def __init__(self) -> None:
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY is empty; chat calls will fail until configured")
        self.client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY or "missing",
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=settings.DEEPSEEK_MAX_RETRIES,
        )
        self.model = settings.DEEPSEEK_CHAT_MODEL
        self.max_tool_rounds = max(1, int(settings.DEEPSEEK_CHAT_MAX_TOOL_ROUNDS or 4))

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        *,
        temperature: float = 0.2,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any], int]:
        """Run a tool-calling loop. Returns (final_text, tool_trace, usage, latency_ms)."""
        working = list(messages)
        tool_trace: list[dict[str, Any]] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        started = time.perf_counter()

        for round_idx in range(self.max_tool_rounds + 1):
            logger.info(
                "DeepSeek chat request | model=%s | round=%s | messages=%s | tools=%s",
                self.model,
                round_idx,
                len(working),
                len(tools),
            )
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": working,
                    "temperature": temperature,
                }
                if tools and round_idx < self.max_tool_rounds:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                response = self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.exception("DeepSeek chat request failed | model=%s", self.model)
                raise AppError(
                    f"Chat service temporarily unavailable: {exc}",
                    code="chat_unavailable",
                    status_code=502,
                ) from exc

            _accumulate_usage(usage_total, response)
            choice = response.choices[0]
            message = choice.message
            tool_calls = list(message.tool_calls or [])

            assistant_payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            if tool_calls:
                assistant_payload["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            working.append(assistant_payload)

            if not tool_calls:
                latency_ms = int((time.perf_counter() - started) * 1000)
                text = (message.content or "").strip()
                logger.info(
                    "DeepSeek chat done | rounds=%s | latency_ms=%s | usage=%s | chars=%s",
                    round_idx + 1,
                    latency_ms,
                    usage_total,
                    len(text),
                )
                return text, tool_trace, usage_total, latency_ms

            for tc in tool_calls:
                name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                    result: Any = {"error": "invalid_tool_arguments", "raw": raw_args}
                else:
                    try:
                        result = tool_handler(name, args)
                        if hasattr(result, "__await__"):
                            raise AppError(
                                "Async tool handlers must be awaited by the caller",
                                code="invalid_tool_handler",
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Tool failed | name=%s", name)
                        result = {"error": str(exc)}

                serialized = _json_dumps(result)
                tool_trace.append(
                    {
                        "id": tc.id,
                        "name": name,
                        "arguments": args,
                        "result_preview": serialized[:1000],
                    }
                )
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": serialized,
                    }
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("DeepSeek chat exhausted tool rounds | latency_ms=%s", latency_ms)
        return (
            "I need a bit more detail to look that up accurately. "
            "Please share the OE/part number or vehicle brand, model, and year.",
            tool_trace,
            usage_total,
            latency_ms,
        )

    async def chat_with_tools_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Any],
        *,
        temperature: float = 0.2,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any], int]:
        """Async tool loop; tool_handler may be async or sync."""
        import inspect

        working = list(messages)
        tool_trace: list[dict[str, Any]] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        started = time.perf_counter()

        for round_idx in range(self.max_tool_rounds + 1):
            logger.info(
                "DeepSeek chat request | model=%s | round=%s | messages=%s | tools=%s",
                self.model,
                round_idx,
                len(working),
                len(tools),
            )
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": working,
                    "temperature": temperature,
                }
                if tools and round_idx < self.max_tool_rounds:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                response = self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.exception("DeepSeek chat request failed | model=%s", self.model)
                raise AppError(
                    f"Chat service temporarily unavailable: {exc}",
                    code="chat_unavailable",
                    status_code=502,
                ) from exc

            _accumulate_usage(usage_total, response)
            choice = response.choices[0]
            message = choice.message
            tool_calls = list(message.tool_calls or [])

            assistant_payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            if tool_calls:
                assistant_payload["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            working.append(assistant_payload)

            if not tool_calls:
                latency_ms = int((time.perf_counter() - started) * 1000)
                text = (message.content or "").strip()
                return text, tool_trace, usage_total, latency_ms

            for tc in tool_calls:
                name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                    result: Any = {"error": "invalid_tool_arguments", "raw": raw_args}
                else:
                    try:
                        maybe = tool_handler(name, args)
                        if inspect.isawaitable(maybe):
                            result = await maybe
                        else:
                            result = maybe
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Tool failed | name=%s", name)
                        result = {"error": str(exc)}

                serialized = _json_dumps(result)
                tool_trace.append(
                    {
                        "id": tc.id,
                        "name": name,
                        "arguments": args,
                        "result_preview": serialized[:1000],
                    }
                )
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": serialized,
                    }
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return (
            "I need a bit more detail to look that up accurately. "
            "Please share the OE/part number or vehicle brand, model, and year.",
            tool_trace,
            usage_total,
            latency_ms,
        )


def _accumulate_usage(total: dict[str, int], response: Any) -> None:
    usage = getattr(response, "usage", None)
    if not usage:
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            total[key] = int(total.get(key) or 0) + int(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps({"error": "unserializable_tool_result"}, ensure_ascii=False)
