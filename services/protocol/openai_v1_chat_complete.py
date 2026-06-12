from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable, Iterator

from fastapi import HTTPException

from services.protocol.agent_compat import (
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
from services.protocol.chat_completion_cache import cache_key, chat_completion_cache, normalize_text_messages
from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    collect_image_outputs,
    collect_text,
    count_message_image_tokens,
    count_message_text_tokens,
    count_text_tokens,
    encode_images,
    normalize_messages,
    stream_image_outputs_with_pool,
    stream_text_deltas,
    text_backend,
)
from utils.helper import build_chat_image_markdown_content, extract_chat_image, extract_chat_prompt, is_image_chat_request, parse_image_count
from utils.image_tokens import (
    chat_usage_from_image_usage,
    count_image_inputs_tokens,
    count_image_output_items_tokens,
    image_usage,
)


def completion_chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None, completion_id: str = "", created: int | None = None) -> dict[str, Any]:
    return {
        "id": completion_id or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": created or int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def completion_response(
    model: str,
    content: str,
    created: int | None = None,
    messages: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_text_tokens = count_message_text_tokens(messages, model) if messages else 0
    prompt_image_tokens = count_message_image_tokens(messages, model) if messages else 0
    prompt_tokens = prompt_text_tokens + prompt_image_tokens
    completion_tokens = count_text_tokens(content, model) if messages else 0
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": assistant_message(content, tool_calls),
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {
                "text_tokens": prompt_text_tokens,
                "image_tokens": prompt_image_tokens,
                "cached_tokens": 0,
            },
            "completion_tokens_details": {
                "text_tokens": completion_tokens,
                "image_tokens": 0,
                "reasoning_tokens": 0,
            },
        },
    }

def assistant_message(content: str, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["content"] = None
        message["tool_calls"] = tool_calls
    return message

def completion_to_legacy(response: dict[str, Any], prompt: object = None) -> dict[str, Any]:
    choices = response.get("choices") if isinstance(response.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    text = str(message.get("content") or "")
    return {
        "id": str(response.get("id") or f"cmpl-{uuid.uuid4().hex}"),
        "object": "text_completion",
        "created": int(response.get("created") or time.time()),
        "model": str(response.get("model") or "auto"),
        "choices": [{
            "text": text,
            "index": 0,
            "logprobs": None,
            "finish_reason": first.get("finish_reason") or "stop",
        }],
        "usage": response.get("usage") or legacy_usage(prompt, text, str(response.get("model") or "auto")),
    }

def legacy_usage(prompt: object, text: str, model: str) -> dict[str, int]:
    prompt_text = prompt if isinstance(prompt, str) else "\n".join(str(item) for item in prompt if isinstance(item, str)) if isinstance(prompt, list) else ""
    prompt_tokens = count_text_tokens(prompt_text, model) if prompt_text else 0
    completion_tokens = count_text_tokens(text, model) if text else 0
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}


def stream_text_chat_completion(backend, messages: list[dict[str, Any]], model: str) -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    request = ConversationRequest(model=model, messages=messages)
    for delta_text in stream_text_deltas(backend, request):
        if not sent_role:
            sent_role = True
            yield completion_chunk(model, {"role": "assistant", "content": delta_text}, None, completion_id, created)
        else:
            yield completion_chunk(model, {"content": delta_text}, None, completion_id, created)
    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)


def collect_chat_content(chunks: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        choices = chunk.get("choices")
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
        content = str(delta.get("content") or "")
        if content:
            parts.append(content)
    return "".join(parts)


def chat_messages_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        return [message for message in messages if isinstance(message, dict)]
    prompt = str(body.get("prompt") or "").strip()
    if prompt:
        return [{"role": "user", "content": prompt}]
    raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})

def insert_system_hint(messages: list[dict[str, Any]], text: str) -> None:
    if not text:
        return
    messages.insert(0, {"role": "system", "content": text})


def chat_image_args(body: dict[str, Any]) -> tuple[str, str, int, list[tuple[bytes, str, str]]]:
    model = str(body.get("model") or "gpt-image-2").strip() or "gpt-image-2"
    prompt = extract_chat_prompt(body)
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})
    images = [
        (data, f"image_{idx}.png", mime)
        for idx, (data, mime) in enumerate(extract_chat_image(body), start=1)
    ]
    return model, prompt, parse_image_count(body.get("n")), images


