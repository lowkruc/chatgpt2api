from __future__ import annotations

import time
import uuid
from typing import Any, Iterable, Iterator

from fastapi import HTTPException

from services.protocol.chat_completion_cache import cache_key, chat_completion_cache, normalize_text_messages
from services.protocol.openai_v1_chat_complete import (
    JSON_MODE_SYSTEM_MESSAGE,
    build_phase_system_message,
    build_tool_call_system_message,
    parse_tool_calls,
    prepare_agent_messages,
    should_force_tool_retry,
    strip_raw_tool_json,
    tool_names_from_body,
    wants_json_mode,
)
from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    count_message_image_tokens,
    count_message_text_tokens,
    count_text_tokens,
    encode_images,
    normalize_messages,
    stream_image_outputs_with_pool,
    stream_text_deltas,
    text_backend,
)
from utils.helper import extract_image_from_message_content, extract_response_prompt, has_response_image_generation_tool
from utils.image_tokens import (
    count_image_content_tokens,
    count_image_output_items_tokens,
    image_usage,
    token_usage,
)

RESPONSE_CONTENT_PART_TYPES = {"text", "input_text", "output_text", "image_url", "input_image", "image"}


def is_text_response_request(body: dict[str, Any]) -> bool:
    return not has_response_image_generation_tool(body)


def has_non_image_tools(body: dict[str, Any]) -> bool:
    tools = body.get("tools")
    if not isinstance(tools, list):
        return False
    return any(
        isinstance(tool, dict) and str(tool.get("type") or "").strip() != "image_generation"
        for tool in tools
    )


def response_image_tool(body: dict[str, Any]) -> dict[str, object]:
    for tool in body.get("tools") or []:
        if isinstance(tool, dict) and tool.get("type") == "image_generation":
            return tool
    return {}


def extract_response_image(input_value: object) -> tuple[bytes, str] | None:
    if isinstance(input_value, dict):
        if str(input_value.get("type") or "").strip() == "input_image":
            images = extract_image_from_message_content([input_value])
            return images[0] if images else None
        images = extract_image_from_message_content(input_value.get("content"))
        return images[0] if images else None
    if not isinstance(input_value, list):
        return None
    for item in reversed(input_value):
        if isinstance(item, dict):
            if str(item.get("type") or "").strip() == "input_image":
                images = extract_image_from_message_content([item])
                if images:
                    return images[0]
            images = extract_image_from_message_content(item.get("content"))
            if images:
                return images[0]
    return None


def _input_image_parts(input_value: object) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if isinstance(input_value, dict):
        content = input_value.get("content")
        if isinstance(content, list):
            parts.extend(item for item in content if isinstance(item, dict))
        return parts
    if not isinstance(input_value, list):
        return parts
    if all(isinstance(item, dict) and item.get("type") for item in input_value):
        return [item for item in input_value if isinstance(item, dict)]
    for item in input_value:
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, list):
                parts.extend(part for part in content if isinstance(part, dict))
    return parts


