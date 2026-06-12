from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from utils.log import logger

JSON_MODE_SYSTEM_MESSAGE = "Return only valid JSON. Do not wrap the JSON in Markdown."

TOOL_CALL_SYSTEM_MESSAGE = (
    "You are an autonomous coding agent with function tools executed by the client.\n"
    "\n"
    "STRICT OUTPUT PROTOCOL - every reply is exactly ONE of two modes:\n"
    "\n"
    "MODE A (tool call): the reply is ONLY this JSON, nothing before or after:\n"
    '{"tool_calls":[{"name":"<tool>","arguments":{}}]}\n'
    "\n"
    "MODE B (final answer): plain text only, ZERO JSON anywhere, used only when the task is fully done.\n"
    "\n"
    "Mixing modes is a protocol violation. JSON plus prose is invalid. A plan announcement without a tool call is invalid.\n"
    "\n"
    "RULES:\n"
    "1. When the user asks about code, files, or the project, the first reply MUST be MODE A. Never ask permission or clarification first.\n"
    "2. After a tool result: if more info is needed reply MODE A again; if everything is known reply MODE B.\n"
    "3. On a tool error reply MODE A with corrected arguments. Never report failure while tools remain usable.\n"
    "4. Never say tools are unavailable. Never narrate what you will read next - call the tool instead.\n"
    "5. MODE B must never contain phrases like 'should I', 'do you want me to', 'apakah mau', 'langkah berikutnya saya akan'.\n"
    "\n"
    "EXAMPLE SESSION:\n"
    "user: pahami codebase ini\n"
    'assistant: {"tool_calls":[{"name":"ls","arguments":{"path":"."}}]}\n'
    "tool: api/ services/ main.py README.md\n"
    'assistant: {"tool_calls":[{"name":"read","arguments":{"path":"main.py","offset":1,"limit":200}}]}\n'
    "tool: from api import create_app ...\n"
    "assistant: Codebase ini adalah FastAPI app. Entry point main.py memanggil create_app() dari api/. (MODE B, no JSON)"
)

PHASE_HINTS = {
    "inspect": "Inspect before answering. Prefer ls/find/grep/read. Do not use write/edit yet.",
    "search": "Search narrowly first. Prefer grep or find with focused limits before reading files.",
    "edit": "Before changing code, inspect target files first. Prefer read/grep/find, then edit or write with minimal changes.",
    "verify": "After making or planning changes, prefer bash to run targeted verification commands.",
}

STRICT_TOOL_RETRY_SYSTEM_MESSAGE = (
    "PROTOCOL VIOLATION: your previous reply mixed prose with a tool plan, asked permission, or announced next steps without acting. "
    "Reply now in MODE A only: a single JSON object {\"tool_calls\":[{\"name\":...,\"arguments\":{...}}]} with no other text, no markdown, no explanation."
)

TOOL_RESULT_PREFIX = "Tool result"

TOOL_CALL_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
TOOL_UNAVAILABLE_TEXT_RE = re.compile(
    r"(do not have access|don't have access|cannot access|can't access|tool(?:s)? (?:is|are) unavailable|tool(?:s)? (?:is|are) not available)",
    re.IGNORECASE,
)
PERMISSION_SEEKING_TEXT_RE = re.compile(
    r"(apakah (?:kamu )?(?:mau|ingin)|mau saya|boleh saya|saya boleh|perlu saya|saya perlu tahu|bisa (?:anda|kamu) konfirmasi|should i|would you like|do you want me|shall i|may i|mana yang mau|bisa berikan|saya perlu sedikit konteks|i need (?:a bit of|some) context|can you confirm)",
    re.IGNORECASE,
)
NEXT_STEP_ANNOUNCEMENT_RE = re.compile(
    r"(langkah (?:berikutnya|selanjutnya)|next step|saya akan membaca|saya akan (?:cek|periksa|baca|scan)|i will read|i would read|i'll read|akan saya baca|selanjutnya (?:saya|kita)|kalau mau,? (?:saya|aku) bisa)",
    re.IGNORECASE,
)


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and str(item.get("type") or "") in {"text", "input_text", "output_text"}:
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


def tool_result_text(message: dict[str, Any]) -> str:
    name = str(message.get("name") or message.get("tool_call_id") or "tool").strip() or "tool"
    content = text_from_content(message.get("content"))
    return f"{TOOL_RESULT_PREFIX} for {name}:\n{content}"


def assistant_tool_call_text(message: dict[str, Any]) -> str:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return text_from_content(message.get("content"))
    compact: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        compact.append({
            "name": function.get("name") or call.get("name"),
            "arguments": function.get("arguments") or call.get("arguments") or "{}",
        })
    return "Assistant requested tool calls:\n" + json.dumps(compact, ensure_ascii=False)


