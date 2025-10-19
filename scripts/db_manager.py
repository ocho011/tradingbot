#!/usr/bin/env python3
"""
Database Management CLI Tool

Provides command-line interface for database operations:
- Initialization and table creation
- Migration management
- Backup and restore
- Schema validation
- Production-safe migrations
"""

import asyncio
import argparse
import sys
import logging
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.migrations import (
    init_database,
    create_all_tables,
    drop_all_tables,
    upgrade_database,
    downgrade_database,
    generate_migration,
    get_current_revision,
    get_migration_history,
    backup_database,
    restore_database,
    list_backups,
    validate_schema,
    safe_migrate,
    check_migration_safety,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


async def cmd_init(args: argparse.Namespace) -> None:
    """Initialize database with tables."""
    print_section("Database Initialization")

    try:
        await init_database(
            database_url=args.database_url,
            echo=args.verbose,
            create_tables=not args.no_tables,
            run_migrations=args.migrate,
        )
        print("✓ Database initialized successfully")
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        sys.exit(1)


async def cmd_create_tables(args: argparse.Namespace) -> None:
    """Create all database tables."""
    print_section("Creating Tables")

    try:
        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        await create_all_tables()
        print("✓ All tables created successfully")
    except Exception as e:
        logger.error(f"Table creation failed: {e}")
        sys.exit(1)


async def cmd_drop_tables(args: argparse.Namespace) -> None:
    """Drop all database tables."""
    print_section("Dropping Tables")

    if not args.force:
        response = input("⚠️  WARNING: This will delete ALL data! Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return

    try:
        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        await drop_all_tables()
        print("✓ All tables dropped")
    except Exception as e:
        logger.error(f"Table dropping failed: {e}")
        sys.exit(1)


async def cmd_migrate(args: argparse.Namespace) -> None:
    """Run database migrations."""
    print_section(f"Migration: {args.action}")

    try:
        if args.action == "upgrade":
            await upgrade_database(args.revision or "head")
            print(f"✓ Database upgraded to: {args.revision or 'head'}")

        elif args.action == "downgrade":
            if not args.revision:
                print("Error: Revision required for downgrade")
                sys.exit(1)
            await downgrade_database(args.revision)
            print(f"✓ Database downgraded to: {args.revision}")

        elif args.action == "current":
            revision = get_current_revision()
            print(f"Current revision: {revision or 'None (empty database)'}")

        elif args.action == "history":
            history = get_migration_history()
            if history:
                print("Migration History:")
                for item in history:
                    print(f"  {item['description']}")
            else:
                print("No migration history")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a new migration file."""
    print_section("Generate Migration")

    try:
        generate_migration(args.message, autogenerate=not args.no_autogenerate)
        print(f"✓ Migration generated: {args.message}")
    except Exception as e:
        logger.error(f"Migration generation failed: {e}")
        sys.exit(1)


async def cmd_backup(args: argparse.Namespace) -> None:
    """Create database backup."""
    print_section("Database Backup")

    try:
        backup_path = None
        if args.name:
            backup_path = Path(f"./data/backups/{args.name}")

        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        result_path = await backup_database(backup_path)
        print(f"✓ Backup created: {result_path}")
        print(f"  Size: {result_path.stat().st_size / 1024:.2f} KB")
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        sys.exit(1)


async def cmd_restore(args: argparse.Namespace) -> None:
    """Restore database from backup."""
    print_section("Database Restore")

    backup_path = Path(args.backup)

    if not backup_path.exists():
        print(f"Error: Backup file not found: {backup_path}")
        sys.exit(1)

    if not args.force:
        response = input(f"⚠️  WARNING: This will overwrite the current database! Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return

    try:
        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        await restore_database(backup_path, confirm=True)
        print(f"✓ Database restored from: {backup_path}")
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        sys.exit(1)


def cmd_list_backups(args: argparse.Namespace) -> None:
    """List all available backups."""
    print_section("Available Backups")

    try:
        backups = list_backups()

        if not backups:
            print("No backups found")
            return

        print(f"Found {len(backups)} backup(s):\n")
        for backup in backups:
            print(f"  {backup['name']}")
            print(f"    Created: {backup['created']}")
            print(f"    Size: {backup['size'] / 1024:.2f} KB")
            print(f"    Path: {backup['path']}\n")

    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        sys.exit(1)


async def cmd_validate(args: argparse.Namespace) -> None:
    """Validate database schema."""
    print_section("Schema Validation")

    try:
        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        results = await validate_schema()

        if results["valid"]:
            print("✓ Schema validation PASSED")
        else:
            print("✗ Schema validation FAILED")

        if results["missing_tables"]:
            print(f"\n  Missing tables: {', '.join(results['missing_tables'])}")

        if results["extra_tables"]:
            print(f"\n  Extra tables: {', '.join(results['extra_tables'])}")

        if results["errors"]:
            print("\n  Errors:")
            for error in results["errors"]:
                print(f"    - {error}")

        # Show table details if verbose
        if args.verbose and results["tables"]:
            print("\n  Table Details:")
            for table_name, table_info in results["tables"].items():
                status = "✓" if table_info.get("valid") else "✗"
                print(f"    {status} {table_name}")

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(1)


async def cmd_safe_migrate(args: argparse.Namespace) -> None:
    """Perform production-safe migration."""
    print_section("Safe Migration")

    try:
        from src.database.engine import init_db
        await init_db(database_url=args.database_url, echo=args.verbose, create_tables=False)

        results = await safe_migrate(
            target_revision=args.revision or "head",
            require_backup=not args.no_backup,
            dry_run=args.dry_run,
        )

        print(f"Initial revision: {results['initial_revision']}")

        if args.dry_run:
            print("\n✓ DRY RUN completed (no changes made)")
        else:
            print(f"Final revision: {results['final_revision']}")

            if results["backup_created"]:
                print(f"\n✓ Backup created: {results['backup_created']}")

            if results["validation"]:
                if results["validation"]["valid"]:
                    print("\n✓ Schema validation PASSED")
                else:
                    print("\n✗ Schema validation FAILED")

            if results["success"]:
                print("\n✓ Migration completed successfully")
            else:
                print("\n✗ Migration completed with errors")

        if results["errors"]:
            print("\nErrors:")
            for error in results["errors"]:
                print(f"  - {error}")

    except Exception as e:
        logger.error(f"Safe migration failed: {e}")
        sys.exit(1)


def cmd_safety_check(args: argparse.Namespace) -> None:
    """Check if it's safe to perform migrations."""
    print_section("Migration Safety Check")

    try:
        results = check_migration_safety()

        if results["safe"]:
            print("✓ Safe to perform migrations")
        else:
            print("✗ Not safe to perform migrations")

        print("\nChecks:")
        for check, status in results["checks"].items():
            status_icon = "✓" if status else "✗"
            print(f"  {status_icon} {check}: {status}")

        if results["warnings"]:
            print("\nWarnings:")
            for warning in results["warnings"]:
                print(f"  ⚠️  {warning}")

    except Exception as e:
        logger.error(f"Safety check failed: {e}")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Database Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global arguments
    parser.add_argument(
        "--database-url",
        help="Database connection URL (overrides environment)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize database")
    init_parser.add_argument("--no-tables", action="store_true", help="Don't create tables")
    init_parser.add_argument("--migrate", action="store_true", help="Run migrations after init")

    # Create tables command
    subparsers.add_parser("create-tables", help="Create all database tables")

    # Drop tables command
    drop_parser = subparsers.add_parser("drop-tables", help="Drop all database tables")
    drop_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Run migrations")
    migrate_parser.add_argument(
        "action",
        choices=["upgrade", "downgrade", "current", "history"],
        help="Migration action",
    )
    migrate_parser.add_argument("--revision", help="Target revision")

    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate migration file")
    generate_parser.add_argument("message", help="Migration message")
    generate_parser.add_argument(
        "--no-autogenerate",
        action="store_true",
        help="Don't use autogenerate",
    )

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create database backup")
    backup_parser.add_argument("--name", help="Backup filename")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("backup", help="Path to backup file")
    restore_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # List backups command
    subparsers.add_parser("list-backups", help="List available backups")

    # Validate command
    subparsers.add_parser("validate", help="Validate database schema")

    # Safe migrate command
    safe_migrate_parser = subparsers.add_parser(
        "safe-migrate",
        help="Production-safe migration",
    )
    safe_migrate_parser.add_argument("--revision", help="Target revision (default: head)")
    safe_migrate_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation",
    )
    safe_migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without applying changes",
    )

    # Safety check command
    subparsers.add_parser("safety-check", help="Check migration safety")

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    command_map = {
        "init": cmd_init,
        "create-tables": cmd_create_tables,
        "drop-tables": cmd_drop_tables,
        "migrate": cmd_migrate,
        "generate": cmd_generate,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "list-backups": cmd_list_backups,
        "validate": cmd_validate,
        "safe-migrate": cmd_safe_migrate,
        "safety-check": cmd_safety_check,
    }

    command_func = command_map[args.command]

    # Run async commands with asyncio
    if asyncio.iscoroutinefunction(command_func):
        asyncio.run(command_func(args))
    else:
        command_func(args)


if __name__ == "__main__":
    main()
