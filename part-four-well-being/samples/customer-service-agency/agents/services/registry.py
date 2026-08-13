"""Unified Registry client — all skill fetch/publish/poll logic in one place."""

import time

from botocore.exceptions import ClientError


def fetch_skill(registry_client, registry_id: str, skill_name: str) -> str | None:
    """Fetch a skill's markdown content from the Registry. Returns None if not found."""
    records = registry_client.list_registry_records(
        registryId=registry_id
    ).get("registryRecords", [])
    record = next((r for r in records if r["name"] == skill_name), None)
    if not record:
        return None
    detail = registry_client.get_registry_record(
        registryId=registry_id, recordId=record["recordId"],
    )
    return (
        detail.get("descriptors", {})
        .get("agentSkillsDefinition", {})
        .get("additionalData", {})
        .get("skillMd", {})
        .get("data", "")
    ) or None


def publish_skill(registry_client, registry_id: str,
                  skill_name: str, skill_content: str, description: str) -> dict:
    """Create or update a skill in the Registry, then submit for approval."""
    records = registry_client.list_registry_records(
        registryId=registry_id
    ).get("registryRecords", [])
    existing = next((r for r in records if r["name"] == skill_name), None)
    is_update = existing is not None

    if existing:
        record_id = existing["recordId"]
        registry_client.update_registry_record(
            registryId=registry_id,
            recordId=record_id,
            description={"optionalValue": description[:4096]},
            descriptors={"optionalValue": {
                "agentSkillsDefinition": {"optionalValue": {
                    "additionalData": {"optionalValue": {
                        "skillMd": {"optionalValue": {
                            "data": {"optionalValue": skill_content},
                        }},
                    }},
                }},
            }},
        )
    else:
        registry_client.create_registry_record(
            registryId=registry_id,
            name=skill_name,
            description=description[:4096],
            recordType="SKILL",
            descriptors={
                "agentSkillsDefinition": {
                    "additionalData": {
                        "skillMd": {"data": skill_content},
                    },
                }
            },
            recordVersion="1.0.0",
        )
        fresh = _poll(registry_client, registry_id,
                      lambda r: r if r["name"] == skill_name else None)
        if not fresh:
            return {"status": "error", "message": "Record not found after creation"}
        record_id = fresh["recordId"]

    for attempt in range(6):
        try:
            registry_client.submit_registry_record_for_approval(
                registryId=registry_id, recordId=record_id,
            )
            break
        except ClientError as e:
            msg = str(e)
            if "current status: APPROVED" in msg:
                break
            if "UPDATING" in msg and attempt < 5:
                time.sleep(3)
                continue
            raise
    record = _poll(registry_client, registry_id,
                   lambda r: r if r.get("recordId") == record_id else None)
    return {
        "status": (record or {}).get("status", "unknown").lower(),
        "record_id": record_id,
        "name": skill_name,
        "action": "updated" if is_update else "created",
    }


def _poll(registry_client, registry_id: str, match, attempts=5, interval=2):
    """Poll list_registry_records until match(record) returns a truthy value."""
    for _ in range(attempts):
        time.sleep(interval)
        records = registry_client.list_registry_records(
            registryId=registry_id
        ).get("registryRecords", [])
        for r in records:
            hit = match(r)
            if hit:
                return hit
    return None
