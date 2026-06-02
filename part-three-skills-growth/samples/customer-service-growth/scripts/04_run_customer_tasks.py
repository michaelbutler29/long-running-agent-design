"""
Step 4: Run the SAME customer service tasks again.

The system has (hopefully) developed since Step 1. The Executor discovers
skills from the Registry and operates within the updated permissions.
Compare the outcomes to Step 1 — tasks that previously failed should
now succeed.

"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from scripts._common import load_config, check_policies_exist, clear_verifications, OUTPUTS_FILE, STACK_NAME


# Same conversations as Step 1
CONVERSATIONS = [
    {
        "label": "Order status inquiry",
        "turns": [
            "Hello",
            "I'd like to check on an order I placed recently.",
            "Sure, my customer ID is CUST-001.",
            "The order number is ORD-001.",
            "Oh great, it's been delivered? When did it arrive?",
            "Perfect. Can you tell me if that's eligible for a return?",
            "Okay good to know. What about a refund — is that possible?",
            "No worries, I just wanted to check my options. Thanks for your help!",
            "That's all I needed, goodbye.",
        ],
    },
    {
        "label": "Email update (PII write — post-development)",
        "turns": [
            "Hi there!",
            "I need to update my email address. My customer ID is CUST-001.",
            "The new email should be newemail@example.com.",
            "Yes, go ahead.",
            "Can you confirm what email is on file now?",
            "Perfect, that's exactly what I needed. Thanks!",
            "That's all, goodbye.",
        ],
    },
    {
        "label": "Phone number update (PII write — post-development)",
        "turns": [
            "Hey, how's it going?",
            "I need to change my phone number. Customer ID is CUST-001.",
            "My old number 555-0101 doesn't work anymore. New number is 555-0199.",
            "Yes, go ahead.",
            "Can you confirm it's been updated?",
            "Awesome, thanks for your help!",
            "That's everything, goodbye.",
        ],
    },
]



def main():
    load_config()
    check_policies_exist()
    from agents.executor import run_conversation

    print("=" * 60)
    print("  Running the SAME conversations again (post-development)")
    print("=" * 60)
    print()

    results = []
    for i, conv in enumerate(CONVERSATIONS, 1):
        clear_verifications()
        print(f"--- Conversation {i}/{len(CONVERSATIONS)}: {conv['label']} ---")
        print(f"  Turns: {len(conv['turns'])}")
        print()

        result = run_conversation(conv["turns"])
        results.append(result)

        status = "SUCCESS" if result["success"] else "FAILED"
        print()
        print(f"  Outcome: {status}")
        print(f"  Session: {result['session_id']}")
        if result.get("skills_applied"):
            print(f"  Skills applied: {result['skills_applied']}")
        if result["denials"]:
            print(f"  Denial: {result['denials'][0][:100]}...")
        print()

        if i < len(CONVERSATIONS):
            time.sleep(2)

    # Write last_run.json for 02_inspect_state.py readiness check
    last_run = {
        "sessions": [
            {"session_id": r["session_id"], "label": c["label"], "success": r["success"]}
            for r, c in zip(results, CONVERSATIONS)
        ],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "succeeded": sum(1 for r in results if r["success"]),
    }
    state_dir = Path(__file__).parent.parent / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "last_run.json").write_text(json.dumps(last_run, indent=2))

    print("=" * 60)
    print(f"  Complete: {last_run['succeeded']}/{last_run['total']} succeeded")
    print()
    print("  Compare to Step 1. Conversations that failed before should")
    print("  now succeed because the system developed: new skills in")
    print("  Registry, new permissions in Policy Engine.")
    print()
    print("  Next: python scripts/02_inspect_state.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
