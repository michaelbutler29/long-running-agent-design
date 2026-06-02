"""
Step 3: Trigger a curation cycle.

The Curator reads reflections from Memory (generated automatically by
the episodic strategy), decides whether to author new skills or propose
permissions, and writes its decisions back to Memory. During this process
the Curator also reflects on its prior decisions and determines if it needs
updates to its own reasoning (prompt) and/or curation skill.

Run 02_inspect_state.py after this to see what changed.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

OUTPUTS_FILE = Path(__file__).parent.parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "SkillGrowthStack"


def load_config():
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    os.environ.setdefault("AWS_REGION", outputs.get("Region", "us-east-1"))
    os.environ.setdefault("AGENTCORE_GATEWAY_URL", outputs["GatewayUrl"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ARN", outputs["GatewayArn"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ID", outputs["GatewayId"])
    os.environ.setdefault("AGENTCORE_MEMORY_ID", outputs["MemoryId"])
    os.environ.setdefault("AGENTCORE_REGISTRY_ID", outputs["RegistryId"])
    os.environ.setdefault("AGENTCORE_POLICY_ENGINE_ID", outputs["PolicyEngineId"])


def main():
    load_config()
    from agents.curator import run_curation_cycle

    print("=" * 60)
    print("  Running Curator")
    print("=" * 60)
    print()
    print("  The Curator reads reflections from Memory and decides")
    print("  whether the fleet needs new skills or permissions.")
    print()

    result = run_curation_cycle()

    print()
    print("=" * 60)
    print("  Curation cycle complete.")
    print()
    print("  Next: python scripts/02_inspect_state.py")
    print("        (to see what changed in Registry and Policy Engine)")
    print("=" * 60)


if __name__ == "__main__":
    main()
