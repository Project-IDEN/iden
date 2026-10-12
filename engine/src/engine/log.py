import logging
import sys

import structlog

from engine.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def configure_logging() -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.engine_env == "prod"
        else structlog.dev.ConsoleRenderer()
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.engine_log_level.upper())
