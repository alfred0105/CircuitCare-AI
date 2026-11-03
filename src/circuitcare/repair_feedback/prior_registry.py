"""Human-approved, versioned prior lifecycle with explicit activation and rollback."""

from __future__ import annotations

import sqlite3
import math

from .case_repository import RepairCaseRepository
from .models import utc_now

MIN_OPERATIONAL_PRIOR_CASES = 5


def propose_prior(repository: RepairCaseRepository, proposal: dict) -> dict:
    if proposal.get("status") != "PROPOSAL_READY" or not proposal.get("prior_weights"):
        raise ValueError("Only a fully estimated proposal can be registered.")
    if proposal.get("contains_synthetic_records") is not False:
        raise ValueError("Prior proposal provenance must explicitly exclude synthetic records.")
    ids = proposal.get("training_case_ids", [])
    if proposal.get("minimum_case_count", 0) < MIN_OPERATIONAL_PRIOR_CASES:
        raise ValueError(f"Operational prior proposals require a minimum of {MIN_OPERATIONAL_PRIOR_CASES} distinct verified cases.")
    if len(ids) != len(set(ids)) or len(ids) != proposal.get("eligible_case_count") or not ids:
        raise ValueError("Prior proposal requires distinct case IDs matching its eligible case count.")
    if len(ids) < proposal.get("minimum_case_count", 1):
        raise ValueError("Prior proposal does not meet its configured minimum case count.")
    weights = proposal["prior_weights"]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-8:
        raise ValueError("Prior weights must be finite, strictly positive, and normalized.")
    model = {**proposal, "status": "PROPOSED"}
    try:
        repository.save_prior_model(model)
    except sqlite3.IntegrityError:
        existing = repository.get_prior_model(proposal["version"])
        if existing is None or existing.get("prior_weights") != proposal.get("prior_weights") or existing.get("training_case_ids") != proposal.get("training_case_ids"):
            raise ValueError("Prior version collision with different proposal contents.")
        repository.record_prior_event(version=proposal["version"], action="PROPOSAL_ALREADY_EXISTS", payload={})
        return existing
    repository.record_prior_event(version=proposal["version"], action="PROPOSED", payload={"eligible_case_count": proposal["eligible_case_count"]})
    return repository.get_prior_model(proposal["version"])


def approve_prior(repository: RepairCaseRepository, version: str, *, reviewer: str, note: str = "") -> dict:
    model = repository.get_prior_model(version)
    if not model or model.get("status") not in {"PROPOSED", "APPROVED"}:
        raise ValueError("Prior must exist as a proposal before approval.")
    model["approval"] = {"reviewer": reviewer, "note": note, "approved_at": utc_now(), "approved": True}
    model["status"] = "APPROVED"
    repository.update_prior_model(version, status="APPROVED")
    # Persist approval details in the version payload through an append-only event.
    repository.record_prior_event(version=version, action="APPROVED", payload=model["approval"])
    _replace_payload(repository, model)
    return model


def activate_prior(repository: RepairCaseRepository, version: str, *, reviewer: str) -> dict:
    model = repository.get_prior_model(version)
    if not model or model.get("status") != "APPROVED" or not model.get("approval", {}).get("approved"):
        raise ValueError("A human-approved prior is required before activation.")
    if model.get("contains_synthetic_records") is not False or not model.get("training_case_ids") or not model.get("prior_weights"):
        raise ValueError("Only a non-empty, real-repair prior proposal can be activated.")
    if len(set(model.get("training_case_ids", []))) < MIN_OPERATIONAL_PRIOR_CASES or model.get("eligible_case_count", 0) < MIN_OPERATIONAL_PRIOR_CASES:
        raise ValueError(f"Activation requires at least {MIN_OPERATIONAL_PRIOR_CASES} distinct verified real-repair cases.")
    for current in repository.list_prior_models(group_id=model["group_id"]):
        if current.get("status") == "ACTIVE" and current["version"] != version:
            repository.update_prior_model(current["version"], status="APPROVED")
            repository.record_prior_event(version=current["version"], action="DEACTIVATED_FOR_REPLACEMENT", payload={"replaced_by": version})
    activated = repository.update_prior_model(version, status="ACTIVE")
    repository.record_prior_event(version=version, action="ACTIVATED", payload={"reviewer": reviewer})
    return activated


def deactivate_prior(repository: RepairCaseRepository, version: str, *, reviewer: str) -> dict:
    model = repository.get_prior_model(version)
    if not model or model.get("status") != "ACTIVE":
        raise ValueError("Only an active prior can be deactivated.")
    updated = repository.update_prior_model(version, status="APPROVED")
    repository.record_prior_event(version=version, action="DEACTIVATED", payload={"reviewer": reviewer})
    return updated


def rollback_prior(repository: RepairCaseRepository, *, group_id: str, target_version: str, reviewer: str) -> dict:
    target = repository.get_prior_model(target_version)
    if not target or target.get("group_id") != group_id or not target.get("approval", {}).get("approved"):
        raise ValueError("Rollback target must be an approved prior for the same group.")
    for current in repository.list_prior_models(group_id=group_id):
        if current.get("status") == "ACTIVE":
            repository.update_prior_model(current["version"], status="APPROVED")
            repository.record_prior_event(version=current["version"], action="ROLLED_BACK", payload={"target_version": target_version, "reviewer": reviewer})
    restored = repository.update_prior_model(target_version, status="ACTIVE")
    repository.record_prior_event(version=target_version, action="ROLLBACK_ACTIVATED", payload={"reviewer": reviewer})
    return restored


def active_prior(repository: RepairCaseRepository, group_id: str) -> dict | None:
    return next((model for model in repository.list_prior_models(group_id=group_id) if model.get("status") == "ACTIVE"), None)


def _replace_payload(repository: RepairCaseRepository, model: dict) -> None:
    # A narrow repository update keeps the version immutable while appending review events.
    import json
    with repository._connect() as db:
        db.execute("UPDATE prior_models SET payload_json=? WHERE version=?",
                   (json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False), model["version"]))