def prepare_agent_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user").strip().lower()
        if role == "developer":
            role = "system"
        if role == "tool":
            prepared.append({"role": "user", "content": tool_result_text(message)})
            continue
        if role == "assistant" and message.get("tool_calls"):
            prepared.append({"role": "assistant", "content": assistant_tool_call_text(message)})
            continue
        if role not in {"system", "user", "assistant"}:
            role = "user"
        prepared.append({"role": role, "content": message.get("content", "")})
    return prepared


def wants_json_mode(body: dict[str, Any]) -> bool:
    response_format = body.get("response_format")
    if not isinstance(response_format, dict):
        return False
    return str(response_format.get("type") or "").strip().lower() in {"json_object", "json_schema"}


def compact_tool_spec(tool: dict[str, Any]) -> dict[str, Any] | None:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    name = str(function.get("name") or tool.get("name") or "").strip()
    if not name:
        return None
    spec: dict[str, Any] = {"name": name}
    description = str(function.get("description") or tool.get("description") or "").strip()
    if description:
        spec["description"] = description
    parameters = function.get("parameters", tool.get("parameters"))
    if isinstance(parameters, dict) and parameters:
        spec["parameters"] = parameters
    return spec


def tool_names_from_body(body: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    tools = body.get("tools")
    if not isinstance(tools, list):
        return names
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or tool.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def build_tool_call_system_message(tools: object, *, strict_retry: bool = False) -> str:
    base = _configured_base_prompt()
    if strict_retry:
        base = f"{base}\n{STRICT_TOOL_RETRY_SYSTEM_MESSAGE}"
    if not isinstance(tools, list) or not tools:
        return base
    specs = [spec for tool in tools if isinstance(tool, dict) for spec in [compact_tool_spec(tool)] if spec]
    if not specs:
        return base
    return f"{base}\nAvailable tools:\n{json.dumps(specs, ensure_ascii=False, separators=(',', ':'))}"


def _agent_protocol_settings() -> dict[str, Any]:
    try:
        from services.config import config
        return config.get_agent_protocol_settings()
    except Exception:
        return {"system_prompt_override": "", "extra_rules": "", "retry_enabled": True}


def _configured_base_prompt() -> str:
    settings = _agent_protocol_settings()
    base = str(settings.get("system_prompt_override") or "") or TOOL_CALL_SYSTEM_MESSAGE
    extra = str(settings.get("extra_rules") or "")
    if extra:
        base = f"{base}\nEXTRA RULES:\n{extra}"
    return base


def tool_retry_enabled() -> bool:
    return bool(_agent_protocol_settings().get("retry_enabled", True))


def infer_agent_phase(prompt: str, allowed_names: set[str]) -> str | None:
    text = str(prompt or "").lower()
    if any(token in text for token in ("fix", "edit", "update", "refactor", "write code", "ubah", "patch")):
        return "edit"
    if any(token in text for token in ("search", "find usage", "grep", "where", "cari")):
        return "search"
    if any(token in text for token in ("test", "verify", "run", "cek", "smoke")) and "bash" in allowed_names:
        return "verify"
    if any(token in text for token in ("understand", "architecture", "pahami", "list file", "structure", "struktur")):
        return "inspect"
    return None


def build_phase_system_message(prompt: str, allowed_names: set[str]) -> str:
    phase = infer_agent_phase(prompt, allowed_names)
    if not phase:
        return ""
    return PHASE_HINTS.get(phase, "")


def decode_tool_arguments(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "{}"
        try:
            json.loads(text)
        except Exception:
            return json.dumps({"input": text}, ensure_ascii=False)
        return text
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "{}"


def normalize_tool_arguments(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments)
    except Exception:
        return arguments
    if not isinstance(payload, dict):
        return arguments
    if name == "bash":
        command = payload.get("command")
        if isinstance(command, str):
            fixed = re.sub(r"\bfind\.(?=\s|$)", "find .", command)
            fixed = re.sub(r"\bls-R\b", "ls -R", fixed)
            fixed = re.sub(r"\bgrep-R\b", "grep -R", fixed)
            if fixed != command:
                payload["command"] = fixed
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def tool_call_payloads_from_text(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    match = TOOL_CALL_JSON_RE.search(text)
    candidates = [match.group(1)] if match else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        offsets = [0] if candidate.startswith("{") else []
        offsets.extend(index for index, char in enumerate(candidate) if char == "{" and index not in offsets)
        for offset in offsets:
            try:
                payload, _end = decoder.raw_decode(candidate[offset:])
            except Exception:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
    return payloads


def infer_tool_name(payload: dict[str, Any], allowed_names: set[str]) -> str | None:
    if "bash" in allowed_names and isinstance(payload.get("command"), str):
        return "bash"
    if "read" in allowed_names and isinstance(payload.get("path"), str):
        return "read"
    if "grep" in allowed_names and any(key in payload for key in ("pattern", "query", "regex")):
        return "grep"
    if "find" in allowed_names and any(key in payload for key in ("glob", "name", "path")):
        return "find"
    if "ls" in allowed_names and any(key in payload for key in ("path", "limit", "depth")):
        return "ls"
    return None


def clamp_tool_arguments(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments)
    except Exception:
        return arguments
    if not isinstance(payload, dict):
        return arguments
    if name == "read":
        if "offset" not in payload:
            payload["offset"] = 1
        if "limit" not in payload:
            payload["limit"] = 200
    elif name == "ls":
        if "limit" not in payload:
            payload["limit"] = 200
    elif name == "find":
        if "limit" not in payload:
            payload["limit"] = 200
    elif name == "grep":
        if "limit" not in payload:
            payload["limit"] = 100
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def rewrite_tool_call(name: str, arguments: str) -> tuple[str, str]:
    try:
        payload = json.loads(arguments)
    except Exception:
        return name, arguments
    if not isinstance(payload, dict):
        return name, arguments
    path = payload.get("path")
    if name == "read" and isinstance(path, str):
        stripped = path.rstrip("/") or path
        if os.path.isdir(stripped):
            payload = {"path": path, "limit": int(payload.get("limit") or 200)}
            return "ls", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return name, arguments


def parse_tool_calls(content: str, allowed_names: set[str]) -> list[dict[str, Any]]:
    if not allowed_names:
        return []
    text = str(content or "").strip()
    if not text:
        return []
    tool_calls: list[dict[str, Any]] = []
    for payload in tool_call_payloads_from_text(text):
        raw_calls = payload.get("tool_calls")
        if isinstance(raw_calls, dict):
            raw_calls = [raw_calls]
        if not isinstance(raw_calls, list):
            name = payload.get("name")
            if name:
                raw_calls = [payload]
        if not isinstance(raw_calls, list):
            inferred_name = infer_tool_name(payload, allowed_names)
            if inferred_name:
                raw_calls = [{"name": inferred_name, "arguments": payload}]
        if not isinstance(raw_calls, list):
            continue
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
            name = str(raw_call.get("name") or function.get("name") or "").strip()
            if name not in allowed_names:
                continue
            arguments = raw_call.get("arguments", function.get("arguments", {}))
            decoded_arguments = decode_tool_arguments(arguments)
            rewritten_name, rewritten_arguments = rewrite_tool_call(name, normalize_tool_arguments(name, decoded_arguments))
            rewritten_arguments = clamp_tool_arguments(rewritten_name, rewritten_arguments)
            tool_calls.append({
                "id": str(raw_call.get("id") or f"call_{uuid.uuid4().hex}"),
                "type": "function",
                "function": {"name": rewritten_name, "arguments": rewritten_arguments},
            })
        if tool_calls:
            return tool_calls
    return tool_calls


def should_force_tool_retry(content: str, allowed_names: set[str]) -> bool:
    if not allowed_names:
        return False
    if not tool_retry_enabled():
        return False
    text = str(content or "").strip()
    if not text:
        return True
    if parse_tool_calls(text, allowed_names):
        return False
    if TOOL_UNAVAILABLE_TEXT_RE.search(text):
        logger.info("agent_protocol violation: tool-unavailable claim, forcing retry")
        return True
    if PERMISSION_SEEKING_TEXT_RE.search(text):
        logger.info("agent_protocol violation: permission-seeking reply, forcing retry")
        return True
    # Treat trailing "I will read X next" plans as incomplete work: the model
    # should call the tool instead of narrating future actions.
    tail = text[-600:]
    if NEXT_STEP_ANNOUNCEMENT_RE.search(tail):
        logger.info("agent_protocol violation: next-step announcement without tool call, forcing retry")
        return True
    return False


def strip_raw_tool_json(text: str) -> str:
    """Remove leaked raw tool-call JSON fragments from model text output."""
    result = str(text or "")
    decoder = json.JSONDecoder()
    cleaned: list[str] = []
    index = 0
    while index < len(result):
        char = result[index]
        if char != "{":
            cleaned.append(char)
            index += 1
            continue
        try:
            payload, end = decoder.raw_decode(result[index:])
        except Exception:
            cleaned.append(char)
            index += 1
            continue
        is_tool_payload = isinstance(payload, dict) and (
            "tool_calls" in payload
            or ("name" in payload and "arguments" in payload)
            or ("command" in payload and len(payload) <= 2)
        )
        if is_tool_payload:
            index += end
            continue
        cleaned.append(char)
        index += 1
    return "".join(cleaned)
