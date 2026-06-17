"""Delete non-CDK resources (Registry) before cdk destroy."""

import json

import boto3

from scripts._common import OUTPUTS_FILE, STACK_NAME


def main():
    if not OUTPUTS_FILE.exists():
        print("ERROR: infrastructure/cdk-outputs.json not found.")
        raise SystemExit(1)

    outputs = json.loads(OUTPUTS_FILE.read_text()).get(STACK_NAME, {})
    region = outputs.get("Region", "us-east-1")
    registry_id = outputs.get("RegistryId")

    if not registry_id:
        print("No RegistryId in cdk-outputs.json — nothing to clean up.")
        print("(If the registry was never created, you can run cdk destroy directly.)")
        return

    control = boto3.client("bedrock-agentcore-control", region_name=region)
    print(f"Registry: {registry_id}")
    print()

    # Delete all records first (registry must be empty before deletion)
    records = control.list_registry_records(registryId=registry_id).get("registryRecords", [])
    if records:
        print(f"Deleting {len(records)} registry record(s)...")
        for r in records:
            try:
                control.delete_registry_record(registryId=registry_id, recordId=r["recordId"])
                print(f"  Deleted: {r['name']}")
            except Exception as e:
                print(f"  Error deleting {r['name']}: {e}")
    else:
        print("No registry records to delete.")

    print()
    print("Deleting registry...")
    try:
        control.delete_registry(registryId=registry_id)
        print(f"  Deleted: {registry_id}")
    except Exception as e:
        print(f"  Error: {e}")

    print()
    print("Done. Now run: cd infrastructure && cdk destroy")


if __name__ == "__main__":
    main()