"""
Base Data Access Object (DAO) providing common CRUD operations.

This module provides a generic base class for all DAOs with type-safe
async CRUD operations, pagination support, and transaction management.
"""

from typing import TypeVar, Generic, Type, Optional, List, Dict, Any, Sequence
from datetime import datetime
import logging

from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from src.database.models import Base


logger = logging.getLogger(__name__)

# Generic type variable for SQLAlchemy models
ModelType = TypeVar('ModelType', bound=Base)


class BaseDAO(Generic[ModelType]):
    """
    Generic base DAO providing common CRUD operations.

    This class provides type-safe async database operations for any
    SQLAlchemy model that extends Base.

    Type Parameters:
        ModelType: SQLAlchemy model class

    Example:
        >>> class TradeDAO(BaseDAO[Trade]):
        ...     def __init__(self, session: AsyncSession):
        ...         super().__init__(Trade, session)
    """

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        """
        Initialize DAO with model class and database session.

        Args:
            model: SQLAlchemy model class
            session: Async database session
        """
        self.model = model
        self.session = session

    async def create(self, **kwargs) -> ModelType:
        """
        Create a new record.

        Args:
            **kwargs: Field values for the new record

        Returns:
            Created model instance

        Raises:
            SQLAlchemyError: If database operation fails

        Example:
            >>> trade = await trade_dao.create(
            ...     symbol='BTCUSDT',
            ...     strategy='MACD',
            ...     entry_price=50000.0
            ... )
        """
        try:
            instance = self.model(**kwargs)
            self.session.add(instance)
            await self.session.flush()
            await self.session.refresh(instance)
            logger.debug(f"Created {self.model.__name__} with id={instance.id}")
            return instance
        except SQLAlchemyError as e:
            logger.error(f"Error creating {self.model.__name__}: {e}")
            raise

    async def get_by_id(self, id: int) -> Optional[ModelType]:
        """
        Get a record by its primary key ID.

        Args:
            id: Primary key value

        Returns:
            Model instance or None if not found

        Example:
            >>> trade = await trade_dao.get_by_id(42)
        """
        try:
            result = await self.session.execute(
                select(self.model).where(self.model.id == id)
            )
            instance = result.scalar_one_or_none()
            if instance:
                logger.debug(f"Retrieved {self.model.__name__} with id={id}")
            return instance
        except SQLAlchemyError as e:
            logger.error(f"Error getting {self.model.__name__} by id={id}: {e}")
            raise

    async def get_all(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> List[ModelType]:
        """
        Get all records with optional pagination and ordering.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Column name to order by (prefix with '-' for descending)

        Returns:
            List of model instances

        Example:
            >>> trades = await trade_dao.get_all(limit=100, order_by='-entry_time')
        """
        try:
            query = select(self.model)

            # Apply ordering
            if order_by:
                if order_by.startswith('-'):
                    # Descending order
                    column = getattr(self.model, order_by[1:])
                    query = query.order_by(column.desc())
                else:
                    # Ascending order
                    column = getattr(self.model, order_by)
                    query = query.order_by(column)

            # Apply pagination
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            result = await self.session.execute(query)
            instances = result.scalars().all()
            logger.debug(f"Retrieved {len(instances)} {self.model.__name__} records")
            return list(instances)
        except SQLAlchemyError as e:
            logger.error(f"Error getting all {self.model.__name__}: {e}")
            raise

    async def get_by_filter(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> List[ModelType]:
        """
        Get records matching filter criteria.

        Args:
            filters: Dictionary of column names and values to filter by
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Column name to order by (prefix with '-' for descending)

        Returns:
            List of model instances matching filters

        Example:
            >>> trades = await trade_dao.get_by_filter(
            ...     {'strategy': 'MACD', 'status': 'OPEN'},
            ...     limit=50
            ... )
        """
        try:
            query = select(self.model)

            # Apply filters
            for column_name, value in filters.items():
                if hasattr(self.model, column_name):
                    column = getattr(self.model, column_name)
                    query = query.where(column == value)

            # Apply ordering
            if order_by:
                if order_by.startswith('-'):
                    column = getattr(self.model, order_by[1:])
                    query = query.order_by(column.desc())
                else:
                    column = getattr(self.model, order_by)
                    query = query.order_by(column)

            # Apply pagination
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            result = await self.session.execute(query)
            instances = result.scalars().all()
            logger.debug(
                f"Retrieved {len(instances)} {self.model.__name__} "
                f"records with filters: {filters}"
            )
            return list(instances)
        except SQLAlchemyError as e:
            logger.error(f"Error filtering {self.model.__name__}: {e}")
            raise

    async def update(self, id: int, **kwargs) -> Optional[ModelType]:
        """
        Update a record by ID.

        Args:
            id: Primary key value
            **kwargs: Field values to update

        Returns:
            Updated model instance or None if not found

        Example:
            >>> trade = await trade_dao.update(
            ...     42,
            ...     exit_price=55000.0,
            ...     status='CLOSED'
            ... )
        """
        try:
            instance = await self.get_by_id(id)
            if instance is None:
                logger.warning(f"{self.model.__name__} with id={id} not found for update")
                return None

            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)

            await self.session.flush()
            await self.session.refresh(instance)
            logger.debug(f"Updated {self.model.__name__} with id={id}")
            return instance
        except SQLAlchemyError as e:
            logger.error(f"Error updating {self.model.__name__} id={id}: {e}")
            raise

    async def delete(self, id: int) -> bool:
        """
        Delete a record by ID.

        Args:
            id: Primary key value

        Returns:
            True if deleted, False if not found

        Example:
            >>> deleted = await trade_dao.delete(42)
        """
        try:
            result = await self.session.execute(
                delete(self.model).where(self.model.id == id)
            )
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"Deleted {self.model.__name__} with id={id}")
            else:
                logger.warning(f"{self.model.__name__} with id={id} not found for deletion")
            return deleted
        except SQLAlchemyError as e:
            logger.error(f"Error deleting {self.model.__name__} id={id}: {e}")
            raise

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count records matching optional filters.

        Args:
            filters: Optional dictionary of column names and values to filter by

        Returns:
            Number of matching records

        Example:
            >>> count = await trade_dao.count({'strategy': 'MACD', 'status': 'OPEN'})
        """
        try:
            query = select(func.count()).select_from(self.model)

            if filters:
                for column_name, value in filters.items():
                    if hasattr(self.model, column_name):
                        column = getattr(self.model, column_name)
                        query = query.where(column == value)

            result = await self.session.execute(query)
            count = result.scalar()
            return count or 0
        except SQLAlchemyError as e:
            logger.error(f"Error counting {self.model.__name__}: {e}")
            raise

    async def exists(self, id: int) -> bool:
        """
        Check if a record exists by ID.

        Args:
            id: Primary key value

        Returns:
            True if record exists, False otherwise

        Example:
            >>> exists = await trade_dao.exists(42)
        """
        try:
            result = await self.session.execute(
                select(func.count()).select_from(self.model).where(self.model.id == id)
            )
            count = result.scalar()
            return count > 0
        except SQLAlchemyError as e:
            logger.error(f"Error checking existence of {self.model.__name__} id={id}: {e}")
            raise

    async def bulk_create(self, items: List[Dict[str, Any]]) -> List[ModelType]:
        """
        Create multiple records in bulk for better performance.

        Args:
            items: List of dictionaries containing field values

        Returns:
            List of created model instances

        Example:
            >>> trades = await trade_dao.bulk_create([
            ...     {'symbol': 'BTCUSDT', 'entry_price': 50000},
            ...     {'symbol': 'ETHUSDT', 'entry_price': 3000},
            ... ])
        """
        try:
            instances = [self.model(**item) for item in items]
            self.session.add_all(instances)
            await self.session.flush()

            # Refresh all instances to get generated IDs
            for instance in instances:
                await self.session.refresh(instance)

            logger.debug(f"Bulk created {len(instances)} {self.model.__name__} records")
            return instances
        except SQLAlchemyError as e:
            logger.error(f"Error bulk creating {self.model.__name__}: {e}")
            raise
