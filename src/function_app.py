"""Azure Functions entry point (Python v2 programming model).

fn_webhook_receiver   POST /api/crm            Close webhook -> source blob -> delay queue
fn_lead_enricher      Service Bus trigger      delay queue -> lookup -> target blob -> Slack
fn_health             GET  /api/health         liveness and configuration presence
fn_lead_owner_stub    GET  /api/lead-owner/..  test-only lookup source (LEAD_OWNER_STUB_ENABLED)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache

import azure.functions as func

from leadflow import logs
from leadflow.config import Settings
from leadflow.delay_queue import ServiceBusScheduler
from leadflow.enricher import handle_delay_message
from leadflow.lookup import HttpLeadOwnerLookup
from leadflow.models import DelayMessage
from leadflow.notify import SlackNotifier
from leadflow.receiver import handle_webhook
from leadflow.storage import AzureBlobStore

app = func.FunctionApp()
logger = logging.getLogger("leadflow.function_app")


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def _store() -> AzureBlobStore:
    return AzureBlobStore(_settings().storage_account_url)


@lru_cache(maxsize=1)
def _scheduler() -> ServiceBusScheduler:
    s = _settings()
    return ServiceBusScheduler(s.servicebus_fqdn, s.servicebus_queue)


@lru_cache(maxsize=1)
def _lookup() -> HttpLeadOwnerLookup:
    return HttpLeadOwnerLookup(_settings().lead_owner_base_url)


@lru_cache(maxsize=1)
def _notifier() -> SlackNotifier:
    return SlackNotifier(_settings().slack_webhook_url)


def _json_response(status_code: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status_code, mimetype="application/json")


# ----------------------------------------------------------------------------- receiver
@app.function_name("fn_webhook_receiver")
@app.route(route="crm", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def fn_webhook_receiver(req: func.HttpRequest) -> func.HttpResponse:
    """Receive a Close webhook, store it in the source container, schedule enrichment."""
    body = req.get_body()
    headers = {k: v for k, v in req.headers.items()}
    try:
        result = handle_webhook(body, headers, _settings(), _store(), _scheduler())
    except Exception as exc:  # noqa: BLE001 - any failure must surface as 500 so Close retries
        logs.error(logger, "receiver_failure", error=repr(exc))
        return _json_response(500, {"status": "error", "reason": "internal error"})
    return _json_response(result.status_code, result.body)


# ----------------------------------------------------------------------------- enricher
@app.function_name("fn_lead_enricher")
@app.service_bus_queue_trigger(
    arg_name="msg", queue_name="%SERVICEBUS_QUEUE%", connection="ServiceBusConnection"
)
def fn_lead_enricher(msg: func.ServiceBusMessage) -> None:
    """Consume a delay-queue message: look up the owner, write the target record, alert.

    Returning normally completes the message. Raising abandons it, so Service Bus redelivers
    it (up to the queue's max delivery count, then dead-letters it).
    """
    message = DelayMessage.from_json(msg.get_body().decode("utf-8"))
    logs.info(
        logger,
        "message_received",
        lead_id=message.lead_id,
        attempt=message.attempt,
        delivery_count=msg.delivery_count,
        message_id=msg.message_id,
    )
    result = handle_delay_message(
        message, _settings(), _store(), _lookup(), _notifier(), _scheduler()
    )
    logs.info(
        logger,
        "message_completed",
        lead_id=result.lead_id,
        action=result.action,
        attempt=result.attempt,
        target_path=result.target_path,
        next_attempt_utc=result.next_attempt_utc,
    )


# ----------------------------------------------------------------------------- health
@app.function_name("fn_health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def fn_health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness check with no side effects; reports configuration presence only."""
    s = _settings()
    return _json_response(
        200,
        {
            "status": "ok",
            "storage_configured": bool(s.storage_account_url),
            "servicebus_configured": bool(s.servicebus_fqdn),
            "slack_configured": s.slack_webhook_url.startswith("https://hooks.slack.com/"),
            "lead_owner_base_url": s.lead_owner_base_url,
            "lead_owner_stub_enabled": s.lead_owner_stub_enabled,
            "verify_signature": s.verify_signature,
            "delay_minutes": s.delay_minutes,
            "retry_interval_minutes": s.retry_interval_minutes,
            "max_lookup_attempts": s.max_lookup_attempts,
        },
    )


# ----------------------------------------------------------------------------- test stub
@app.function_name("fn_lead_owner_stub")
@app.route(route="lead-owner/{lead_id}.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def fn_lead_owner_stub(req: func.HttpRequest) -> func.HttpResponse:
    """Serve a synthetic lead-owner record for test leads (decision 16).

    Active only when LEAD_OWNER_STUB_ENABLED=true and only for lead ids beginning with
    lead_test; everything else is 404, matching the real bucket's behavior for a missing file.
    Used by pointing LEAD_OWNER_BASE_URL at https://<host>/api/lead-owner during the Phase 3
    smoke test, so the found path can be exercised before the CRM team sends real leads.
    """
    lead_id = req.route_params.get("lead_id", "")
    if not _settings().lead_owner_stub_enabled or not lead_id.startswith("lead_test"):
        return _json_response(404, {"error": "not found"})
    record = {
        "lead_id": lead_id,
        "display_name": f"Test Lead {lead_id[9:15]}",
        "lead_email": f"{lead_id[9:21]}@example.com",
        "lead_owner": "Stub Owner",
        "funnel": "STUB Direct VSL",
        "status_label": "Potential",
        "date_created": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    return _json_response(200, record)
