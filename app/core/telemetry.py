"""Opt-in Azure telemetry. Install the azure extra before enabling."""

from app.core.config import Settings


def configure_telemetry(settings: Settings) -> None:
    if not settings.applicationinsights_connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:
        raise RuntimeError(
            "Install .[azure] before configuring Application Insights"
        ) from exc
    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string
    )
