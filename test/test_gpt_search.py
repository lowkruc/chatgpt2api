from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.openai_backend_api import OpenAIBackendAPI


def main() -> None:
    ACCESS_TOKEN = ""
    PROMPT = "Search the web for projects related to chatgpt2api"
    if not ACCESS_TOKEN.strip():
        raise ValueError("ACCESS_TOKEN is empty")
    print(json.dumps(OpenAIBackendAPI(ACCESS_TOKEN).search(PROMPT), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
