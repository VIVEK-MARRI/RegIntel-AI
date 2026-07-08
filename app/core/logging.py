import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configures structured logging for production."""
    log_format = "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] - %(message)s"

    # Clear existing handlers on the root logger
    logging.root.handlers = []

    logging.basicConfig(
        level=level, format=log_format, handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Restrict noise from dependency loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