def text_chat_parts(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    model = str(body.get("model") or "auto").strip() or "auto"
    raw_messages = prepare_agent_messages(chat_messages_from_body(body))
    messages = normalize_text_messages(normalize_messages(raw_messages))
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        last_user = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")
        phase_hint = build_phase_system_message(last_user, tool_names_from_body(body))
        if phase_hint:
            insert_system_hint(messages, phase_hint)
        insert_system_hint(messages, build_tool_call_system_message(tools))
    if wants_json_mode(body):
        insert_system_hint(messages, JSON_MODE_SYSTEM_MESSAGE)
    return model, messages

def text_chat_response(body: dict[str, Any]) -> dict[str, Any]:
    model, messages = text_chat_parts(body)
    allowed_tool_names = tool_names_from_body(body)
    key = cache_key(body, messages, stream=False)

    def compute() -> dict[str, Any]:
        content = collect_text(text_backend(), ConversationRequest(model=model, messages=messages))
        tool_calls = parse_tool_calls(content, allowed_tool_names)
        if not tool_calls and should_force_tool_retry(content, allowed_tool_names):
            # Show the model its own invalid reply plus a corrective instruction,
            # which works far better than repeating the system prompt blindly.
            retry_messages = list(messages) + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": build_tool_call_system_message(body.get("tools"), strict_retry=True)},
            ]
            content = collect_text(text_backend(), ConversationRequest(model=model, messages=retry_messages))
            tool_calls = parse_tool_calls(content, allowed_tool_names)
        if not tool_calls and allowed_tool_names:
            content = strip_raw_tool_json(content).strip() or content
        return completion_response(model, "" if tool_calls else content, messages=messages, tool_calls=tool_calls)

    return chat_completion_cache.get_or_compute_response(key, compute)


def image_result_content(result: dict[str, Any]) -> str:
    data = result.get("data")
    if isinstance(data, list) and data:
        return build_chat_image_markdown_content(result)
    return str(result.get("message") or "Image generation completed.")


def image_chat_response(body: dict[str, Any]) -> dict[str, Any]:
    model, prompt, n, images = chat_image_args(body)
    result = collect_image_outputs(stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        response_format="b64_json",
        images=encode_images(images) or None,
    )))
    response = completion_response(model, image_result_content(result), int(result.get("created") or 0) or None)
    usage = image_usage(
        input_text_tokens=count_text_tokens(prompt, model),
        input_image_tokens=count_image_inputs_tokens(images, model),
        output_tokens=count_image_output_items_tokens(result.get("data")),
    )
    response["usage"] = chat_usage_from_image_usage(usage)
    return response


def image_chat_events(body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    model, prompt, n, images = chat_image_args(body)
    image_outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        response_format="b64_json",
        images=encode_images(images) or None,
    ))
    yield from stream_image_chat_completion(image_outputs, model)


def stream_image_chat_completion(image_outputs: Iterable[ImageOutput], model: str) -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    sent_text = ""
    for output in image_outputs:
        content = ""
        if output.kind == "progress":
            content = output.text
            sent_text += content
        elif output.kind == "result":
            content = build_chat_image_markdown_content({"data": output.data})
        elif output.kind == "message":
            content = output.text[len(sent_text):] if output.text.startswith(sent_text) else output.text
        if not content:
            continue
        if not sent_role:
            sent_role = True
            yield completion_chunk(model, {"role": "assistant", "content": content}, None, completion_id, created)
        else:
            yield completion_chunk(model, {"content": content}, None, completion_id, created)
    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    if body.get("stream"):
        if is_image_chat_request(body):
            return image_chat_events(body)
        model, messages = text_chat_parts(body)
        key = cache_key(body, messages, stream=True)
        return chat_completion_cache.get_or_compute_stream(
            key,
            lambda: stream_text_chat_completion(text_backend(), messages, model),
        )
    if is_image_chat_request(body):
        return image_chat_response(body)
    return text_chat_response(body)

def completions_handle(body: dict[str, Any]) -> dict[str, Any]:
    prompt = body.get("prompt")
    if isinstance(prompt, list):
        prompt_text = "\n".join(str(item) for item in prompt if isinstance(item, str)).strip()
    else:
        prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})
    chat_body = dict(body)
    chat_body["messages"] = [{"role": "user", "content": prompt_text}]
    chat_body.pop("prompt", None)
    chat_body["stream"] = False
    return completion_to_legacy(text_chat_response(chat_body), prompt=prompt)
