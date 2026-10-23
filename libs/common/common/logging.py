import logging
import sys

import structlog


def setup_logging(service: str, level: str = "INFO", json: bool = True) -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=lvl, format="%(message)s")
    renderer = structlog.processors.JSONRenderer(ensure_ascii=False) if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
