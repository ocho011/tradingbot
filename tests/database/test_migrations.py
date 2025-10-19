"""
Tests for database migration system.

This module tests:
- Database initialization and table creation
- Migration execution (upgrade/downgrade)
- Backup and restore functionality
- Schema validation
- Production safety mechanisms
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from sqlalchemy import text

from src.database.migrations import (
    init_database,
    create_all_tables,
    drop_all_tables,
    initial_data_setup,
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
    MigrationError,
    BackupError,
    ValidationError,
)
from src.database.engine import init_db, close_db, get_session
from src.database.models import Base, Trade, Position, Statistics, BacktestResult


@pytest.fixture
async def test_db():
    """Fixture to provide a test database."""
    # Use temporary directory for test database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        # Initialize database
        await init_db(database_url=db_url, echo=False, create_tables=False)

        yield db_url

        # Cleanup
        await close_db()
        if db_path.exists():
            db_path.unlink()


@pytest.fixture
def temp_backup_dir():
    """Fixture to provide temporary backup directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Patch the backup directory
        with patch("src.database.migrations.get_backup_path") as mock_get_path:
            def get_test_backup_path(backup_name=None):
                if backup_name is None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_name = f"backup_{timestamp}.db"
                return backup_dir / backup_name

            mock_get_path.side_effect = get_test_backup_path
            yield backup_dir


# ============================================================================
# Initialization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_all_tables(test_db):
    """Test creating all database tables."""
    await create_all_tables()

    # Verify tables exist
    async with get_session() as session:
        # Check if we can query each table
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]

        assert "trades" in tables
        assert "positions" in tables
        assert "statistics" in tables
        assert "backtest_results" in tables


@pytest.mark.asyncio
async def test_drop_all_tables(test_db):
    """Test dropping all database tables."""
    # Create tables first
    await create_all_tables()

    # Drop tables
    await drop_all_tables()

    # Verify tables are gone
    async with get_session() as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]

        assert "trades" not in tables
        assert "positions" not in tables


@pytest.mark.asyncio
async def test_init_database(test_db):
    """Test full database initialization."""
    await init_database(database_url=test_db, create_tables=True, run_migrations=False)

    # Verify tables exist
    async with get_session() as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]

        assert len(tables) >= 4  # At least 4 main tables


@pytest.mark.asyncio
async def test_initial_data_setup(test_db):
    """Test initial data setup function."""
    await create_all_tables()

    async with get_session() as session:
        await initial_data_setup(session)
        # Verify session is still valid after setup
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


# ============================================================================
# Migration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_upgrade_database_error():
    """Test upgrade_database raises error when Alembic fails."""
    with patch("src.database.migrations.run_alembic_command") as mock_cmd:
        mock_cmd.side_effect = MigrationError("Test error")

        with pytest.raises(MigrationError, match="Failed to upgrade database"):
            await upgrade_database()


@pytest.mark.asyncio
async def test_downgrade_database_error():
    """Test downgrade_database raises error when Alembic fails."""
    with patch("src.database.migrations.run_alembic_command") as mock_cmd:
        mock_cmd.side_effect = MigrationError("Test error")

        with pytest.raises(MigrationError, match="Failed to downgrade database"):
            await downgrade_database("previous")


def test_generate_migration():
    """Test migration file generation."""
    with patch("src.database.migrations.run_alembic_command") as mock_cmd:
        mock_result = Mock()
        mock_result.stdout = "Generated migration file"
        mock_cmd.return_value = mock_result

        generate_migration("test migration", autogenerate=True)

        # Verify command was called correctly
        mock_cmd.assert_called_once()
        call_args = mock_cmd.call_args[0][0]
        assert "revision" in call_args
        assert "--autogenerate" in call_args
        assert "test migration" in call_args


def test_get_current_revision():
    """Test getting current database revision."""
    with patch("src.database.migrations.run_alembic_command") as mock_cmd:
        # Test with revision present
        mock_result = Mock()
        mock_result.stdout = "abc123 (head)"
        mock_cmd.return_value = mock_result

        revision = get_current_revision()
        assert revision == "abc123"

        # Test with no revision
        mock_result.stdout = "None"
        revision = get_current_revision()
        assert revision is None


