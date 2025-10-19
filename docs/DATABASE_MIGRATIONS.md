# Database Migration System

Comprehensive guide to database migration, backup, and schema management for the trading bot.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [CLI Tool Usage](#cli-tool-usage)
- [Programmatic API](#programmatic-api)
- [Migration Workflow](#migration-workflow)
- [Backup and Restore](#backup-and-restore)
- [Schema Validation](#schema-validation)
- [Production Safety](#production-safety)
- [Troubleshooting](#troubleshooting)

## Overview

The database migration system provides:

- **Alembic Integration**: Version-controlled schema migrations
- **Automatic Backups**: Safe migration with rollback capability
- **Schema Validation**: Verify database integrity
- **CLI Management**: Command-line tools for all operations
- **Production Safety**: Multi-layer safety checks and dry-run mode

### Architecture

```
alembic/                    # Migration scripts directory
├── versions/              # Migration version files
├── env.py                 # Alembic environment configuration
└── script.py.mako         # Migration template

src/database/
├── models.py              # SQLAlchemy ORM models
├── engine.py              # Database engine and session management
└── migrations.py          # Migration utilities and functions

scripts/
└── db_manager.py          # CLI management tool
```

## Quick Start

### 1. Install Dependencies

```bash
# Install Alembic (already in pyproject.toml)
pip install alembic>=1.13.0

# Or install all project dependencies
pip install -e .
```

### 2. Initialize Database

```bash
# Create tables without migrations
python scripts/db_manager.py init

# Or initialize with migrations
python scripts/db_manager.py init --migrate
```

### 3. Create Your First Migration

```bash
# Generate migration from model changes
python scripts/db_manager.py generate "initial schema"

# Apply migration
python scripts/db_manager.py migrate upgrade
```

### 4. Verify Setup

```bash
# Check current migration status
python scripts/db_manager.py migrate current

# Validate schema
python scripts/db_manager.py validate
```

## CLI Tool Usage

### Database Initialization

```bash
# Initialize database with tables
python scripts/db_manager.py init

# Initialize without creating tables
python scripts/db_manager.py init --no-tables

# Initialize and run migrations
python scripts/db_manager.py init --migrate

# Use custom database URL
python scripts/db_manager.py --database-url sqlite:///custom.db init
```

### Table Management

```bash
# Create all tables
python scripts/db_manager.py create-tables

# Drop all tables (with confirmation)
python scripts/db_manager.py drop-tables

# Force drop without confirmation
python scripts/db_manager.py drop-tables --force
```

### Migration Management

```bash
# Upgrade to latest version
python scripts/db_manager.py migrate upgrade

# Upgrade to specific version
python scripts/db_manager.py migrate upgrade abc123

# Downgrade to specific version
python scripts/db_manager.py migrate downgrade def456

# Check current version
python scripts/db_manager.py migrate current

# View migration history
python scripts/db_manager.py migrate history
```

### Generate Migrations

```bash
# Auto-generate migration from model changes
python scripts/db_manager.py generate "add user table"

# Generate empty migration (manual editing)
python scripts/db_manager.py generate "custom changes" --no-autogenerate
```

### Backup and Restore

```bash
# Create backup
python scripts/db_manager.py backup

# Create backup with custom name
python scripts/db_manager.py backup --name my_backup.db

# List available backups
python scripts/db_manager.py list-backups

# Restore from backup (with confirmation)
python scripts/db_manager.py restore ./data/backups/backup_20240101_120000.db

# Force restore without confirmation
python scripts/db_manager.py restore backup.db --force
```

### Schema Validation

```bash
# Validate current schema
python scripts/db_manager.py validate

# Validate with detailed output
python scripts/db_manager.py -v validate
```

### Production-Safe Migration

```bash
# Safe migration with automatic backup
python scripts/db_manager.py safe-migrate

# Dry-run mode (no changes)
python scripts/db_manager.py safe-migrate --dry-run

# Safe migrate without backup
python scripts/db_manager.py safe-migrate --no-backup

# Check migration safety
python scripts/db_manager.py safety-check
```

## Programmatic API

### Basic Usage

```python
from src.database.migrations import (
    init_database,
    create_all_tables,
    upgrade_database,
    backup_database,
    validate_schema,
    safe_migrate,
)

# Initialize database
await init_database(create_tables=True)

# Create backup
backup_path = await backup_database()
print(f"Backup created: {backup_path}")

# Validate schema
results = await validate_schema()
if results["valid"]:
    print("Schema is valid")

# Safe migration
results = await safe_migrate(
    target_revision="head",
    require_backup=True,
    dry_run=False,
)
```

### Advanced Usage

```python
from src.database.migrations import (
    generate_migration,
    get_current_revision,
    get_migration_history,
    restore_database,
    check_migration_safety,
)

# Generate migration
generate_migration("add indexes", autogenerate=True)

# Check current revision
current = get_current_revision()
print(f"Current revision: {current}")

# Get migration history
history = get_migration_history()
for item in history:
    print(item["description"])

# Check safety before migration
safety = check_migration_safety()
if safety["safe"]:
    await upgrade_database("head")
else:
    print("Not safe to migrate:", safety["warnings"])

# Restore from backup
backup_path = Path("./data/backups/backup_20240101.db")
await restore_database(backup_path, confirm=True)
```

## Migration Workflow

### Development Workflow

1. **Modify Models**: Update SQLAlchemy models in `src/database/models.py`

2. **Generate Migration**:
   ```bash
   python scripts/db_manager.py generate "add new column"
   ```

3. **Review Migration**: Check generated file in `alembic/versions/`

4. **Apply Migration**:
   ```bash
   python scripts/db_manager.py migrate upgrade
   ```

5. **Validate**:
   ```bash
   python scripts/db_manager.py validate
   ```

### Production Workflow

1. **Test in Staging**:
   ```bash
   # Dry run first
   python scripts/db_manager.py safe-migrate --dry-run

   # Apply if safe
   python scripts/db_manager.py safe-migrate
   ```

2. **Create Production Backup**:
   ```bash
   python scripts/db_manager.py backup --name prod_pre_migration.db
   ```

3. **Check Safety**:
   ```bash
   python scripts/db_manager.py safety-check
   ```

4. **Apply Migration**:
   ```bash
   python scripts/db_manager.py safe-migrate
   ```

5. **Verify**:
   ```bash
   python scripts/db_manager.py validate
   python scripts/db_manager.py migrate current
   ```

### Rollback Procedure

If migration fails or causes issues:

1. **Downgrade Migration**:
   ```bash
   python scripts/db_manager.py migrate downgrade <previous_revision>
   ```

2. **Or Restore from Backup**:
   ```bash
   python scripts/db_manager.py restore <backup_file> --force
   ```

## Backup and Restore

### Automatic Backups

Backups are automatically created:
- Before safe migrations (unless `--no-backup` is used)
- Before database restoration (safety backup)

### Manual Backups

```bash
# Create timestamped backup
python scripts/db_manager.py backup

# Create named backup
python scripts/db_manager.py backup --name before_major_change.db
```

### Backup Location

Default: `./data/backups/`

Format: `backup_YYYYMMDD_HHMMSS.db`

### Restore Process

```bash
# List available backups
python scripts/db_manager.py list-backups

# Restore specific backup
python scripts/db_manager.py restore ./data/backups/backup_20240101_120000.db
```

**Safety Features**:
- Creates safety backup before restore
- Requires explicit confirmation
- Validates backup file exists

## Schema Validation

### What is Validated

- **Table Existence**: All expected tables present
- **Column Structure**: Correct columns in each table
- **Data Types**: Column types match models
- **Constraints**: NOT NULL and other constraints
- **Indexes**: Required indexes exist

### Validation Levels

```bash
# Basic validation
python scripts/db_manager.py validate

# Detailed validation
python scripts/db_manager.py -v validate
```

### Programmatic Validation

```python
from src.database.migrations import validate_schema

results = await validate_schema()

print(f"Valid: {results['valid']}")
print(f"Missing tables: {results['missing_tables']}")
print(f"Extra tables: {results['extra_tables']}")

for table_name, table_info in results['tables'].items():
    if not table_info['valid']:
        print(f"Issues in {table_name}:")
        print(f"  Missing columns: {table_info['missing_columns']}")
        print(f"  Extra columns: {table_info['extra_columns']}")
```

## Production Safety

### Safety Mechanisms

1. **Pre-Migration Backup**: Automatic backup before changes
2. **Schema Validation**: Before and after migration
3. **Dry-Run Mode**: Test migrations without applying
4. **Safety Checks**: Verify database accessibility and backup capability
5. **Rollback Support**: Easy reversion via downgrade or restore

### Safe Migration Features

```bash
# Full safety features
python scripts/db_manager.py safe-migrate

# Test migration without changes
python scripts/db_manager.py safe-migrate --dry-run

# Skip backup (not recommended)
python scripts/db_manager.py safe-migrate --no-backup
```

### Safety Check Results

```bash
python scripts/db_manager.py safety-check
```

Checks:
- Database accessibility
- Backup directory writable
- Current revision trackable
- Migration system functional

## Troubleshooting

### Common Issues

#### Migration Fails with "target database is not up to date"

**Solution**: Check current revision and upgrade incrementally

```bash
python scripts/db_manager.py migrate current
python scripts/db_manager.py migrate history
python scripts/db_manager.py migrate upgrade
```

#### "Database file not found" during backup

**Solution**: Initialize database first

```bash
python scripts/db_manager.py init
python scripts/db_manager.py backup
```

#### Schema validation fails after migration

**Diagnosis**:
```bash
python scripts/db_manager.py -v validate
```

**Solution**: Check migration file for errors or restore from backup

#### Cannot downgrade migration

**Solution**: Check if downgrade is implemented in migration file

```python
# In migration file, ensure downgrade() is implemented
def downgrade() -> None:
    """Revert migration changes."""
    op.drop_table('new_table')  # Example
```

### Recovery Procedures

#### Complete Database Reset

```bash
# Backup current state (if needed)
python scripts/db_manager.py backup --name pre_reset.db

# Drop all tables
python scripts/db_manager.py drop-tables --force

# Reinitialize
python scripts/db_manager.py init --migrate
```

#### Restore from Backup

```bash
# List backups
python scripts/db_manager.py list-backups

# Restore
python scripts/db_manager.py restore ./data/backups/<backup_file> --force
```

### Debug Mode

Enable verbose output for troubleshooting:

```bash
python scripts/db_manager.py -v <command>
```

Or set logging level in code:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Environment Variables

Configure database via environment variables:

```bash
# Full database URL
export DATABASE_URL="sqlite:///./data/tradingbot.db"

# Or just database path (for SQLite)
export DB_PATH="./data/tradingbot.db"

# PostgreSQL example
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/tradingbot"
```

## Best Practices

### Development

1. **Always test migrations** on a copy of production data
2. **Generate migrations** incrementally for each logical change
3. **Review generated migrations** before applying
4. **Write descriptive migration messages**
5. **Test both upgrade and downgrade** paths

### Production

1. **Always backup** before migrations
2. **Use safe-migrate** instead of direct upgrade
3. **Test in staging** environment first
4. **Schedule migrations** during low-traffic periods
5. **Monitor application** after migration
6. **Keep recent backups** accessible

### Code

1. **Never modify applied migrations** (create new one instead)
2. **Keep models in sync** with migrations
3. **Document complex migrations** in comments
4. **Test migrations** with realistic data volumes
5. **Implement rollback** in all migrations

## Additional Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Project Database Models](../src/database/models.py)
- [Migration Utilities](../src/database/migrations.py)
