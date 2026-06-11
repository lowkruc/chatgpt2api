#!/usr/bin/env python3
"""
Storage backend data migration script.

Usage:
  python scripts/migrate_storage.py --from json --to postgres
  python scripts/migrate_storage.py --from postgres --to git
  python scripts/migrate_storage.py --export accounts.json
  python scripts/migrate_storage.py --import accounts.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from services.storage.factory import create_storage_backend


def export_to_json(output_file: str):
    """Export data from the current storage backend to a JSON file."""
    print(f"[migrate] Exporting data to {output_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage = create_storage_backend(DATA_DIR)
    accounts = storage.load_accounts()
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(accounts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    
    print(f"[migrate] Exported {len(accounts)} accounts to {output_file}")


def import_from_json(input_file: str):
    """Import data from a JSON file into the current storage backend."""
    print(f"[migrate] Importing data from {input_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"[migrate] Error: File not found: {input_file}")
        sys.exit(1)
    
    try:
        accounts = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(accounts, list):
            print(f"[migrate] Error: Invalid JSON format, expected array")
            sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[migrate] Error: Invalid JSON: {e}")
        sys.exit(1)
    
    storage = create_storage_backend(DATA_DIR)
    storage.save_accounts(accounts)
    
    print(f"[migrate] Imported {len(accounts)} accounts")


def migrate_data(from_backend: str, to_backend: str):
    """Migrate data from one storage backend to another."""
    print(f"[migrate] Migrating from {from_backend} to {to_backend}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Save the original environment variables
    original_backend = os.environ.get("STORAGE_BACKEND")
    
    try:
        # Read data from the source backend
        os.environ["STORAGE_BACKEND"] = from_backend
        from_storage = create_storage_backend(DATA_DIR)
        accounts = from_storage.load_accounts()
        print(f"[migrate] Loaded {len(accounts)} accounts from {from_backend}")
        
        # Write data to the target backend
        os.environ["STORAGE_BACKEND"] = to_backend
        to_storage = create_storage_backend(DATA_DIR)
        to_storage.save_accounts(accounts)
        print(f"[migrate] Saved {len(accounts)} accounts to {to_backend}")
        
        print(f"[migrate] Migration completed successfully!")
        
    finally:
        # Restore the original environment variables
        if original_backend:
            os.environ["STORAGE_BACKEND"] = original_backend
        elif "STORAGE_BACKEND" in os.environ:
            del os.environ["STORAGE_BACKEND"]


def main():
    parser = argparse.ArgumentParser(
        description="ChatGPT2API storage backend data migration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate from JSON to PostgreSQL
  python scripts/migrate_storage.py --from json --to postgres
  
  # Migrate from PostgreSQL to Git
  python scripts/migrate_storage.py --from postgres --to git
  
  # Export current data to a JSON file
  python scripts/migrate_storage.py --export backup.json
  
  # Import data from a JSON file
  python scripts/migrate_storage.py --import backup.json

Environment variables:
  STORAGE_BACKEND  - storage backend type (json, sqlite, postgres, git)
  DATABASE_URL     - database connection string
  GIT_REPO_URL     - Git repository URL
  GIT_TOKEN        - Git access token
        """
    )
    
    parser.add_argument(
        "--from",
        dest="from_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="Source storage backend",
    )
    parser.add_argument(
        "--to",
        dest="to_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="Target storage backend",
    )
    parser.add_argument(
        "--export",
        dest="export_file",
        metavar="FILE",
        help="Export data to a JSON file",
    )
    parser.add_argument(
        "--import",
        dest="import_file",
        metavar="FILE",
        help="Import data from a JSON file",
    )
    
    args = parser.parse_args()
    
    # Check arguments
    if args.from_backend and args.to_backend:
        migrate_data(args.from_backend, args.to_backend)
    elif args.export_file:
        export_to_json(args.export_file)
    elif args.import_file:
        import_from_json(args.import_file)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
