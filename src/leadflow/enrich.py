"""Merge the CRM event with the lead-owner record into the enriched schema (Section 4.2)."""

from __future__ import annotations

from typing import Any

from leadflow.models import LeadEvent

UNASSIGNED = "Unassigned"
FUNNEL_CUSTOM_FIELD_PREFIX = "custom.cf_am3U"  # the funnel custom field seen in both samples


def funnel_from_crm(event: LeadEvent) -> str:
    data = event.raw.get("event", {}).get("data", {})
    for key, value in data.items():
        if isinstance(key, str) and key.startswith(FUNNEL_CUSTOM_FIELD_PREFIX):
            return str(value or "")
    return ""


def build_enriched_record(
    event: LeadEvent,
    lookup_record: dict[str, Any] | None,
    *,
    lookup_status: str,
    lookup_attempts: int,
    received_at_utc: str,
    enriched_at_utc: str,
    source_path: str,
) -> dict[str, Any]:
    lookup = lookup_record or {}
    return {
        "lead_id": event.lead_id,
        "display_name": event.display_name,
        "date_created": event.date_created,
        "status_label": event.status_label,
        "lead_email": str(lookup.get("lead_email") or ""),
        "lead_owner": str(lookup.get("lead_owner") or UNASSIGNED),
        "funnel": str(lookup.get("funnel") or funnel_from_crm(event)),
        "funnel_from_crm": funnel_from_crm(event),
        "event_id": event.event_id,
        "received_at_utc": received_at_utc,
        "enriched_at_utc": enriched_at_utc,
        "lookup_status": lookup_status,
        "lookup_attempts": lookup_attempts,
        "source_path": source_path,
        "alert_sent_at_utc": None,
    }


def target_blob_name(lead_id: str, matched: bool) -> str:
    name = f"crm_lead_enriched_{lead_id}.json"
    return name if matched else f"unmatched/{name}"
