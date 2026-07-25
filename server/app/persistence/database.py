from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from server.app.core.config import Settings
from server.app.persistence.models import Base, SchemaMigration


SCHEMA_VERSIONS = ("0001_phase_c", "0002_governance", "0003_runtime_controls")
SCHEMA_VERSION = SCHEMA_VERSIONS[-1]


class Database:
    def __init__(self, url: str, *, pool_size: int = 10, echo: bool = False) -> None:
        parsed = make_url(url)
        kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True, "echo": echo}
        if parsed.get_backend_name() == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = pool_size
        self.engine: Engine = create_engine(url, **kwargs)
        if parsed.get_backend_name() == "sqlite":
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(settings.database_url, pool_size=settings.database_pool_size)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    def migrate(self) -> None:
        """Apply the additive Phase C schema.

        Production deploys invoke this explicitly as a migration job. API and
        worker startup only call ``check_schema``.
        """

        Base.metadata.create_all(self.engine)
        self._migrate_runtime_controls()
        with self.transaction() as session:
            for version in SCHEMA_VERSIONS:
                if session.get(SchemaMigration, version) is None:
                    session.add(SchemaMigration(version=version))

    def _migrate_runtime_controls(self) -> None:
        """Add retry-cycle columns to databases created before schema 0003.

        ``create_all`` deliberately does not mutate existing tables, so the
        controlled migration job performs these two additive, backwards-safe
        changes explicitly. Defaults make all historical runs cycle zero.
        """

        columns = {item["name"] for item in inspect(self.engine).get_columns("job_stage_runs")}
        statements: list[str] = []
        if "retry_cycle" not in columns:
            statements.append(
                "ALTER TABLE job_stage_runs ADD COLUMN retry_cycle INTEGER NOT NULL DEFAULT 0"
            )
        if "cycle_attempt" not in columns:
            statements.append(
                "ALTER TABLE job_stage_runs ADD COLUMN cycle_attempt INTEGER NOT NULL DEFAULT 1"
            )
        if statements:
            with self.engine.begin() as connection:
                for statement in statements:
                    connection.execute(text(statement))

    def check_schema(self) -> str:
        with self.engine.connect() as connection:
            result = connection.execute(
                text("SELECT version FROM schema_migrations WHERE version = :version"),
                {"version": SCHEMA_VERSION},
            ).scalar_one_or_none()
        if result != SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {SCHEMA_VERSION} is not installed; run the controlled migration job"
            )
        return result

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
