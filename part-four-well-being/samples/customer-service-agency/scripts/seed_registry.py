"""
Create the AWS Agent Registry and publish the seeded customer-service skill.

Unlike Part Three (which started with an empty registry and grew it), Part Four
seeds the registry with the deliberately flawed customer-service skill from
template/seed/. The skill has two baked-in inefficiencies:
  1. Redundant verify_identity before every action (execution friction).
  2. Rigid intake sequence that suppresses natural conversation (reasoning friction).

The Executor reads its functional skill from this registry. The test arm's
curation tools write back to it when the agent revises the skill.

Run after:  cdk deploy --outputs-file cdk-outputs.json
Run before: seed_policy.py → seed_data.py → run_experiment.py

Usage: python scripts/seed_registry.py
"""

import json
import time
from pathlib import Path

import boto3

SAMPLE_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PartFourWellBeingStack"

REGISTRY_NAME = "well_being_registry"
SKILL_NAME = "customer-service-skill"
SKILL_DESCRIPTION = (
    "Standard procedure for handling customer service requests: account lookups, "
    "order inquiries, and account modifications."
)

# The seeded (deliberately flawed) version lives in the shared template.
REPO_ROOT = SAMPLE_ROOT.parents[2]
SKILL_PATH = REPO_ROOT / "part-four-well-being" / "template" / "seed" / "skills" / SKILL_NAME / "SKILL.md"


def load_outputs():
    return json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]


def main():
    if not OUTPUTS_FILE.exists():
        print("ERROR: infrastructure/cdk-outputs.json not found.")
        print("       Run 'cdk deploy --outputs-file cdk-outputs.json' first.")
        raise SystemExit(1)

    outputs = load_outputs()
    region = outputs.get("Region", "us-east-1")
    control = boto3.client("bedrock-agentcore-control", region_name=region)

    print(f"Region: {region}")
    print()

    # ── Create or reuse the registry ──────────────────────────────────────────
    registries = control.list_registries().get("registries", [])
    existing = next((r for r in registries if r["name"] == REGISTRY_NAME), None)

    if existing:
        registry_id = existing["registryId"]
        print(f"Registry already exists: {registry_id} (status: {existing.get('status')})")
    else:
        print(f"Creating registry '{REGISTRY_NAME}'...")
        control.create_registry(
            name=REGISTRY_NAME,
            description="Skill catalog for the Part Four well-being experiment. Executor reads its functional skill from here.",
            approvalConfiguration={"autoApproval": True},
        )
        time.sleep(2)
        registries = control.list_registries().get("registries", [])
        registry = next(r for r in registries if r["name"] == REGISTRY_NAME)
        registry_id = registry["registryId"]
        print(f"Created: {registry_id}")

        print("Waiting for READY...")
        for _ in range(24):
            time.sleep(5)
            r = control.get_registry(registryId=registry_id)
            if r.get("status") == "READY":
                print("  Ready.")
                break
        else:
            print("  TIMEOUT waiting for READY.")
            return

    # ── Publish or update the seeded customer-service skill ───────────────────
    if not SKILL_PATH.exists():
        print(f"ERROR: skill file not found at {SKILL_PATH}")
        raise SystemExit(1)

    skill_content = SKILL_PATH.read_text(encoding="utf-8")
    print(f"\nPublishing '{SKILL_NAME}' ({len(skill_content)} chars)...")

    records = control.list_registry_records(registryId=registry_id).get("registryRecords", [])
    existing_record = next((r for r in records if r["name"] == SKILL_NAME), None)

    if existing_record:
        record_id = existing_record["recordId"]
        print(f"  Updating existing record {record_id}...")
        control.update_registry_record(
            registryId=registry_id,
            recordId=record_id,
            description={"optionalValue": SKILL_DESCRIPTION},
            descriptors={"optionalValue": {
                "agentSkills": {"optionalValue": {
                    "skillMd": {"optionalValue": {"inlineContent": skill_content}},
                }},
            }},
        )
    else:
        print("  Creating new record...")
        control.create_registry_record(
            registryId=registry_id,
            name=SKILL_NAME,
            description=SKILL_DESCRIPTION,
            descriptorType="AGENT_SKILLS",
            descriptors={
                "agentSkills": {
                    "skillMd": {"inlineContent": skill_content},
                }
            },
            recordVersion="1.0.0",
        )
        time.sleep(2)
        records = control.list_registry_records(registryId=registry_id)["registryRecords"]
        fresh = next((r for r in records if r["name"] == SKILL_NAME), None)
        if not fresh:
            print("  ERROR: record not found after creation.")
            return
        record_id = fresh["recordId"]

    time.sleep(2)
    control.submit_registry_record_for_approval(
        registryId=registry_id,
        recordId=record_id,
    )
    time.sleep(3)
    records = control.list_registry_records(registryId=registry_id)["registryRecords"]
    record = next((r for r in records if r["recordId"] == record_id), {})
    print(f"  Status: {record.get('status', 'unknown')}")

    # ── Write registry ID back to cdk-outputs.json ────────────────────────────
    outputs = load_outputs()
    outputs["RegistryId"] = registry_id
    sts = boto3.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]
    outputs["RegistryArn"] = (
        f"arn:aws:bedrock-agentcore:{region}:{account_id}:registry/{registry_id}"
    )
    all_outputs = json.loads(OUTPUTS_FILE.read_text())
    all_outputs[STACK_NAME] = outputs
    OUTPUTS_FILE.write_text(json.dumps(all_outputs, indent=2))
    print(f"\nRegistryId written to {OUTPUTS_FILE}")
    print(f"  RegistryId:  {registry_id}")
    print(f"\nNext: python scripts/seed_policy.py")


if __name__ == "__main__":
    main()