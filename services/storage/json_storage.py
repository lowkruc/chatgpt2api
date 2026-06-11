from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.storage.base import StorageBackend


class JSONStorageBackend(StorageBackend):
    """Local JSON file storage backend."""

    def __init__(self, file_path: Path, auth_keys_path: Path | None = None):
        self.file_path = file_path
        self.auth_keys_path = auth_keys_path or file_path.with_name("auth_keys.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, Exception):
            return []

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_accounts(self) -> list[dict[str, Any]]:
        """Load account data from a JSON file."""
        return self._load_json_list(self.file_path)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """Save account data to a JSON file."""
        self._save_json_list(self.file_path, accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """Load auth key data from a JSON file."""
        if not self.auth_keys_path.exists():
            return []
        try:
            data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """Save auth key data to a JSON file."""
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.write_text(
            json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def health_check(self) -> dict[str, Any]:
        """Health check."""
        try:
            # Check whether the file is readable/writable
            if self.file_path.exists():
                self.file_path.read_text(encoding="utf-8")
            return {
                "status": "healthy",
                "backend": "json",
                "file_exists": self.file_path.exists(),
                "file_path": str(self.file_path),
                "auth_keys_file_exists": self.auth_keys_path.exists(),
                "auth_keys_file_path": str(self.auth_keys_path),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """Get storage backend info."""
        return {
            "type": "json",
            "description": "Local JSON file storage",
            "file_path": str(self.file_path),
            "file_exists": self.file_path.exists(),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
        }