def test_get_migration_history():
    """Test getting migration history."""
    with patch("src.database.migrations.run_alembic_command") as mock_cmd:
        mock_result = Mock()
        mock_result.stdout = """
        abc123 -> def456, test migration 1
        def456 -> ghi789, test migration 2
        """
        mock_cmd.return_value = mock_result

        history = get_migration_history()
        assert len(history) == 2
        assert all("description" in item for item in history)


# ============================================================================
# Backup and Restore Tests
# ============================================================================


@pytest.mark.asyncio
async def test_backup_database(test_db, temp_backup_dir):
    """Test database backup creation."""
    # Create tables to have some data
    await create_all_tables()

    # Create backup
    backup_path = await backup_database()

    # Verify backup exists
    assert backup_path.exists()
    assert backup_path.suffix == ".db"
    assert backup_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_backup_database_nonexistent_file():
    """Test backup fails when database file doesn't exist."""
    with patch("src.database.migrations.get_database_url") as mock_url:
        mock_url.return_value = "sqlite+aiosqlite:///nonexistent.db"

        with pytest.raises(BackupError, match="Database file not found"):
            await backup_database()


@pytest.mark.asyncio
async def test_restore_database_requires_confirmation(test_db, temp_backup_dir):
    """Test restore requires explicit confirmation."""
    await create_all_tables()
    backup_path = await backup_database()

    with pytest.raises(BackupError, match="requires explicit confirmation"):
        await restore_database(backup_path, confirm=False)


@pytest.mark.asyncio
async def test_restore_database_success(test_db, temp_backup_dir):
    """Test successful database restore."""
    await create_all_tables()

    # Create backup
    backup_path = await backup_database()

    # Modify database (drop tables)
    await drop_all_tables()

    # Restore from backup
    await restore_database(backup_path, confirm=True)

    # Verify tables are back
    async with get_session() as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]
        assert len(tables) >= 4


@pytest.mark.asyncio
async def test_restore_database_missing_backup():
    """Test restore fails when backup file doesn't exist."""
    fake_path = Path("/tmp/nonexistent_backup.db")

    with pytest.raises(BackupError, match="Backup file not found"):
        await restore_database(fake_path, confirm=True)


def test_list_backups(temp_backup_dir):
    """Test listing available backups."""
    # Create some test backup files
    backup_files = [
        temp_backup_dir / "backup_20240101_120000.db",
        temp_backup_dir / "backup_20240102_120000.db",
    ]

    for backup_file in backup_files:
        backup_file.touch()

    with patch("src.database.migrations.Path") as mock_path:
        mock_path.return_value = temp_backup_dir

        backups = list_backups()
        assert len(backups) >= 2
        assert all("name" in b and "path" in b and "size" in b for b in backups)


# ============================================================================
# Schema Validation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_validate_schema_success(test_db):
    """Test schema validation with correct schema."""
    await create_all_tables()

    validation = await validate_schema()

    assert validation["valid"] is True
    assert len(validation["missing_tables"]) == 0
    assert len(validation["errors"]) == 0


@pytest.mark.asyncio
async def test_validate_schema_missing_tables(test_db):
    """Test schema validation detects missing tables."""
    # Initialize engine but don't create tables
    validation = await validate_schema()

    assert validation["valid"] is False
    assert len(validation["missing_tables"]) > 0
    assert "trades" in validation["missing_tables"]


@pytest.mark.asyncio
async def test_validate_schema_extra_tables(test_db):
    """Test schema validation detects extra tables."""
    await create_all_tables()

    # Add an extra table
    async with get_session() as session:
        await session.execute(text("CREATE TABLE extra_table (id INTEGER PRIMARY KEY)"))
        await session.commit()

    validation = await validate_schema()

    assert "extra_table" in validation["extra_tables"]


