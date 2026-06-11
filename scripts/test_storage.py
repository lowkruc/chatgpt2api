#!/usr/bin/env python3
"""
Storage backend test script.

Usage:
  python scripts/test_storage.py
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from services.storage.factory import create_storage_backend


def test_storage():
    """Test the currently configured storage backend."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("ChatGPT2API storage backend test")
    print("=" * 60)
    
    # Show the current config
    backend_type = os.getenv("STORAGE_BACKEND", "json")
    print(f"\nCurrent storage backend: {backend_type}")
    
    if backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = os.getenv("DATABASE_URL", "")
        if database_url:
            # Hide the password
            if "://" in database_url and "@" in database_url:
                protocol, rest = database_url.split("://", 1)
                if "@" in rest:
                    credentials, host = rest.split("@", 1)
                    if ":" in credentials:
                        username, _ = credentials.split(":", 1)
                        database_url = f"{protocol}://{username}:****@{host}"
            print(f"Database connection: {database_url}")
        else:
            print(f"Database connection: local SQLite (data/accounts.db)")
    
    elif backend_type == "git":
        repo_url = os.getenv("GIT_REPO_URL", "")
        branch = os.getenv("GIT_BRANCH", "main")
        file_path = os.getenv("GIT_FILE_PATH", "accounts.json")
        print(f"Git repository: {repo_url}")
        print(f"Git branch: {branch}")
        print(f"File path: {file_path}")
    
    print("\n" + "=" * 60)
    
    try:
        # Create the storage backend
        print("\n[1/5] Creating storage backend...")
        storage = create_storage_backend(DATA_DIR)
        print("✅ Storage backend created successfully")
        
        # Get backend info
        print("\n[2/5] Getting backend info...")
        info = storage.get_backend_info()
        print(f"✅ Backend type: {info.get('type')}")
        print(f"   Description: {info.get('description')}")
        for key, value in info.items():
            if key not in ('type', 'description'):
                print(f"   {key}: {value}")
        
        # Health check
        print("\n[3/5] Running health check...")
        health = storage.health_check()
        status = health.get("status")
        if status == "healthy":
            print(f"✅ Health status: {status}")
        else:
            print(f"❌ Health status: {status}")
            print(f"   Error: {health.get('error')}")
            return False
        
        # Read data
        print("\n[4/5] Reading account data...")
        accounts = storage.load_accounts()
        print(f"✅ Successfully read {len(accounts)} accounts")
        
        # Write test (optional)
        print("\n[5/5] Testing write capability...")
        test_account = {
            "access_token": "test_token_" + str(os.getpid()),
            "type": "Free",
            "status": "test",
            "quota": 0,
            "email": "test@example.com",
        }
        
        # Add a test account
        test_accounts = accounts + [test_account]
        storage.save_accounts(test_accounts)
        print("✅ Test account written successfully")
        
        # Verify the write
        reloaded = storage.load_accounts()
        if len(reloaded) == len(test_accounts):
            print("✅ Write verified successfully")
        else:
            print(f"❌ Verification failed: expected {len(test_accounts)} accounts, got {len(reloaded)}")
            return False
        
        # Restore the original data
        storage.save_accounts(accounts)
        print("✅ Original data restored")
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_storage()
    sys.exit(0 if success else 1)
