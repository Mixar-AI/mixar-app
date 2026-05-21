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
import os
import sys


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


def get_logger(name: str = None, level: int = None) -> logging.Logger:
    """
    Get or create a logger with the specified name.

    Args:
        name: The name of the logger. If None, returns the root Mixar logger.
              For module loggers, use __name__ from the calling module.
        level: The logging level. If None, reads from config/mixar.json
               ("log_level" key), defaulting to INFO.

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
    logger.setLevel(level)

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
        if logger_name in _loggers:
            _loggers[logger_name].setLevel(level)
            for handler in _loggers[logger_name].handlers:
                handler.setLevel(level)
    else:
        # Update all registered loggers
        for logger in _loggers.values():
            logger.setLevel(level)
            for handler in logger.handlers:
                handler.setLevel(level)


# Default logger for backward compatibility
default_logger = get_logger('mixar')
