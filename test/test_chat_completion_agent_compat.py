from __future__ import annotations

import unittest
from unittest.mock import patch

from services.protocol import agent_compat
from services.protocol.openai_v1_chat_complete import (
    build_phase_system_message,
    build_tool_call_system_message,
    completions_handle,
    parse_tool_calls,
    prepare_agent_messages,
    should_force_tool_retry,
    strip_raw_tool_json,
    text_chat_parts,
    wants_json_mode,
)
from services.protocol.openai_v1_response import handle as responses_handle, messages_from_input
from services.protocol.openai_v1_response import response_events


class ChatCompletionAgentCompatTests(unittest.TestCase):
    def test_prepare_agent_messages_maps_developer_and_tool_roles(self):
        messages = prepare_agent_messages([
            {"role": "developer", "content": "Use terse answers."},
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": "{}"}}]},
        ])

        self.assertEqual(messages[0], {"role": "system", "content": "Use terse answers."})
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("Tool result for call_1", messages[1]["content"])
        self.assertEqual(messages[2]["role"], "assistant")
        self.assertIn("read_file", messages[2]["content"])

    def test_parse_tool_calls_accepts_json_block(self):
        calls = parse_tool_calls(
            '```json\n{"tool_calls":[{"name":"read_file","arguments":{"path":"main.py"}}]}\n```',
            {"read_file"},
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["type"], "function")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(calls[0]["function"]["arguments"], '{"path":"main.py"}')

    def test_parse_tool_calls_accepts_json_embedded_in_text(self):
        calls = parse_tool_calls(
            'before {"tool_calls":[{"name":"read_file","arguments":{"path":"README.md"}}]} after',
            {"read_file"},
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(calls[0]["function"]["arguments"], '{"path":"README.md"}')

    def test_parse_tool_calls_normalizes_common_bash_spacing_typos(self):
        calls = parse_tool_calls(
            '{"tool_calls":[{"name":"bash","arguments":{"command":"pwd && find. -maxdepth 2 -type f"}}]}',
            {"bash"},
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["arguments"], '{"command":"pwd && find . -maxdepth 2 -type f"}')

    def test_parse_tool_calls_infers_bare_command_json_as_bash_call(self):
        calls = parse_tool_calls('{"command":"ls -R"}{"command":"ls -la"}', {"bash"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "bash")
        self.assertEqual(calls[0]["function"]["arguments"], '{"command":"ls -R"}')

    def test_parse_tool_calls_infers_read_from_path_payload(self):
        calls = parse_tool_calls('{"path":"README.md"}', {"read"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read")
        self.assertEqual(calls[0]["function"]["arguments"], '{"path":"README.md","offset":1,"limit":200}')

    def test_parse_tool_calls_rewrites_directory_read_to_ls(self):
        calls = parse_tool_calls('{"path":"."}', {"read", "ls"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "ls")
        self.assertEqual(calls[0]["function"]["arguments"], '{"path":".","limit":200}')

    def test_json_mode_detection(self):
        self.assertTrue(wants_json_mode({"response_format": {"type": "json_object"}}))
        self.assertTrue(wants_json_mode({"response_format": {"type": "json_schema"}}))
        self.assertFalse(wants_json_mode({"response_format": {"type": "text"}}))

    def test_tool_prompt_includes_available_tool_schema(self):
        prompt = build_tool_call_system_message([{
            "type": "function",
            "name": "read_file",
            "description": "Read a local file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }])

        self.assertIn("Available tools", prompt)
        self.assertIn("read_file", prompt)
        self.assertIn("path", prompt)
        self.assertIn("MODE A", prompt)
        self.assertIn("MODE B", prompt)
        self.assertIn("Never say tools are unavailable", prompt)

    def test_retry_policy_triggers_on_tool_unavailable_text(self):
        self.assertTrue(should_force_tool_retry("I don't have access to that tool here.", {"bash"}))
        self.assertFalse(should_force_tool_retry('{"tool_calls":[{"name":"bash","arguments":{"command":"pwd"}}]}', {"bash"}))

    def test_retry_policy_triggers_on_permission_seeking_text(self):
        self.assertTrue(should_force_tool_retry(
            "Tentu! Untuk memahami codebase, saya perlu sedikit konteks. Apakah mau saya lakukan itu dulu?",
            {"bash", "read"},
        ))
        self.assertTrue(should_force_tool_retry("Should I start by scanning the project folder?", {"read"}))
        self.assertFalse(should_force_tool_retry("Arsitektur project ini terdiri dari API layer dan services.", {"read"}))

    def test_retry_policy_triggers_on_next_step_announcement(self):
        self.assertTrue(should_force_tool_retry(
            "Berdasarkan struktur repo, area terbesar adalah Account Pool. "
            "Kalau langkah berikutnya adalah memahami arsitektur internal, saya akan membaca main.py dan api/app.py.",
            {"read", "ls"},
        ))
        self.assertTrue(should_force_tool_retry("Next step: I will read services/config.py to confirm.", {"read"}))
        self.assertFalse(should_force_tool_retry(
            "Arsitektur lengkap: main.py memanggil create_app() dari api/app.py yang me-register router.",
            {"read"},
        ))

    def test_agent_protocol_config_override_and_retry_toggle(self):
        with patch.object(agent_compat, "_agent_protocol_settings", return_value={
            "system_prompt_override": "CUSTOM PROTOCOL PROMPT",
            "extra_rules": "Always answer in Indonesian.",
            "retry_enabled": True,
        }):
            prompt = build_tool_call_system_message([{"type": "function", "name": "read"}])
            self.assertIn("CUSTOM PROTOCOL PROMPT", prompt)
            self.assertIn("EXTRA RULES", prompt)
            self.assertIn("Always answer in Indonesian.", prompt)
            self.assertNotIn("MODE A", prompt)

        with patch.object(agent_compat, "_agent_protocol_settings", return_value={
            "system_prompt_override": "",
            "extra_rules": "",
            "retry_enabled": False,
        }):
            self.assertFalse(should_force_tool_retry("Apakah mau saya lakukan itu dulu?", {"read"}))

    def test_strip_raw_tool_json_removes_leaked_payloads(self):
        text = (
            'Saya bisa membaca package.json jika ada.'
            '{"tool_calls":[{"name":"bash","arguments":{"command":"find . -type f"}}]}'
            ' Lanjut analisis.'
        )
        self.assertEqual(strip_raw_tool_json(text), "Saya bisa membaca package.json jika ada. Lanjut analisis.")
        self.assertEqual(strip_raw_tool_json('{"command":"ls -R"}halo'), "halo")
        self.assertEqual(strip_raw_tool_json("plain text only"), "plain text only")

    def test_responses_stream_does_not_call_upstream_thrice_on_tool_failure(self):
        call_count = 0

        def fake_stream_text_deltas(_backend, _request):
            nonlocal call_count
            call_count += 1
            yield "Apakah mau saya lakukan itu dulu?"

        with patch("services.protocol.openai_v1_response.text_backend", return_value=object()), \
                patch("services.protocol.openai_v1_response.stream_text_deltas", side_effect=fake_stream_text_deltas):
            events = list(response_events({
                "model": "auto",
                "input": "pahami codebase ini",
                "stream": True,
                "tools": [{"type": "function", "name": "read"}],
            }))

        self.assertEqual(call_count, 2)
        completed = next(event for event in events if event["type"] == "response.completed")
        self.assertEqual(completed["response"]["output"][0]["type"], "message")

    def test_phase_hint_inferred_from_intent(self):
        self.assertIn("inspect", build_phase_system_message("pahami codebase ini", {"read", "ls"}).lower())
        self.assertIn("read/grep/find", build_phase_system_message("fix bug di auth middleware", {"read", "edit"}))
        self.assertEqual(build_phase_system_message("halo apa kabar", {"read"}), "")

    def test_text_chat_parts_inserts_phase_hint_for_agent_prompt(self):
        _model, messages = text_chat_parts({
            "model": "auto",
            "messages": [{"role": "user", "content": "pahami codebase ini lalu jelaskan arsitektur"}],
            "tools": [{"type": "function", "name": "read"}, {"type": "function", "name": "ls"}],
        })

        system_texts = [str(m.get("content") or "") for m in messages if m.get("role") == "system"]
        self.assertTrue(any("Inspect before answering" in text for text in system_texts))

    def test_legacy_completions_handle_maps_prompt_to_text_completion(self):
        with patch("services.protocol.openai_v1_chat_complete.text_backend", return_value=object()), \
                patch("services.protocol.openai_v1_chat_complete.collect_text", return_value="hello"):
            response = completions_handle({"model": "auto", "prompt": "Say hello"})

        self.assertEqual(response["object"], "text_completion")
        self.assertEqual(response["choices"][0]["text"], "hello")
        self.assertEqual(response["choices"][0]["finish_reason"], "stop")

    def test_responses_function_call_output_maps_to_tool_role(self):
        messages = messages_from_input([
            {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{\"path\":\"main.py\"}"},
            {"type": "function_call_output", "call_id": "call_1", "output": "print('ok')"},
        ])

        self.assertEqual(messages[0]["role"], "assistant")
        self.assertEqual(messages[1]["role"], "tool")
        self.assertEqual(messages[1]["tool_call_id"], "call_1")

    def test_responses_tool_json_becomes_function_call_item(self):
        def fake_stream_text_deltas(_backend, _request):
            yield '{"tool_calls":[{"name":"read_file","arguments":{"path":"main.py"}}]}'

        with patch("services.protocol.openai_v1_response.text_backend", return_value=object()), \
                patch("services.protocol.openai_v1_response.stream_text_deltas", side_effect=fake_stream_text_deltas):
            response = responses_handle({
                "model": "auto",
                "input": "read main.py",
                "tools": [{"type": "function", "name": "read_file"}],
            })

        self.assertEqual(response["object"], "response")
        self.assertEqual(response["output"][0]["type"], "function_call")
        self.assertEqual(response["output"][0]["name"], "read_file")
        self.assertEqual(response["output"][0]["arguments"], '{"path":"main.py"}')

    def test_responses_stream_emits_pi_compatible_function_call_events(self):
        def fake_stream_text_deltas(_backend, _request):
            yield '{"tool_calls":[{"name":"read_file","arguments":{"path":"main.py"}}]}'

        with patch("services.protocol.openai_v1_response.text_backend", return_value=object()), \
                patch("services.protocol.openai_v1_response.stream_text_deltas", side_effect=fake_stream_text_deltas):
            events = list(response_events({
                "model": "auto",
                "input": "read main.py",
                "stream": True,
                "tools": [{"type": "function", "name": "read_file"}],
            }))

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[0], "response.created")
        self.assertIn("response.output_item.added", event_types)
        self.assertIn("response.function_call_arguments.done", event_types)
        self.assertIn("response.output_item.done", event_types)
        added = next(event for event in events if event["type"] == "response.output_item.added")
        done = next(event for event in events if event["type"] == "response.output_item.done")
        self.assertEqual(added["item"]["type"], "function_call")
        self.assertTrue(done["item"]["id"].startswith("fc_"))

    def test_responses_retries_once_when_model_claims_tool_unavailable(self):
        attempts = iter([
            ["I don't have access to that tool here."],
            ['{"tool_calls":[{"name":"read_file","arguments":{"path":"main.py"}}]}'],
        ])

        def fake_stream_text_deltas(_backend, _request):
            yield from next(attempts)

        with patch("services.protocol.openai_v1_response.text_backend", return_value=object()), \
                patch("services.protocol.openai_v1_response.stream_text_deltas", side_effect=fake_stream_text_deltas):
            response = responses_handle({
                "model": "auto",
                "input": "read main.py",
                "tools": [{"type": "function", "name": "read_file"}],
            })

        self.assertEqual(response["output"][0]["type"], "function_call")
        self.assertEqual(response["output"][0]["name"], "read_file")


if __name__ == "__main__":
    unittest.main()
