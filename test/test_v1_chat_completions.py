from __future__ import annotations

import json
import time
import unittest

import requests

from utils.helper import save_images_from_text

AUTH_KEY = "chatgpt2api"
BASE_URL = "http://localhost:8000"


class ChatCompletionsTests(unittest.TestCase):
    def test_text_completion_http(self):
        """Test the non-streaming HTTP call for text chat."""
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            json={
                "model": "auto",
                "messages": [
                    {"role": "user", "content": "Hello."},
                    {"role": "assistant", "content": "Hello, I can help you with text and image related requests."},
                    {"role": "user", "content": "Then please briefly introduce yourself."},
                ],
            },
            timeout=300,
        )
        print("text non-stream status:")
        print(response.status_code)
        print("text non-stream result:")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))

    def test_text_completion_stream_http(self):
        """Test the streaming HTTP call for text chat."""
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            json={
                "model": "auto",
                "stream": True,
                "messages": [
                    {"role": "user", "content": "Hello."},
                    {"role": "assistant", "content": "Hello, my name is Claude."},
                    {"role": "user", "content": "Then please briefly introduce yourself, such as what your name is."},
                ],
            },
            stream=True,
            timeout=300,
        )
        print("text stream status:")
        print(response.status_code)
        print("text stream result:")
        for line in response.iter_lines():
            if line:
                print(line.decode("utf-8", errors="replace"))

    def test_image_completion_http(self):
        """Test the non-streaming HTTP call for image chat."""
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            json={
                "model": "gpt-image-2",
                "messages": [
                    {"role": "user", "content": "I want to create a Nanjing city promotional poster."},
                ],
                "n": 1,
            },
            timeout=300,
        )
        payload = response.json()
        content = str((((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""))
        saved_paths = save_images_from_text(content, "chat_completions_image_non_stream")
        print("image non-stream status:")
        print(response.status_code)
        print("image non-stream saved files:")
        for path in saved_paths:
            print(path)

    def test_image_completion_stream_http(self):
        """Test the streaming HTTP call for image chat."""
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            json={
                "model": "gpt-image-2",
                "stream": True,
                "messages": [
                    {"role": "user", "content": "I want to create a Nanjing city promotional poster."},
                ],
                "n": 1,
            },
            stream=True,
            timeout=300,
        )
        parts: list[str] = []
        started_at = time.time()
        print("image stream status:")
        print(response.status_code)
        print("image stream chunks:")
        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8", errors="replace")
            print(f"{time.time() - started_at:6.2f}s {text}")
            if not text.startswith("data:"):
                continue
            payload = text[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except Exception:
                continue
            delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
            content = str(delta.get("content") or "")
            if content:
                parts.append(content)
        saved_paths = save_images_from_text("".join(parts), "chat_completions_image_stream")
        print("image stream saved files:")
        for path in saved_paths:
            print(path)
