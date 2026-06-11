from __future__ import annotations

import os
from pathlib import Path

from services.storage.base import StorageBackend
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.git_storage import GitStorageBackend
from services.storage.json_storage import JSONStorageBackend


def create_storage_backend(data_dir: Path) -> StorageBackend:
    """
    Create a storage backend based on environment variables.
    
    Environment variables:
    - STORAGE_BACKEND: json|sqlite|postgres|git (default json)
    - DATABASE_URL: database connection string (for sqlite/postgres)
    - GIT_REPO_URL: Git repository URL (for git)
    - GIT_TOKEN: Git access token (for git)
    - GIT_BRANCH: Git branch (default main)
    - GIT_FILE_PATH: file path inside the Git repository (default accounts.json)
    """
    backend_type = os.getenv("STORAGE_BACKEND", "json").lower().strip()
    
    print(f"[storage] Initializing storage backend: {backend_type}")
    
    if backend_type == "json":
        # Local JSON file storage
        file_path = data_dir / "accounts.json"
        auth_keys_path = data_dir / "auth_keys.json"
        print(f"[storage] Using JSON storage: {file_path}")
        return JSONStorageBackend(file_path, auth_keys_path)
    
    elif backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        # Database storage
        database_url = os.getenv("DATABASE_URL", "").strip()
        
        if not database_url:
            # If no DATABASE_URL is provided, use a local SQLite database
            database_url = f"sqlite:///{data_dir / 'accounts.db'}"
            print(f"[storage] No DATABASE_URL provided, using local SQLite: {database_url}")
        else:
            print(f"[storage] Using database storage: {_mask_password(database_url)}")
        
        return DatabaseStorageBackend(database_url)
    
    elif backend_type == "git":
        # Git repository storage
        repo_url = os.getenv("GIT_REPO_URL", "").strip()
        token = os.getenv("GIT_TOKEN", "").strip()
        branch = os.getenv("GIT_BRANCH", "main").strip()
        file_path = os.getenv("GIT_FILE_PATH", "accounts.json").strip()
        auth_keys_file_path = os.getenv("GIT_AUTH_KEYS_FILE_PATH", "auth_keys.json").strip()
        
        if not repo_url:
            raise ValueError(
                "GIT_REPO_URL is required when using git storage backend. "
                "Please set GIT_REPO_URL environment variable."
            )
        
        print(f"[storage] Using Git storage: {_mask_token(repo_url)}, branch: {branch}, file: {file_path}")
        
        cache_dir = data_dir / "git_cache"
        return GitStorageBackend(
            repo_url=repo_url,
            token=token,
            branch=branch,
            file_path=file_path,
            auth_keys_file_path=auth_keys_file_path,
            local_cache_dir=cache_dir,
        )
    
    else:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Supported backends: json, sqlite, postgres, git"
        )


def _mask_password(url: str) -> str:
    """Hide the password in the database connection string."""
    if "://" not in url:
        return url
    try:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.split("@", 1)
            if ":" in credentials:
                username, _ = credentials.split(":", 1)
                return f"{protocol}://{username}:****@{host}"
        return url
    except Exception:
        return url


def _mask_token(url: str) -> str:
    """Hide the token in the URL."""
    if "@" in url and "://" in url:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{protocol}://****@{host}"
    return url