# ============================================================================
# Production Safety Tests
# ============================================================================


@pytest.mark.asyncio
async def test_safe_migrate_dry_run(test_db):
    """Test safe migration in dry-run mode."""
    with patch("src.database.migrations.upgrade_database") as mock_upgrade:
        results = await safe_migrate(dry_run=True, require_backup=False)

        # Should not actually upgrade
        mock_upgrade.assert_not_called()
        assert results["success"] is True


@pytest.mark.asyncio
async def test_safe_migrate_creates_backup(test_db, temp_backup_dir):
    """Test safe migration creates backup."""
    await create_all_tables()

    with patch("src.database.migrations.upgrade_database") as mock_upgrade, \
         patch("src.database.migrations.validate_schema") as mock_validate:

        mock_validate.return_value = {"valid": True}

        results = await safe_migrate(require_backup=True)

        assert results["backup_created"] is not None


@pytest.mark.asyncio
async def test_safe_migrate_validates_schema(test_db):
    """Test safe migration performs schema validation."""
    with patch("src.database.migrations.upgrade_database") as mock_upgrade, \
         patch("src.database.migrations.validate_schema") as mock_validate, \
         patch("src.database.migrations.backup_database") as mock_backup:

        mock_validate.return_value = {"valid": True}
        mock_backup.return_value = Path("/tmp/backup.db")

        results = await safe_migrate()

        # Should validate schema
        assert mock_validate.call_count >= 1


def test_check_migration_safety(test_db):
    """Test migration safety checks."""
    safety = check_migration_safety()

    assert "safe" in safety
    assert "checks" in safety
    assert "warnings" in safety


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_tables_error_handling():
    """Test error handling when table creation fails."""
    with patch("src.database.migrations.get_engine") as mock_engine:
        mock_engine.side_effect = RuntimeError("Engine not initialized")

        with pytest.raises(MigrationError, match="Table creation failed"):
            await create_all_tables()


@pytest.mark.asyncio
async def test_validate_schema_error_handling():
    """Test error handling in schema validation."""
    with patch("src.database.migrations.get_engine") as mock_engine:
        mock_engine.side_effect = RuntimeError("Engine not initialized")

        with pytest.raises(ValidationError, match="Schema validation failed"):
            await validate_schema()


def test_backup_database_non_sqlite():
    """Test backup fails for non-SQLite databases."""
    with patch("src.database.migrations.get_database_url") as mock_url:
        mock_url.return_value = "postgresql://localhost/test"

        with pytest.raises(BackupError, match="only supported for SQLite"):
            import asyncio
            asyncio.run(backup_database())


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_migration_workflow(test_db, temp_backup_dir):
    """Test complete migration workflow."""
    # 1. Initialize database
    await init_database(database_url=test_db, create_tables=True)

    # 2. Validate schema
    validation = await validate_schema()
    assert validation["valid"] is True

    # 3. Create backup
    backup_path = await backup_database()
    assert backup_path.exists()

    # 4. List backups
    with patch("src.database.migrations.Path") as mock_path:
        mock_path.return_value = temp_backup_dir
        backups = list_backups()
        assert len(backups) > 0


@pytest.mark.asyncio
async def test_backup_restore_workflow(test_db, temp_backup_dir):
    """Test backup and restore workflow."""
    # Create and populate database
    await create_all_tables()

    async with get_session() as session:
        from src.database.models import Trade
        from src.core.constants import TimeFrame

        trade = Trade(
            symbol="BTCUSDT",
            strategy="test",
            timeframe=TimeFrame.M15,
            entry_time=datetime.now(),
            entry_price=50000,
            quantity=1.0,
            side="LONG",
        )
        session.add(trade)
        await session.commit()

    # Create backup
    backup_path = await backup_database()

    # Drop tables (simulate data loss)
    await drop_all_tables()

    # Restore from backup
    await restore_database(backup_path, confirm=True)

    # Verify data is restored
    async with get_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM trades"))
        count = result.scalar()
        assert count == 1
