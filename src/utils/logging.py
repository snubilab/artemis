"""
Structured Logging Utility

Phase 8 P1: Centralized logging configuration
- Dev: Human-readable colored console
- Prod: JSON lines for log aggregation (Datadog/CloudWatch)

Usage:
    from src.utils.logging import get_logger
    
    logger = get_logger(__name__)
    logger.info("Processing query", query=query, top_k=10)
"""
import logging
import sys
from typing import Optional

# Try structlog, fallback to standard logging
try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False
    print("[Warning] structlog not installed. Using standard logging.")


def configure_logging(debug: bool = True, json_logs: bool = False) -> None:
    """
    Configure logging for the application.
    
    Args:
        debug: If True, use colorful dev-friendly output
        json_logs: If True, output JSON lines (for production)
    """
    if not HAS_STRUCTLOG:
        # Fallback to standard logging
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format="[%(name)s] %(levelname)s: %(message)s"
        )
        return
    
    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_logs:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ]
    else:
        # Development: Colored console
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    factory = structlog.PrintLoggerFactory()
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        context_class=dict,
        logger_factory=factory,
        cache_logger_on_first_use=True,
    )
    
    # Also configure standard library logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if debug else logging.INFO,
    )


class StructlogCompatibleLogger:
    """
    Wrapper for standard logging that accepts keyword arguments.
    Converts kwargs to string format for compatibility.
    """
    
    def __init__(self, logger: logging.Logger):
        self._logger = logger
    
    def _format_msg(self, event: str, **kwargs) -> str:
        if kwargs:
            extras = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{event} | {extras}"
        return event
    
    def debug(self, event: str, **kwargs):
        self._logger.debug(self._format_msg(event, **kwargs))
    
    def info(self, event: str, **kwargs):
        self._logger.info(self._format_msg(event, **kwargs))
    
    def warning(self, event: str, **kwargs):
        self._logger.warning(self._format_msg(event, **kwargs))
    
    def error(self, event: str, **kwargs):
        self._logger.error(self._format_msg(event, **kwargs))
    
    def exception(self, event: str, **kwargs):
        self._logger.exception(self._format_msg(event, **kwargs))


def get_logger(name: Optional[str] = None):
    """
    Get a logger instance.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger (structlog or compatible wrapper)
    """
    if HAS_STRUCTLOG:
        return structlog.get_logger(name or "artemis")
    else:
        return StructlogCompatibleLogger(logging.getLogger(name or "artemis"))


# Auto-configure on import (can be overridden)
_configured = False


def _auto_configure():
    """Auto-configure logging on first logger access."""
    global _configured
    if not _configured:
        try:
            from src.settings import settings
            debug = getattr(settings, 'DEBUG', True)
            json_logs = getattr(settings, 'JSON_LOGS', False)
        except Exception as e:
            print(
                "[Warning] Logging auto-config failed; using defaults. "
                f"error_type={type(e).__name__} error={e}",
                file=sys.stderr,
            )
            debug = True
            json_logs = False
        
        configure_logging(debug=debug, json_logs=json_logs)
        _configured = True


# Configure on import
_auto_configure()
