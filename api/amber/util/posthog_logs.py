"""Dedicated OpenTelemetry export of purpose-written Amber operational logs."""

import logging
from typing import Any

from amber.util.config import Settings

posthog_log = logging.getLogger("amber.posthog_export")
posthog_log.setLevel(logging.INFO)
posthog_log.propagate = False

_logger_provider: Any | None = None
_log_handler: logging.Handler | None = None


def initialize_posthog_logs(settings: Settings) -> None:
    """Route only ``posthog_log`` records to PostHog through the OTLP HTTP exporter."""
    global _logger_provider, _log_handler

    if _logger_provider is not None or not settings.posthog_api_key or not settings.posthog_host:
        return

    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    logger_provider = LoggerProvider()
    set_logger_provider(logger_provider)
    exporter = OTLPLogExporter(
        endpoint=f"{settings.posthog_host.rstrip('/')}/i/v1/logs",
        headers={"Authorization": f"Bearer {settings.posthog_api_key}"},
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    _log_handler = LoggingHandler(logger_provider=logger_provider)
    posthog_log.addHandler(_log_handler)
    _logger_provider = logger_provider
    posthog_log.info(
        "PostHog OTLP log export configured",
        extra={"event": "posthog_log_export_configured", "exporter": "otlp_http"},
    )


def shutdown_posthog_logs() -> None:
    """Flush and stop the dedicated exporter without changing application logging."""
    global _logger_provider, _log_handler

    if _logger_provider is None:
        return

    _logger_provider.force_flush()
    _logger_provider.shutdown()
    if _log_handler is not None:
        posthog_log.removeHandler(_log_handler)
        _log_handler.close()
    _logger_provider = None
    _log_handler = None
