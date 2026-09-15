from logging.handlers import QueueListener
import os
import copy
import logging
from typing import Any, Dict, Optional
import fnmatch
import logging.config


LoggingConfigDict = Dict[str, Any]

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(processName)s:%(process)d] %(name)s: %(message)s"

class ExcludePatternsFilter(logging.Filter):
    def __init__(self, exclude_patterns: list[str], **kwargs):
        super().__init__(**kwargs)
        self.exclude_patterns = exclude_patterns

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(
            fnmatch.fnmatch(record.name, pattern) for pattern in self.exclude_patterns
        ) and super().filter(record)


class AutoStartQueueListener(QueueListener):
    def __init__(self, queue, *handlers, respect_handler_level=False):
        super().__init__(queue, *handlers, respect_handler_level=respect_handler_level)
        self.start()


def setup_file_logger(
    base_log_dir: str,
    logger_name: str,
    log_filename: Optional[str] = None,
    level: int = logging.INFO,
    file_mode: str = "a",
    formatter: Optional[logging.Formatter] = None,
) -> logging.Logger:
    """
    Create and configure a logger with a FileHandler.

    Args:
        base_log_dir: Directory where log files will be stored.
        logger_name: Name of the logger to create/get.
        log_filename: Optional filename for the log file.
            If None, defaults to `<logger_name>.log`.
        level: Logger and handler level. Defaults to INFO.
        file_mode: File open mode for the handler (default 'a').
        formatter: Optional logging.Formatter for the handler.
            If None, uses a default formatter.

    Returns:
        The configured Logger instance.
    """
    os.makedirs(base_log_dir, exist_ok=True)

    if log_filename is None:
        log_filename = f"{logger_name}.log"

    log_file_path = os.path.join(base_log_dir, log_filename)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    _add_file_handler(
        logger=logger,
        log_file_path=log_file_path,
        level=level,
        mode=file_mode,
        formatter=formatter,
    )

    return logger


def _init_child_logging(config: dict | None):
    if config is not None:
        logging.config.dictConfig(config)


def _add_file_handler(
    logger: logging.Logger,
    log_file_path: str,
    level: int = logging.INFO,
    mode: str = "a",
    formatter: logging.Formatter | None = None,
):
    """
    Add a FileHandler to an existing logger instance.

    Useful for dynamically adding file handlers at runtime, such as when you
    need log files with names based on runtime parameters (e.g., port numbers,
    process IDs, timestamps).

    Args:
        logger: The logger instance to add the handler to.
        log_file_path: Path to the log file. Parent directory will be created
            if it doesn't exist.
        level: Logging level for this handler. Defaults to INFO.
        mode: File open mode ('a' for append, 'w' for overwrite). Defaults to 'a'.
        formatter: Optional custom formatter. If None, uses the library's
            default format.

    Returns:
        The created FileHandler instance (can be used to remove it later).
    """
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(
            handler, "baseFilename", None
        ) == os.path.abspath(log_file_path):
            return handler

    file_handler = logging.FileHandler(log_file_path, mode=mode, encoding="utf-8")
    file_handler.setLevel(level)
    if formatter is None:
        formatter = logging.Formatter(
            DEFAULT_LOG_FORMAT
        )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return file_handler


def _get_logging_config(log_dir: str = "logs") -> LoggingConfigDict:
    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "exclude_patterns_filter": {
                "()": "automa_ai.common.setup_logging.ExcludePatternsFilter",
                "name": "automa_ai",
                "exclude_patterns": [],
            },
        },
        "formatters": {
            "default": {"format": DEFAULT_LOG_FORMAT}
        },
        "handlers": {
            "catch_all_file": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "level": "INFO",
                "filename": f"{log_dir}/automa_ai.log",
                "filters": ["exclude_patterns_filter"],
            },
            "queue_listener": {
                "class": "logging.handlers.QueueHandler",
                "listener": "automa_ai.common.setup_logging.AutoStartQueueListener",
                "queue": {
                    "()": "multiprocessing.Queue"
                },
                "level": "INFO",
                "handlers": [
                    "catch_all_file",
                ],
            },
        },
        "loggers": {
            "automa_ai": {
                "handlers": ["catch_all_file"],
                "level": "INFO",
                "propagate": False,
            },
            # Silence multiprocessing's internal logger to avoid QueueHandler recursion
            # from using a multiprocessing.Queue for logging.
            "multiprocessing": {
                "level": "WARNING",
                "handlers": [],
                "propagate": False,
            },
        },
    }

    return LOGGING_CONFIG


def _deep_merge_dicts(
    d1: LoggingConfigDict, d2: LoggingConfigDict
) -> LoggingConfigDict:
    """
    Merge d2 into d1 without overwriting existing keys in d1
    """
    for key, value in d2.items():
        if key in d1:
            if isinstance(d1[key], dict) and isinstance(value, dict):
                _deep_merge_dicts(d1[key], value)
            elif isinstance(d1[key], list) and isinstance(value, list):
                # Avoid duplicates
                for item in value:
                    if item not in d1[key]:
                        d1[key].append(item)
            else:
                # Skip overwriting existing key to respect user's config
                pass
        else:
            d1[key] = copy.deepcopy(value)
    return d1


def build_logging_config(
    log_dir: str = "logs",
    existing_config: Optional[LoggingConfigDict] = None,
) -> LoggingConfigDict:
    """
    Build a logging configuration dictionary for the `automa_ai` library.

    This function:
    - Constructs a logging config that defines filters, formatters, handlers,
      and loggers under the `automa_ai.*` namespace.
    - Optionally merges this configuration into an existing logging config
      dictionary without overwriting existing keys or user-defined settings.
    - Ensures the log directory exists.

    It does NOT call `logging.config.dictConfig`; the caller is responsible for
    applying the returned configuration.

    Args:
        log_dir (str): Directory where log files used by `automa_ai` will be
            created. Defaults to "logs".
        existing_config (dict | None): An optional existing logging
            configuration dictionary to merge into. If None, only the library's
            configuration is returned.

    Returns:
        dict: A logging configuration dictionary suitable for passing to
              `logging.config.dictConfig`.
    """
    os.makedirs(log_dir, exist_ok=True)
    config = _get_logging_config(log_dir=log_dir)

    if existing_config is None:
        return config

    return _deep_merge_dicts(copy.deepcopy(existing_config), config)


def setup_logging(
    log_dir: str = "logs",
    existing_config: Optional[LoggingConfigDict] = None,
) -> None:
    """
    Convenience helper for applying the `automa_ai` logging configuration.

    This is a thin wrapper around `build_logging_config` that also calls
    `logging.config.dictConfig`. It may be convenient for simple scripts,
    but larger applications may prefer to call `build_logging_config` and
    apply the returned dict themselves.

    Args:
        log_dir: Directory where log files used by `automa_ai` will be
            created. Defaults to "logs".
        existing_config: An optional existing logging configuration
            dictionary to merge into before applying.

    Returns:
        dict: A logging configuration dictionary suitable for passing to
              `logging.config.dictConfig`.
    """
    config = build_logging_config(log_dir=log_dir, existing_config=existing_config)
    logging.config.dictConfig(config)
    return config
