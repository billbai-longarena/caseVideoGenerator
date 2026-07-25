from __future__ import annotations

from server.app.core.config import load_settings
from server.app.persistence.database import Database, SCHEMA_VERSION


def main() -> None:
    settings = load_settings()
    database = Database.from_settings(settings)
    database.migrate()
    database.check_schema()
    print(f"applied database schema {SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
