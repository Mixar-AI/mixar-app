# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Centralized logging configuration for Mixar Texture Painting.

This module provides a unified logging setup that can be used across
all Mixar modules to replace print statements with proper logging.

Log level is read from config/mixar.json ("log_level" key).
Valid values: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL".
Default: "INFO" if not specified or config unavailable.
"""

import json
import logging
import logging.handlers
import os
import sys
import time


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    # Status symbols
    SYMBOLS = {
        'DEBUG': '◆',
        'INFO': '✓',
        'WARNING': '⚠',
        'ERROR': '✗',
        'CRITICAL': '✗✗',
    }

    def format(self, record):
        """Format the log record with colors and symbols."""
        # Add color to levelname
        levelname = record.levelname
        if levelname in self.COLORS:
            color = self.COLORS[levelname]
            symbol = self.SYMBOLS[levelname]
            record.levelname = f"{color}[{levelname}]{self.RESET}"
            record.symbol = f"{color}{symbol}{self.RESET}"
        else:
            record.symbol = ''

        return super().format(record)


# Global logger registry to avoid duplicate handlers
_loggers = {}
# Per-logger lowest level written to the log file (see get_logger).
_file_floors = {}

# ---------------------------------------------------------------------------
# Client log file
# ---------------------------------------------------------------------------
#
# The console is hidden on Windows and held at ERROR in Prod, so without a file
# a user's report leaves no client-side record. Every Mixar logger also writes
# to ONE rotating file under ``~/.mixar/logs/`` with UTC timestamps: WARNING
# and above from every module, plus the ``[SCENES]`` ledger at INFO
# (``common/scenes_log.py`` opts in with ``file_floor=logging.INFO``). The
# console keeps its configured level, so nothing new is printed. Every line is
# redacted on write (``log_redact``). The file stays on the machine until the
# user sends it (Help > Report a Bug or Save Support Bundle).
#
# A background process (the headless sandbox child) writes its own file: two
# processes rotating one file fails on Windows, where an open file cannot be
# renamed. ``MIXAR_CLIENT_LOG_DIR`` overrides the folder; ``0`` / ``off``
# disables file logging (the test suite does).

LOG_FILENAME = "mixar-client.log"
BACKGROUND_LOG_FILENAME = "mixar-sandbox.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
#: The level every logger lets through to the file, whatever the console level.
FILE_FLOOR = logging.WARNING

_file_handler = None
_file_handler_failed = False


class _UtcFormatter(logging.Formatter):
    """ISO-8601 UTC with milliseconds, so a client line and a backend line
    can share one timeline without knowing the machine's time zone. Output
    (tracebacks included) is redacted, so the file never holds a raw secret."""

    converter = time.gmtime

    def formatTime(self, record, datefmt=None):  # noqa: N802 - logging API
        base = time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
        return f"{base}.{int(record.msecs):03d}Z"

    def format(self, record):
        text = super().format(record)
        try:
            from .log_redact import redact_text
            return redact_text(text)
        except Exception:
            return text


def log_dir() -> str:
    """Folder of the client log file, or ``""`` when file logging is off."""
    override = os.environ.get("MIXAR_CLIENT_LOG_DIR")
    if override is not None:
        return "" if override.strip().lower() in ("", "0", "off") else override
    return os.path.join(os.path.expanduser("~"), ".mixar", "logs")


def _is_background() -> bool:
    try:
        import bpy
        return bpy.app.background is True
    except Exception:
        return False


def log_file_path() -> str:
    folder = log_dir()
    if not folder:
        return ""
    name = BACKGROUND_LOG_FILENAME if _is_background() else LOG_FILENAME
    return os.path.join(folder, name)


def get_file_handler():
    """The shared rotating file handler, created once; ``None`` when file
    logging is disabled or the folder cannot be written. Never raises."""
    global _file_handler, _file_handler_failed
    if _file_handler is not None or _file_handler_failed:
        return _file_handler
    path = log_file_path()
    if not path:
        _file_handler_failed = True
        return None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8", delay=True,
        )
        # Each logger's own level (its file floor) decides what reaches it.
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            _UtcFormatter(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _file_handler = handler
    except Exception:
        _file_handler_failed = True
        _file_handler = None
    return _file_handler


def reset_file_handler() -> None:
    """Detach and close the shared handler (tests, or a changed
    ``MIXAR_CLIENT_LOG_DIR``); the next ``get_logger`` re-creates it."""
    global _file_handler, _file_handler_failed
    if _file_handler is not None:
        for logger in _loggers.values():
            if _file_handler in logger.handlers:
                logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass
    _file_handler = None
    _file_handler_failed = False


# Cached log level from config (resolved lazily)
_config_log_level = None


def _get_config_log_level() -> int:
    """Read log_level from config/mixar.json.

    Reads the file directly (not via config.py) to avoid circular imports.
    Falls back to INFO if config is unavailable or malformed.

    In Prod environment, the log level is forced to ERROR regardless of
    the configured log_level to prevent sensitive information leaking.
    """
    global _config_log_level
    if _config_log_level is not None:
        return _config_log_level

    try:
        import bpy
        config_path = os.path.join(
            bpy.utils.resource_path('LOCAL'), 'config', 'mixar.json'
        )
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Force ERROR level in production to hide sensitive info
            environment = config.get('environment', 'Prod')
            if environment == 'Prod':
                _config_log_level = logging.ERROR
                return _config_log_level

            level_name = config.get('log_level', 'INFO').upper()
            _config_log_level = getattr(logging, level_name, logging.INFO)
            return _config_log_level
    except Exception:
        pass

    _config_log_level = logging.INFO
    return _config_log_level


def get_logger(name: str = None, level: int = None,
               file_floor: int = FILE_FLOOR) -> logging.Logger:
    """
    Get or create a logger with the specified name.

    Args:
        name: The name of the logger. If None, returns the root Mixar logger.
              For module loggers, use __name__ from the calling module.
        level: The CONSOLE logging level. If None, reads from
               config/mixar.json ("log_level" key), defaulting to INFO.
        file_floor: The lowest level this logger writes to the client log
               file (default WARNING). The ``[SCENES]`` ledger passes INFO.

    Returns:
        A configured logger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting operation...")
        >>> logger.debug("Processing item %s", item_name)
        >>> logger.error("Failed to process: %s", error)
    """
    if name is None:
        name = 'mixar'

    # Return existing logger if already configured
    if name in _loggers:
        return _loggers[name]

    if level is None:
        level = _get_config_log_level()

    # Create new logger
    logger = logging.getLogger(name)
    # The logger admits what either sink wants; the console handler below keeps
    # the configured level, so console output is unchanged.
    _file_floors[name] = file_floor
    logger.setLevel(min(level, file_floor))

    # Prevent propagation to avoid duplicate logs
    logger.propagate = False

    # Only add handlers if this logger doesn't have any
    if not logger.handlers:
        # Console handler with colored output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        # Use colored formatter
        formatter = ColoredFormatter(
            fmt='%(symbol)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    file_handler = get_file_handler()
    if file_handler is not None and file_handler not in logger.handlers:
        logger.addHandler(file_handler)

    # Register logger
    _loggers[name] = logger

    return logger


def set_log_level(level: int, logger_name: str = None):
    """
    Set the logging level for a specific logger or all Mixar loggers.

    Args:
        level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        logger_name: The name of the logger to configure. If None, updates all.
    """
    if logger_name:
        names = [logger_name] if logger_name in _loggers else []
    else:
        names = list(_loggers)
    for name in names:
        logger = _loggers[name]
        # The log file keeps each logger's own floor: a quieter console never
        # silences it, and a louder one is undone when the console goes quiet.
        logger.setLevel(min(level, _file_floors.get(name, FILE_FLOOR)))
        for handler in logger.handlers:
            if handler is not _file_handler:
                handler.setLevel(level)


# Default logger for backward compatibility
default_logger = get_logger('mixar')