def _is_response_content_part(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    part_type = str(value.get("type") or "").strip()
    return part_type in RESPONSE_CONTENT_PART_TYPES or ("image_url" in value and part_type != "message")


def _message_content_from_response_item(item: dict[str, Any]) -> object:
    item_type = str(item.get("type") or "").strip()
    if item_type == "function_call_output":
        return str(item.get("output") or item.get("content") or "")
    if item_type == "function_call":
        name = str(item.get("name") or "").strip()
        arguments = str(item.get("arguments") or "{}").strip() or "{}"
        return f"Assistant requested tool calls:\n[{name} {arguments}]".strip()
    content = item.get("content")
    if isinstance(content, list):
        return [dict(part) if isinstance(part, dict) else part for part in content]
    if isinstance(content, str):
        return content
    return extract_response_prompt([item]) or content or ""


def _append_response_message(messages: list[dict[str, Any]], role: object, content: object) -> None:
    if isinstance(content, str):
        if content.strip():
            messages.append({"role": str(role or "user"), "content": content.strip()})
        return
    if isinstance(content, list) and content:
        messages.append({"role": str(role or "user"), "content": content})


def messages_from_input(input_value: object, instructions: object = None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_text = str(instructions or "").strip()
    if system_text:
        messages.append({"role": "system", "content": system_text})
    if isinstance(input_value, str):
        if input_value.strip():
            messages.append({"role": "user", "content": input_value.strip()})
        return messages
    if isinstance(input_value, dict):
        item_type = str(input_value.get("type") or "").strip()
        if item_type == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": str(input_value.get("call_id") or input_value.get("id") or ""),
                "content": str(input_value.get("output") or input_value.get("content") or ""),
            })
            return messages
        if item_type == "function_call":
            messages.append({
                "role": "assistant",
                "tool_calls": [{
                    "id": str(input_value.get("call_id") or input_value.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(input_value.get("name") or ""),
                        "arguments": str(input_value.get("arguments") or "{}"),
                    },
                }],
            })
            return messages
        if _is_response_content_part(input_value):
            _append_response_message(messages, "user", [dict(input_value)])
            return messages
        _append_response_message(
            messages,
            input_value.get("role") or "user",
            _message_content_from_response_item(input_value),
        )
        return messages
    if isinstance(input_value, list):
        if all(_is_response_content_part(item) for item in input_value):
            _append_response_message(messages, "user", [dict(item) for item in input_value if isinstance(item, dict)])
            return messages
        pending_parts: list[dict[str, Any]] = []
        for item in input_value:
            if isinstance(item, dict) and str(item.get("type") or "").strip() == "function_call_output":
                if pending_parts:
                    _append_response_message(messages, "user", pending_parts)
                    pending_parts = []
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or item.get("id") or ""),
                    "content": str(item.get("output") or item.get("content") or ""),
                })
                continue
            if isinstance(item, dict) and str(item.get("type") or "").strip() == "function_call":
                if pending_parts:
                    _append_response_message(messages, "user", pending_parts)
                    pending_parts = []
                messages.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": str(item.get("call_id") or item.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(item.get("name") or ""),
                            "arguments": str(item.get("arguments") or "{}"),
                        },
                    }],
                })
                continue
            if _is_response_content_part(item):
                pending_parts.append(dict(item))
                continue
            if pending_parts:
                _append_response_message(messages, "user", pending_parts)
                pending_parts = []
            if not isinstance(item, dict):
                continue
            _append_response_message(
                messages,
                item.get("role") or "user",
                _message_content_from_response_item(item),
            )
        if pending_parts:
            _append_response_message(messages, "user", pending_parts)
    return messages


