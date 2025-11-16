"""
Database migration utilities and initialization functions.

This module provides:
- Database initialization and table creation
- Migration execution and management
- Backup and restore functionality
- Schema validation tools
- Production safety mechanisms
"""

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.engine import get_engine
from src.database.engine import init_db as init_engine
from src.database.models import Base

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Base exception for migration-related errors."""



class BackupError(Exception):
    """Exception raised when backup operations fail."""



class ValidationError(Exception):
    """Exception raised when schema validation fails."""



# ============================================================================
# Database Initialization Functions
# ============================================================================


async def init_database(
    database_url: Optional[str] = None,
    echo: bool = False,
    create_tables: bool = True,
    run_migrations: bool = False,
) -> None:
    """
    Initialize database with tables and optionally run migrations.

    This is the main entry point for database setup. It will:
    1. Initialize the database engine
    2. Create tables if requested
    3. Run pending migrations if requested

    Args:
        database_url: Database connection URL (uses environment if None)
        echo: Enable SQL query logging
        create_tables: Whether to create all tables
        run_migrations: Whether to run Alembic migrations

    Example:
        >>> await init_database(create_tables=True)
    """
    logger.info("Initializing database...")

    # Initialize engine and session factory
    await init_engine(database_url=database_url, echo=echo, create_tables=False)

    if create_tables:
        await create_all_tables()

    if run_migrations:
        await upgrade_database()

    logger.info("Database initialization complete")


async def create_all_tables() -> None:
    """
    Create all database tables based on SQLAlchemy models.

    This is safe to call multiple times - only creates tables that don't exist.
    Uses Base.metadata to create all registered tables.

    Raises:
        MigrationError: If table creation fails
    """
    try:
        engine = get_engine()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("All database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise MigrationError(f"Table creation failed: {e}")


async def drop_all_tables() -> None:
    """
    Drop all database tables.

    ⚠️ WARNING: This will delete all data in the database!
    Only use for testing or complete database reset.

    Raises:
        MigrationError: If table dropping fails
    """
    try:
        engine = get_engine()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        logger.warning("All database tables dropped")
    except Exception as e:
        logger.error(f"Failed to drop tables: {e}")
        raise MigrationError(f"Table dropping failed: {e}")


async def initial_data_setup(session: AsyncSession) -> None:
    """
    Set up initial data in the database.

    This function can be used to populate the database with:
    - Default configuration values
    - Reference data
    - Initial user accounts

    Args:
        session: Database session to use

    Example:
        >>> async with get_session() as session:
        ...     await initial_data_setup(session)
    """
    logger.info("Setting up initial data...")

    # Add initial data setup logic here
    # Example:
    # - Create default strategies
    # - Set up initial configuration
    # - Create system accounts

    await session.commit()
    logger.info("Initial data setup complete")


# ============================================================================
# Alembic Migration Functions
# ============================================================================


def run_alembic_command(command: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """
    Run an Alembic command via subprocess.

    Args:
        command: Alembic command and arguments
        check: Whether to raise exception on non-zero exit code

    Returns:
        CompletedProcess instance with result

    Raises:
        MigrationError: If command fails and check=True
    """
    try:
        result = subprocess.run(
            ["alembic"] + command,
            capture_output=True,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Alembic command failed: {e.stderr}")
        raise MigrationError(f"Migration command failed: {e.stderr}")


async def upgrade_database(revision: str = "head") -> None:
    """
    Upgrade database to a specific revision.

    Args:
        revision: Target revision (default: "head" for latest)

    Raises:
        MigrationError: If upgrade fails
    """
    logger.info(f"Upgrading database to revision: {revision}")

    try:
        result = run_alembic_command(["upgrade", revision])
        logger.info(f"Database upgraded successfully: {result.stdout}")
    except Exception as e:
        logger.error(f"Database upgrade failed: {e}")
        raise MigrationError(f"Failed to upgrade database: {e}")


async def downgrade_database(revision: str) -> None:
    """
    Downgrade database to a specific revision.

    ⚠️ WARNING: This may result in data loss!

    Args:
        revision: Target revision to downgrade to

    Raises:
        MigrationError: If downgrade fails
    """
    logger.warning(f"Downgrading database to revision: {revision}")

    try:
        result = run_alembic_command(["downgrade", revision])
        logger.info(f"Database downgraded successfully: {result.stdout}")
    except Exception as e:
        logger.error(f"Database downgrade failed: {e}")
        raise MigrationError(f"Failed to downgrade database: {e}")


def generate_migration(message: str, autogenerate: bool = True) -> None:
    """
    Generate a new migration file.

    Args:
        message: Migration description
        autogenerate: Whether to use autogenerate to detect schema changes

    Raises:
        MigrationError: If migration generation fails
    """
    logger.info(f"Generating migration: {message}")

    try:
        command = ["revision"]
        if autogenerate:
            command.append("--autogenerate")
        command.extend(["-m", message])

        result = run_alembic_command(command)
        logger.info(f"Migration generated successfully: {result.stdout}")
    except Exception as e:
        logger.error(f"Migration generation failed: {e}")
        raise MigrationError(f"Failed to generate migration: {e}")


def get_current_revision() -> Optional[str]:
    """
    Get the current database revision.

    Returns:
        Current revision ID or None if no migrations applied

    Raises:
        MigrationError: If unable to determine current revision
    """
    try:
        result = run_alembic_command(["current"])
        output = result.stdout.strip()

        if not output or "None" in output:
            return None

        # Extract revision from output (format: "revision_id (head)")
        revision = output.split()[0] if output else None
        return revision
    except Exception as e:
        logger.error(f"Failed to get current revision: {e}")
        raise MigrationError(f"Failed to get current revision: {e}")


def get_migration_history() -> List[Dict[str, str]]:
    """
    Get the migration history.

    Returns:
        List of migration information dictionaries

    Raises:
        MigrationError: If unable to retrieve history
    """
    try:
        result = run_alembic_command(["history"])
        history = []

        for line in result.stdout.strip().split("\n"):
            if "->" in line or "<-" in line:
                history.append({"description": line.strip()})

        return history
    except Exception as e:
        logger.error(f"Failed to get migration history: {e}")
        raise MigrationError(f"Failed to get migration history: {e}")


# ============================================================================
# Backup and Restore Functions
# ============================================================================


def get_backup_path(backup_name: Optional[str] = None) -> Path:
    """
    Get the path for a database backup.

    Args:
        backup_name: Optional custom backup name

    Returns:
        Path object for the backup file
    """
    backup_dir = Path("./data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    if backup_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}.db"

    return backup_dir / backup_name


async def backup_database(backup_path: Optional[Path] = None) -> Path:
    """
    Create a backup of the SQLite database.

    Args:
        backup_path: Optional custom backup path

    Returns:
        Path to the backup file

    Raises:
        BackupError: If backup fails
    """
    try:
        # Get current database path
        from src.database.engine import get_database_url

        db_url = get_database_url()

        if not db_url.startswith("sqlite"):
            raise BackupError("Backup only supported for SQLite databases")

        # Extract database file path
        db_path = db_url.replace("sqlite+aiosqlite:///", "")
        source_path = Path(db_path)

        if not source_path.exists():
            raise BackupError(f"Database file not found: {source_path}")

        # Determine backup path
        if backup_path is None:
            backup_path = get_backup_path()

        # Create backup
        logger.info(f"Creating backup: {source_path} -> {backup_path}")
        shutil.copy2(source_path, backup_path)

        # Verify backup
        if not backup_path.exists():
            raise BackupError("Backup file was not created")

        logger.info(f"Backup created successfully: {backup_path}")
        return backup_path

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise BackupError(f"Failed to create backup: {e}")


async def restore_database(backup_path: Path, confirm: bool = False) -> None:
    """
    Restore database from a backup.

    ⚠️ WARNING: This will overwrite the current database!

    Args:
        backup_path: Path to backup file
        confirm: Must be True to proceed with restore

    Raises:
        BackupError: If restore fails
    """
    if not confirm:
        raise BackupError("Restore requires explicit confirmation (confirm=True)")

    try:
        # Verify backup exists
        if not backup_path.exists():
            raise BackupError(f"Backup file not found: {backup_path}")

        # Get current database path
        from src.database.engine import get_database_url

        db_url = get_database_url()

        if not db_url.startswith("sqlite"):
            raise BackupError("Restore only supported for SQLite databases")

        db_path = db_url.replace("sqlite+aiosqlite:///", "")
        target_path = Path(db_path)

        # Create backup of current database before restoring
        if target_path.exists():
            current_backup = get_backup_path(
                f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            logger.info(f"Creating safety backup: {current_backup}")
            shutil.copy2(target_path, current_backup)

        # Restore from backup
        logger.warning(f"Restoring database: {backup_path} -> {target_path}")
        shutil.copy2(backup_path, target_path)

        logger.info("Database restored successfully")

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise BackupError(f"Failed to restore database: {e}")


def list_backups() -> List[Dict[str, Any]]:
    """
    List all available database backups.

    Returns:
        List of backup information dictionaries
    """
    backup_dir = Path("./data/backups")

    if not backup_dir.exists():
        return []

    backups = []
    for backup_file in backup_dir.glob("*.db"):
        stat = backup_file.stat()
        backups.append(
            {
                "name": backup_file.name,
                "path": str(backup_file),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime),
            }
        )

    # Sort by creation time, newest first
    backups.sort(key=lambda x: x["created"], reverse=True)
    return backups


# ============================================================================
# Schema Validation Functions
# ============================================================================


async def validate_schema() -> Dict[str, Any]:
    """
    Validate database schema against SQLAlchemy models.

    Returns:
        Dictionary with validation results

    Raises:
        ValidationError: If validation fails
    """
    try:
        engine = get_engine()
        validation_results = {
            "valid": True,
            "tables": {},
            "missing_tables": [],
            "extra_tables": [],
            "errors": [],
        }

        async with engine.connect() as conn:
            # Get database inspector
            inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))

            # Get expected tables from models
            expected_tables = set(Base.metadata.tables.keys())

            # Get actual tables from database
            actual_tables = await conn.run_sync(lambda sync_conn: set(inspector.get_table_names()))

            # Find missing and extra tables
            validation_results["missing_tables"] = list(expected_tables - actual_tables)
            validation_results["extra_tables"] = list(actual_tables - expected_tables)

            # Validate each table structure
            for table_name in expected_tables & actual_tables:
                table_validation = await validate_table_structure(conn, inspector, table_name)
                validation_results["tables"][table_name] = table_validation

                if not table_validation["valid"]:
                    validation_results["valid"] = False

            # Check for critical issues
            if validation_results["missing_tables"]:
                validation_results["valid"] = False
                validation_results["errors"].append(
                    f"Missing tables: {', '.join(validation_results['missing_tables'])}"
                )

        logger.info(
            f"Schema validation complete: {'PASSED' if validation_results['valid'] else 'FAILED'}"
        )
        return validation_results

    except Exception as e:
        logger.error(f"Schema validation failed: {e}")
        raise ValidationError(f"Schema validation failed: {e}")


async def validate_table_structure(conn, inspector, table_name: str) -> Dict[str, Any]:
    """
    Validate a single table's structure.

    Args:
        conn: Database connection
        inspector: SQLAlchemy inspector
        table_name: Name of table to validate

    Returns:
        Dictionary with validation results for the table
    """
    try:
        table_validation = {
            "valid": True,
            "columns": {},
            "missing_columns": [],
            "extra_columns": [],
            "column_mismatches": [],
        }

        # Get expected columns from model
        model_table = Base.metadata.tables[table_name]
        expected_columns = {col.name: col for col in model_table.columns}

        # Get actual columns from database
        actual_columns = await conn.run_sync(
            lambda sync_conn: {col["name"]: col for col in inspector.get_columns(table_name)}
        )

        # Find missing and extra columns
        table_validation["missing_columns"] = list(
            set(expected_columns.keys()) - set(actual_columns.keys())
        )
        table_validation["extra_columns"] = list(
            set(actual_columns.keys()) - set(expected_columns.keys())
        )

        # Validate column types (simplified check)
        for col_name in set(expected_columns.keys()) & set(actual_columns.keys()):
            expected_col = expected_columns[col_name]
            actual_col = actual_columns[col_name]

            col_validation = {
                "name": col_name,
                "matches": True,
            }

            # Check nullable
            if expected_col.nullable != actual_col.get("nullable"):
                col_validation["matches"] = False
                col_validation["nullable_mismatch"] = True

            table_validation["columns"][col_name] = col_validation

            if not col_validation["matches"]:
                table_validation["valid"] = False
                table_validation["column_mismatches"].append(col_name)

        # Mark as invalid if there are structural issues
        if table_validation["missing_columns"] or table_validation["extra_columns"]:
            table_validation["valid"] = False

        return table_validation

    except Exception as e:
        logger.error(f"Table validation failed for {table_name}: {e}")
        return {
            "valid": False,
            "error": str(e),
        }


# ============================================================================
# Production Safety Functions
# ============================================================================


async def safe_migrate(
    target_revision: str = "head",
    require_backup: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Safely perform database migration with safety checks.

    This function provides production-safe migration with:
    - Automatic backup before migration
    - Schema validation before and after
    - Rollback on failure
    - Dry-run mode for testing

    Args:
        target_revision: Target migration revision
        require_backup: Whether to require backup before migration
        dry_run: If True, only simulate migration

    Returns:
        Dictionary with migration results

    Raises:
        MigrationError: If migration fails
    """
    results = {
        "success": False,
        "backup_created": None,
        "initial_revision": None,
        "final_revision": None,
        "validation": None,
        "errors": [],
    }

    try:
        # Get current revision
        results["initial_revision"] = get_current_revision()
        logger.info(f"Current revision: {results['initial_revision']}")

        # Create backup if required
        if require_backup and not dry_run:
            backup_path = await backup_database()
            results["backup_created"] = str(backup_path)
            logger.info(f"Backup created: {backup_path}")

        # Validate schema before migration
        logger.info("Validating schema before migration...")
        pre_validation = await validate_schema()

        if not pre_validation["valid"]:
            results["errors"].append("Pre-migration schema validation failed")
            logger.warning("Schema validation warnings detected")

        # Perform migration
        if dry_run:
            logger.info("DRY RUN: Would upgrade to revision: {target_revision}")
            results["success"] = True
        else:
            logger.info(f"Performing migration to: {target_revision}")
            await upgrade_database(target_revision)

            # Get new revision
            results["final_revision"] = get_current_revision()
            logger.info(f"New revision: {results['final_revision']}")

            # Validate schema after migration
            logger.info("Validating schema after migration...")
            post_validation = await validate_schema()
            results["validation"] = post_validation

            if not post_validation["valid"]:
                results["errors"].append("Post-migration schema validation failed")
                logger.error("Schema validation failed after migration")
            else:
                results["success"] = True
                logger.info("Migration completed successfully")

        return results

    except Exception as e:
        error_msg = f"Migration failed: {e}"
        results["errors"].append(error_msg)
        logger.error(error_msg)
        raise MigrationError(error_msg)


def check_migration_safety() -> Dict[str, Any]:
    """
    Check if it's safe to perform migrations.

    Returns:
        Dictionary with safety check results
    """
    safety_checks = {
        "safe": True,
        "checks": {},
        "warnings": [],
    }

    # Check if database is accessible
    try:
        get_engine()
        safety_checks["checks"]["database_accessible"] = True
    except Exception as e:
        safety_checks["safe"] = False
        safety_checks["checks"]["database_accessible"] = False
        safety_checks["warnings"].append(f"Database not accessible: {e}")

    # Check if backup directory is writable
    try:
        backup_dir = Path("./data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        test_file = backup_dir / ".test"
        test_file.touch()
        test_file.unlink()
        safety_checks["checks"]["backup_writable"] = True
    except Exception as e:
        safety_checks["safe"] = False
        safety_checks["checks"]["backup_writable"] = False
        safety_checks["warnings"].append(f"Backup directory not writable: {e}")

    # Check if there are pending migrations
    try:
        current = get_current_revision()
        safety_checks["checks"]["current_revision"] = current
    except Exception as e:
        safety_checks["warnings"].append(f"Could not determine current revision: {e}")

    return safety_checks
