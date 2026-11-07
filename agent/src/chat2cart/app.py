from contextlib import closing

import structlog

from chat2cart.config import load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.logging import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    with closing(connect(settings.db_path)) as conn:
        version = migrate(conn)
    structlog.get_logger().info("database_ready", schema_version=version)
