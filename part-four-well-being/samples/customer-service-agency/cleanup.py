"""Delete non-CDK resources (Registry, Policies) before cdk destroy."""

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
    engine_id = outputs.get("PolicyEngineId")

    control = boto3.client("bedrock-agentcore-control", region_name=region)
    registry = boto3.client("agent-registry-control", region_name=region)

    # Clear policies (Policy Engine won't delete with active policies)
    if engine_id:
        print(f"Policy Engine: {engine_id}")
        try:
            policies = control.list_policies(policyEngineId=engine_id).get("policies", [])
            if policies:
                print(f"  Deleting {len(policies)} policy/policies...")
                for p in policies:
                    try:
                        control.delete_policy(policyEngineId=engine_id, policyId=p["policyId"])
                        print(f"    Deleted: {p['name']}")
                    except Exception as e:
                        print(f"    Error deleting {p['name']}: {e}")
            else:
                print("  No policies to delete.")
        except Exception as e:
            print(f"  Policy Engine not found or inaccessible: {e}")
        print()

    # Clear registry
    if registry_id:
        print(f"Registry: {registry_id}")
        try:
            records = registry.list_registry_records(registryId=registry_id).get("registryRecords", [])
            if records:
                print(f"  Deleting {len(records)} registry record(s)...")
                for r in records:
                    try:
                        registry.delete_registry_record(registryId=registry_id, recordId=r["recordId"])
                        print(f"    Deleted: {r['name']}")
                    except Exception as e:
                        print(f"    Error deleting {r['name']}: {e}")
            else:
                print("  No registry records to delete.")

            print()
            print("  Deleting registry...")
            try:
                registry.delete_registry(registryId=registry_id)
                print(f"    Deleted: {registry_id}")
            except Exception as e:
                print(f"    Error: {e}")
        except Exception as e:
            print(f"  Registry not found or inaccessible: {e}")
    else:
        print("No RegistryId in cdk-outputs.json — skipping registry cleanup.")

    print()
    print("Done. Now run: cd infrastructure && cdk destroy")


if __name__ == "__main__":
    main()