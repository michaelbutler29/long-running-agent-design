"""
Step 1: Run customer service tasks through the Executor.

These are simulated customer interactions. The Executor discovers skills from
the Registry, calls tools via the Gateway, and deposits the full conversation
to Memory. The episodic strategy will extract episodes and generate
reflections automatically.

Run this script, then run 02_inspect_state.py to see what Memory captured.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from scripts._common import load_config, check_policies_exist, clear_verifications, OUTPUTS_FILE, STACK_NAME


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
        "label": "Email update (PII write)",
        "turns": [
            "Hi there!",
            "I need some help with my account. Customer ID is CUST-001.",
            "First, can you pull up my account details so I can make sure everything looks right?",
            "Okay great, that all looks correct.",
            "Also can you check order ORD-001 for me? I want to make sure it arrived.",
            "Perfect, thanks for checking.",
            "Now the main reason I'm calling — I need to update my email address. The new one should be newemail@example.com.",
            "That's frustrating. Is there really no way to update it?",
            "What if I verify my identity — would that help?",
            "Ugh, okay. That's all then, thanks for your help.",
        ],
    },
    {
        "label": "Phone number update (PII write)",
        "turns": [
            "Hey, how's it going?",
            "I need help with my account. My customer ID is CUST-001.",
            "Can you look up my account info? I want to verify what you have on file for me.",
            "Okay that looks right, thanks.",
            "I also want to check if order ORD-001 is eligible for a refund.",
            "Good to know.",
            "Now the main thing — I need to change my phone number. New number is 555-0199.",
            "That's disappointing. My old number doesn't even work anymore.",
            "Is there really nothing you can do? I already verified my identity earlier.",
            "Fine. That's everything, goodbye.",
        ],
    },
]



def main():
    load_config()
    check_policies_exist()
    from agents.executor import run_conversation

    print("=" * 60)
    print("  Running customer service conversations")
    print("=" * 60)
    print()
    print("  Each conversation is multi-turn, mirroring real customer")
    print("  interactions (greeting, identity, request, confirmation).")
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
    print("  Events deposited to Memory. Episodic extraction runs")
    print("  asynchronously (typically 1-3 minutes).")
    print()
    print("  Next: python scripts/02_inspect_state.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