def text_output_item(text: str, item_id: str | None = None, status: str = "completed") -> dict[str, Any]:
    return {
        "id": item_id or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def image_output_items(prompt: str, data: list[dict[str, Any]], item_id: str | None = None) -> list[dict[str, Any]]:
    output = []
    for item in data:
        b64_json = str(item.get("b64_json") or "").strip()
        if b64_json:
            output.append({
                "id": item_id or f"ig_{len(output) + 1}",
                "type": "image_generation_call",
                "status": "completed",
                "result": b64_json,
                "revised_prompt": str(item.get("revised_prompt") or prompt).strip() or prompt,
            })
    return output

def function_call_output_items(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        call_id = str(call.get("id") or f"call_{uuid.uuid4().hex}")
        output.append({
            "id": f"fc_{uuid.uuid4().hex}",
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": name,
            "arguments": str(function.get("arguments") or "{}"),
        })
    return output

def started_function_call_item(item: dict[str, Any]) -> dict[str, Any]:
    started = dict(item)
    started["status"] = "in_progress"
    started["arguments"] = ""
    return started


def response_created(response_id: str, model: str, created: int) -> dict[str, Any]:
    return {
        "type": "response.created",
        "response": {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "in_progress",
            "error": None,
            "incomplete_details": None,
            "model": model,
            "output": [],
            "parallel_tool_calls": False,
        },
    }


def response_completed(
    response_id: str,
    model: str,
    created: int,
    output: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": model,
            "output": output,
            "parallel_tool_calls": False,
        },
    }
    if usage:
        response["response"]["usage"] = usage
    return response


def text_response_parts(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    model = str(body.get("model") or "auto").strip() or "auto"
    raw_messages = prepare_agent_messages(messages_from_input(body.get("input"), body.get("instructions")))
    messages = normalize_text_messages(normalize_messages(raw_messages))
    if has_non_image_tools(body):
        last_user = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")
        phase_hint = build_phase_system_message(last_user, tool_names_from_body(body))
        if phase_hint:
            messages.insert(0, {"role": "system", "content": phase_hint})
        messages.insert(0, {"role": "system", "content": build_tool_call_system_message(body.get("tools"))})
    if wants_json_mode(body):
        messages.insert(0, {"role": "system", "content": JSON_MODE_SYSTEM_MESSAGE})
    return model, messages


def stream_text_response(backend, body: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    model = str(body.get("model") or "auto").strip() or "auto"
    messages = messages if messages is not None else messages_from_input(body.get("input"), body.get("instructions"))
    response_id = f"resp_{uuid.uuid4().hex}"
    item_id = f"msg_{uuid.uuid4().hex}"
    created = int(time.time())
    allowed_tool_names = tool_names_from_body(body)
    full_text = ""
    yield response_created(response_id, model, created)
    if allowed_tool_names:
        request = ConversationRequest(model=model, messages=messages)
        for delta in stream_text_deltas(backend, request):
            full_text += delta
        tool_items = function_call_output_items(parse_tool_calls(full_text, allowed_tool_names))
        if not tool_items and should_force_tool_retry(full_text, allowed_tool_names):
            retry_messages = list(messages) + [
                {"role": "assistant", "content": full_text},
                {"role": "user", "content": build_tool_call_system_message(body.get("tools"), strict_retry=True)},
            ]
            full_text = ""
            retry_request = ConversationRequest(model=model, messages=retry_messages)
            for delta in stream_text_deltas(backend, retry_request):
                full_text += delta
            tool_items = function_call_output_items(parse_tool_calls(full_text, allowed_tool_names))
        if tool_items:
            for output_index, item in enumerate(tool_items):
                yield {"type": "response.output_item.added", "output_index": output_index, "item": started_function_call_item(item)}
                yield {
                    "type": "response.function_call_arguments.done",
                    "item_id": item["id"],
                    "output_index": output_index,
                    "arguments": item["arguments"],
                }
                yield {"type": "response.output_item.done", "output_index": output_index, "item": item}
            usage = token_usage(
                input_text_tokens=count_message_text_tokens(messages, model),
                input_image_tokens=count_message_image_tokens(messages, model),
                output_text_tokens=count_text_tokens(full_text, model),
            )
            yield response_completed(response_id, model, created, tool_items, usage)
            return
        # No tool call after retry: emit collected text directly instead of
        # calling upstream again, and strip any leaked raw tool JSON.
        final_text = strip_raw_tool_json(full_text).strip() or full_text.strip()
        yield {"type": "response.output_item.added", "output_index": 0, "item": text_output_item("", item_id, "in_progress")}
        yield {"type": "response.output_text.delta", "item_id": item_id, "output_index": 0, "content_index": 0, "delta": final_text}
        yield {"type": "response.output_text.done", "item_id": item_id, "output_index": 0, "content_index": 0, "text": final_text}
        item = text_output_item(final_text, item_id, "completed")
        yield {"type": "response.output_item.done", "output_index": 0, "item": item}
        usage = token_usage(
            input_text_tokens=count_message_text_tokens(messages, model),
            input_image_tokens=count_message_image_tokens(messages, model),
            output_text_tokens=count_text_tokens(final_text, model),
        )
        yield response_completed(response_id, model, created, [item], usage)
        return
    yield {"type": "response.output_item.added", "output_index": 0, "item": text_output_item("", item_id, "in_progress")}
    request = ConversationRequest(model=model, messages=messages)
    for delta in stream_text_deltas(backend, request):
        full_text += delta
        yield {"type": "response.output_text.delta", "item_id": item_id, "output_index": 0, "content_index": 0, "delta": delta}
    yield {"type": "response.output_text.done", "item_id": item_id, "output_index": 0, "content_index": 0, "text": full_text}
    item = text_output_item(full_text, item_id, "completed")
    yield {"type": "response.output_item.done", "output_index": 0, "item": item}
    usage = token_usage(
        input_text_tokens=count_message_text_tokens(messages, model),
        input_image_tokens=count_message_image_tokens(messages, model),
        output_text_tokens=count_text_tokens(full_text, model),
    )
    yield response_completed(response_id, model, created, [item], usage)


def stream_image_response(
    image_outputs: Iterable[ImageOutput],
    prompt: str,
    model: str,
    input_image_tokens: int = 0,
    size: object = None,
    quality: str = "auto",
) -> Iterator[dict[str, Any]]:
    response_id = f"resp_{uuid.uuid4().hex}"
    created = int(time.time())
    yield response_created(response_id, model, created)
    for output in image_outputs:
        if output.kind == "message":
            text = output.text
            item = text_output_item(text)
            usage = token_usage(
                input_text_tokens=count_text_tokens(prompt, model),
                input_image_tokens=input_image_tokens,
                output_text_tokens=count_text_tokens(text, model),
            )
            yield {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": text}
            yield {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "text": text}
            yield {"type": "response.output_item.done", "output_index": 0, "item": item}
            yield response_completed(response_id, model, created, [item], usage)
            return
        if output.kind != "result":
            continue
        items = image_output_items(prompt, output.data)
        if items:
            usage = image_usage(
                input_text_tokens=count_text_tokens(prompt, model),
                input_image_tokens=input_image_tokens,
                output_tokens=count_image_output_items_tokens(output.data, size, quality),
            )
            for output_index, item in enumerate(items):
                yield {"type": "response.output_item.done", "output_index": output_index, "item": item}
            yield response_completed(response_id, model, created, items, usage)
            return
    raise RuntimeError("image generation failed")


def collect_response(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    completed = {}
    for event in events:
        if event.get("type") == "response.completed":
            completed = event.get("response") if isinstance(event.get("response"), dict) else {}
    if not completed:
        raise RuntimeError("response generation failed")
    return completed


def response_events(body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if is_text_response_request(body):
        model, messages = text_response_parts(body)
        key = cache_key(body, messages, stream=bool(body.get("stream")))
        yield from chat_completion_cache.get_or_compute_stream(
            key,
            lambda: stream_text_response(text_backend(), body, messages),
        )
        return

    prompt = extract_response_prompt(body.get("input"))
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "input text is required"})
    model = str(body.get("model") or "gpt-image-2").strip() or "gpt-image-2"
    image_info = extract_response_image(body.get("input"))
    if image_info:
        image_data, mime_type = image_info
        images = encode_images([(image_data, "image.png", mime_type)])
    else:
        images = None
    input_image_tokens = count_image_content_tokens(_input_image_parts(body.get("input")), model)
    tool = response_image_tool(body)
    image_outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        size=tool.get("size"),
        quality=str(tool.get("quality") or "auto"),
        response_format="b64_json",
        images=images,
    ))
    yield from stream_image_response(image_outputs, prompt, model, input_image_tokens, tool.get("size"), str(tool.get("quality") or "auto"))


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    events = response_events(body)
    if body.get("stream"):
        return events
    return collect_response(events)
