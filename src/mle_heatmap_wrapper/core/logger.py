"""Application logging helpers."""

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from .config import config


class CustomFormatter(logging.Formatter):
    """Console formatter with optional ANSI colors."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, datefmt: str, use_colors: bool = True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors and record.levelname in self.COLORS:
            original = record.levelname
            record.levelname = f"{self.COLORS[original]}{original}{self.RESET}"
            formatted = super().format(record)
            record.levelname = original
            return formatted
        return super().format(record)


class LoggerManager:
    """Singleton-like logger configuration manager."""

    _loggers = {}
    _initialized = False

    @classmethod
    def setup_logging(cls, log_name: str = "mle_heatmap") -> None:
        if cls._initialized:
            return

        log_file = config.paths.logs_dir / f"{log_name}_{datetime.now():%Y%m%d}.log"
        root_logger = logging.getLogger()
        root_logger.setLevel(
            getattr(logging, config.logging.level.upper(), logging.INFO)
        )
        root_logger.handlers.clear()

        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when=config.logging.file_rotation,
            backupCount=config.logging.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(config.logging.format, datefmt=config.logging.date_format)
        )
        root_logger.addHandler(file_handler)

        if config.logging.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(
                getattr(logging, config.logging.level.upper(), logging.INFO)
            )
            console_handler.setFormatter(
                CustomFormatter(
                    config.logging.format,
                    datefmt=config.logging.date_format,
                    use_colors=True,
                )
            )
            root_logger.addHandler(console_handler)

        cls._initialized = True
        logger = cls.get_logger("LoggerManager")
        logger.info("Logging initialized - Level: %s", config.logging.level)
        logger.info("Log file: %s", log_file)

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        if not cls._initialized:
            cls.setup_logging()
        if name not in cls._loggers:
            cls._loggers[name] = logging.getLogger(name)
        return cls._loggers[name]


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor."""

    return LoggerManager.get_logger(name)
