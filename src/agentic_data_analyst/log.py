"""Logging setup: everything goes through loguru, to the console and to a rolling file."""

import logging
import sys
from pathlib import Path
from types import FrameType

from loguru import logger

from agentic_data_analyst.settings import LOG_LEVEL


class _InterceptHandler(logging.Handler):
    """Forwards standard-library log records (Chainlit, httpx, uvicorn) to loguru; recipe from the loguru docs."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Find the caller outside the logging module, so loguru reports the real origin.
        frame: FrameType | None = logging.currentframe()
        depth = 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(log_file: Path) -> None:
    # Replace loguru's default stderr sink, so the console uses LOG_LEVEL too.
    logger.remove()
    logger.add(sys.stderr, level=LOG_LEVEL)
    # The file keeps errors after the terminal is closed; rotation and retention bound disk use.
    logger.add(log_file, level=LOG_LEVEL, rotation="10 MB", retention=5, encoding="utf-8")
    # Level 0 forwards every record; the loguru sinks filter by LOG_LEVEL.
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
