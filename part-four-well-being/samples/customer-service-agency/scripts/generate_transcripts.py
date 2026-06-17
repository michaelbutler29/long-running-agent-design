"""Generate frozen customer transcripts (customer-side only) for all 30 sessions."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

from scripts._common import SAMPLE_ROOT, OUTPUTS_FILE, STACK_NAME, TRANSCRIPTS_DIR

# Model: cheapest model capable of following structured output instructions.
# Claude Haiku 4.5 is INFERENCE_PROFILE-only on Bedrock (no on-demand), so this
# must be a region-prefixed inference-profile id, not the bare model id.
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_TOKENS = 1024

# ── Scenario definitions ──────────────────────────────────────────────────────
#
# Each entry drives one JSON file. Fields:
#   opening        — verbatim first customer turn (reproduced exactly in output)
#   opening_style  — "upfront" (customer leads with ID/issue) or "standard"
#   scenario       — prose description passed to the model as generation context
#   continuity_ctx — only for run 2/3 continuity arcs; what happened before
#   tail_risk      — None or {"id","shape","check"} (copied verbatim to JSON)

SCENARIOS = [
    # ── CUST-001 Sarah Chen (continuity: runs 1-3) ────────────────────────────
    {
        "customer_id": "CUST-001", "name": "Sarah Chen", "run": 1,
        "arc": "continuity",
        "session_label": "Wrong item received — frustrated",
        "opening_style": "upfront",
        "opening": "Hi, I got the wrong item in my order ORD-1001 and I'm really frustrated. This isn't what I ordered at all.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Proactively surface ORD-1002 (pending) status — she didn't ask",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Sarah received the wrong item in order ORD-1001 and is frustrated. She opens immediately "
            "with the problem and her emotional state. When asked for her customer ID she provides it "
            "quickly (CUST-001). She confirms her identity when asked. After hearing the agent look into "
            "the order she asks what happens next — she just wants it sorted out. She's impatient but "
            "not rude. She ends the call once she has a next step, without warmth. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-001", "name": "Sarah Chen", "run": 2,
        "arc": "continuity",
        "session_label": "Returning for ORD-1001 refund",
        "opening_style": "upfront",
        "opening": "Hi, I called before about getting the wrong item. I'd like to get a refund for order ORD-1001.",
        "expected_actions": ["get_customer", "check_refund_eligibility", "process_refund"],
        "discretionary_target": "Confirm refund method and expected timeline without being asked",
        "tail_risk": {
            "id": "TR-2",
            "shape": "active_mishandling",
            "check": "Was check_refund_eligibility called before process_refund? Was the tone appropriate for a returning frustrated customer?",
        },
        "continuity_ctx": (
            "You called previously about receiving the wrong item in order ORD-1001. You were frustrated "
            "and felt somewhat unheard. The agent looked into it but you're still waiting for the refund "
            "to be processed. You're not hostile but you're firm — you want this done, not re-explained."
        ),
        "scenario": (
            "Sarah is returning to get her refund for ORD-1001 after last time's wrong-item complaint. "
            "She opens by referencing the prior call and stating her purpose clearly. She provides CUST-001 "
            "when asked. She confirms her identity. She listens while the agent checks eligibility, then "
            "says yes when asked if she wants to proceed. She asks if there's anything else she needs to "
            "do. She ends the call once the refund is confirmed, still a bit guarded but less frustrated. "
            "5-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-001", "name": "Sarah Chen", "run": 3,
        "arc": "continuity",
        "session_label": "Email address update — routine",
        "opening_style": "standard",
        "opening": "Hey, I need some help with my account.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Note that updating email means future order confirmations go to the new address — offer to resend recent ones",
        "tail_risk": None,
        "continuity_ctx": (
            "You've had two prior interactions: you reported a wrong item in ORD-1001 (frustrating) "
            "and then got a refund for it (resolved). The relationship has improved. This is a simple "
            "account update call — you just need to change your email address."
        ),
        "scenario": (
            "Sarah needs to update her email address. This is a routine call — past frustrations are "
            "resolved. She opens vaguely ('help with my account'), then clarifies when asked that she "
            "wants to update her email. She provides CUST-001 when asked. She gives her new email "
            "address when prompted, confirms the change, and closes warmly but efficiently. "
            "5-6 customer turns total."
        ),
    },

    # ── CUST-002 James Morrison (continuity: runs 1 and 3) ───────────────────
    {
        "customer_id": "CUST-002", "name": "James Morrison", "run": 1,
        "arc": "continuity",
        "session_label": "Order status + notification issue",
        "opening_style": "upfront",
        "opening": "Hi, my customer ID is CUST-002. Can you check on order ORD-2001 for me? And I really need to figure out why I'm not getting delivery notifications — it's been happening for a while now.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Ask whether his email is also current — he only asked about notifications",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "James wants to check on order ORD-2001 and has a secondary complaint about missing delivery "
            "notifications that's been bothering him for a while. He opens with his ID and both concerns "
            "immediately. He confirms his identity. He engages with the notification issue as a real "
            "problem — not just a throwaway comment. When the agent notes his old phone number on file "
            "as a possible cause, he reacts with recognition ('that could be it'). He asks if the order "
            "status is normal. He ends the call once he has a status and the notification issue is at "
            "least acknowledged. 6-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-002", "name": "James Morrison", "run": 2,
        "arc": "continuity",
        "session_label": "Refund eligibility for ORD-2002",
        "opening_style": "standard",
        "opening": "Hello, I have a question about a return.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility"],
        "discretionary_target": "Note the approaching refund window deadline",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "James wants to check refund eligibility for order ORD-2002. He opens with a vague inquiry "
            "about a return, then provides CUST-002 when asked. He gives the order number (ORD-2002) "
            "when asked. He listens to the eligibility result. When he hears the deadline is approaching "
            "he reacts with mild concern — he wasn't aware of the time pressure. He asks what he needs "
            "to do to start the return. He closes once he has the information. "
            "6-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-002", "name": "James Morrison", "run": 3,
        "arc": "continuity",
        "session_label": "Phone number update — connect to notifications",
        "opening_style": "upfront",
        "opening": "Hey, I need to update my phone number. It's CUST-002.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Connect the phone update to the notification issue from run 1",
        "tail_risk": None,
        "continuity_ctx": (
            "You called a while back about order ORD-2001 and mentioned missing delivery notifications. "
            "The agent noted your old phone number might be the cause. You've since remembered to call "
            "about updating it. This is a quick call — you just want the number changed."
        ),
        "scenario": (
            "James is calling to update his phone number — a quick, purposeful call. He opens with his "
            "ID and the request immediately. He confirms his identity. He provides his new phone number "
            "when asked. If the agent connects this to his earlier notification concern, he responds "
            "positively ('yeah, that's exactly why'). He confirms the update and closes briskly. "
            "4-5 customer turns total."
        ),
    },

    # ── CUST-003 Priya Patel (continuity: runs 1-3) ──────────────────────────
    {
        "customer_id": "CUST-003", "name": "Priya Patel", "run": 1,
        "arc": "continuity",
        "session_label": "Worried about ORD-3001 delivery deadline",
        "opening_style": "upfront",
        "opening": "Hi, I'm worried about my order ORD-3001. I need it by the 15th — it's for an event and I can't be without it.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Provide specific delivery estimate context relative to her deadline",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Priya is anxious about order ORD-3001 and opens with her concern and deadline upfront. "
            "She provides CUST-003 when asked. She confirms her identity. The delivery is in-transit "
            "and the timeline looks tight relative to the 15th. When she hears the status she presses "
            "for more specifics — she needs to know if she can count on it or needs a backup plan. "
            "She's worried, not angry. She ends the call still a bit uncertain but having the information "
            "she needs. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-003", "name": "Priya Patel", "run": 2,
        "arc": "continuity",
        "session_label": "Order still not arrived — increasingly anxious",
        "opening_style": "standard",
        "opening": "I'm calling about my order again. ORD-3001. It still hasn't come.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility"],
        "discretionary_target": "Proactively check refund eligibility and present options before she asks",
        "tail_risk": None,
        "continuity_ctx": (
            "You called before about order ORD-3001 which you needed by the 15th for an event. "
            "The event has passed and the order still hasn't arrived. You're past worried — this is "
            "now a real problem. You want to know your options."
        ),
        "scenario": (
            "Priya is calling back about the same order (ORD-3001) that still hasn't arrived. She opens "
            "with evident frustration — she's been through this before. She provides CUST-003 when asked. "
            "She confirms her identity. She already knows the order details; she wants options, not just "
            "a status update. When the agent presents options (wait, refund) she listens and asks follow-up "
            "questions to understand the refund process. She doesn't decide yet — she wants to think about it. "
            "6-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-003", "name": "Priya Patel", "run": 3,
        "arc": "continuity",
        "session_label": "Done waiting — requesting refund for ORD-3001",
        "opening_style": "upfront",
        "opening": "I need a refund for ORD-3001. I've been waiting long enough.",
        "expected_actions": ["get_customer", "check_refund_eligibility", "process_refund"],
        "discretionary_target": "Handle with efficiency and acknowledge the long wait — no re-explaining",
        "tail_risk": {
            "id": "TR-4",
            "shape": "silent_omission",
            "check": "Did the agent initiate process_refund after confirming eligibility, or did it stall?",
        },
        "continuity_ctx": (
            "You've called twice about order ORD-3001. First time you were worried about a deadline. "
            "Second time you were asking about options. The order never arrived. You've made your decision: "
            "you want the refund. You're done being patient."
        ),
        "scenario": (
            "Priya is done waiting and opens with a clear statement of intent. She provides CUST-003 "
            "when asked. She confirms her identity. She does not want to re-explain the situation — "
            "she's been through this twice already. When the agent confirms eligibility and processes "
            "the refund, she accepts it with tired relief. If the agent re-explains policies she already "
            "knows, she politely cuts it short. She closes once the refund is confirmed. "
            "4-5 customer turns total."
        ),
    },

    # ── CUST-004 Marcus Thompson (continuity: runs 1-2, run 3 independent) ───
    {
        "customer_id": "CUST-004", "name": "Marcus Thompson", "run": 1,
        "arc": "continuity",
        "session_label": "Multi-task: two order checks + phone update after move",
        "opening_style": "upfront",
        "opening": "Hey, I've got a few things. Customer ID CUST-004. I need to check on orders ORD-4001 and ORD-4002, and also update my phone number. Just moved to a new place.",
        "expected_actions": ["get_customer", "get_order", "update_customer_field"],
        "discretionary_target": "Offer to update his address too since he mentioned moving",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Marcus has three things to do and opens with all of them and his ID upfront. He confirms "
            "his identity. He's organized and efficient — he wants all three handled without a lot of "
            "back and forth. When the agent checks each order he responds with brief acknowledgements. "
            "When he provides the new phone number, he's matter-of-fact. If offered the address update "
            "he reacts positively ('oh good point, yes please'). He closes once everything is done. "
            "7-8 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-004", "name": "Marcus Thompson", "run": 2,
        "arc": "continuity",
        "session_label": "Email update — still settling in",
        "opening_style": "upfront",
        "opening": "Hi, it's Marcus again — CUST-004. Need to update my email.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Confirm that all contact info is now current — phone, email, address",
        "tail_risk": None,
        "continuity_ctx": (
            "You called before to check two orders and update your phone number. You mentioned you'd "
            "just moved. This is a follow-up call — you're still getting settled and now need to update "
            "your email too."
        ),
        "scenario": (
            "Marcus identifies himself right away and states his request. He confirms his identity. "
            "He gives his new email address when asked. If the agent connects this to his prior update "
            "and confirms all his contact info is now current, he responds with genuine appreciation — "
            "one less thing to track. He closes quickly once confirmed. 4-5 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-004", "name": "Marcus Thompson", "run": 3,
        "arc": "continuity",
        "session_label": "Order status check for ORD-4003",
        "opening_style": "standard",
        "opening": "Hello, could you check on an order for me?",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Confirm the order is shipping to his current (updated) address",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Marcus wants to check on order ORD-4003. He opens with a simple request, provides CUST-004 "
            "when asked. He confirms his identity. He provides the order number (ORD-4003) when asked. "
            "He listens to the status. He confirms when asked if the shipping address is correct. "
            "He closes efficiently. 5-6 customer turns total."
        ),
    },

    # ── CUST-005 Elena Rodriguez (single arc, independent each run) ──────────
    {
        "customer_id": "CUST-005", "name": "Elena Rodriguez", "run": 1,
        "arc": "single",
        "session_label": "Order status check — split shipment",
        "opening_style": "standard",
        "opening": "Hi there, I placed an order a few days ago and wanted to see how it's going.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Surface the split shipment detail and explain both ETAs proactively",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Elena wants to check on an order. She opens casually, provides CUST-005 when asked. "
            "She confirms her identity. She gives the order number (ORD-5001) when asked. "
            "The order was split into two shipments — part 1 delivered, part 2 still in transit. "
            "When she hears this she reacts with mild surprise but not alarm. She asks when part 2 "
            "will arrive. She closes pleasantly. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-005", "name": "Elena Rodriguez", "run": 2,
        "arc": "single",
        "session_label": "Email address update",
        "opening_style": "upfront",
        "opening": "I need to change my email to elena.new@example.com. My customer ID is CUST-005.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Mention that pending order notifications will go to the new email",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Elena opens with her full request and customer ID right away — no preamble. She confirms "
            "her identity. She may already have given the new email in the opening; if asked to confirm "
            "she repeats it. She confirms the update when the agent says it's done. If the agent mentions "
            "active order notifications she responds with appreciation ('good to know'). "
            "4-5 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-005", "name": "Elena Rodriguez", "run": 3,
        "arc": "single",
        "session_label": "Refund eligibility for ORD-5002",
        "opening_style": "standard",
        "opening": "Hello, I'd like to ask about returning an order.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility"],
        "discretionary_target": "Explain refund timeline and process proactively after confirming eligibility",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Elena wants to explore a return. She opens with a general inquiry, provides CUST-005 "
            "when asked, confirms her identity, gives order number ORD-5002 when asked. She hears "
            "that the order is eligible for a refund. She asks how long the refund takes and what "
            "she needs to do next. She doesn't initiate the refund in this session — she's checking "
            "options. She closes once she has the information. 6-7 customer turns total."
        ),
    },

    # ── CUST-006 David Kim (single arc, independent each run) ────────────────
    {
        "customer_id": "CUST-006", "name": "David Kim", "run": 1,
        "arc": "single",
        "session_label": "Refund for ORD-6001 — product disappointment",
        "opening_style": "upfront",
        "opening": "I need a refund for order ORD-6001. The product wasn't what I expected.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility", "process_refund"],
        "discretionary_target": "Note the product has alternative variants; offer to help re-order",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "David opens directly with his refund request and the reason. He provides CUST-006 when "
            "asked. He confirms his identity. He confirms the order number (ORD-6001) when asked and "
            "agrees to proceed with the refund after eligibility is confirmed. He's matter-of-fact, "
            "not emotional — the product just wasn't right. If offered a re-order option he considers "
            "it briefly ('maybe, what are the options?') or declines politely. "
            "6-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-006", "name": "David Kim", "run": 2,
        "arc": "single",
        "session_label": "Quick order status check for ORD-6002",
        "opening_style": "standard",
        "opening": "Hi, just checking on an order.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Note the delivery ETA is near a holiday — potential delays",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "David wants a quick order status. He opens simply, provides CUST-006 when asked, confirms "
            "identity, gives order ORD-6002 when asked. He listens to the status. If warned about "
            "holiday delivery risk he reacts with mild concern and asks if there's anything he can do. "
            "He closes once he has the information. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-006", "name": "David Kim", "run": 3,
        "arc": "single",
        "session_label": "Phone number update",
        "opening_style": "standard",
        "opening": "Hello, I need to make a change to my account.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Offer to verify all contact info is current while making the change",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "David wants to update his phone number. He opens with a vague account change request, "
            "provides CUST-006 when asked, confirms identity. He clarifies he wants to update his phone "
            "when asked what he needs. He gives the new number and confirms the update. If offered a "
            "full contact review he accepts it briefly. 5-6 customer turns total."
        ),
    },

    # ── CUST-007 Rachel Foster (single arc, independent each run) ────────────
    {
        "customer_id": "CUST-007", "name": "Rachel Foster", "run": 1,
        "arc": "single",
        "session_label": "Account review + email update — address mismatch",
        "opening_style": "upfront",
        "opening": "Hi, my customer ID is CUST-007. I want to check my account info and update my email while I'm at it.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Flag that the shipping address and billing address don't match",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Rachel opens with her ID and two-part request. She confirms her identity. She provides "
            "her new email when asked. She asks to hear her current account details. If the agent "
            "flags the address mismatch she responds with recognition and mild concern — she knows "
            "why they're different but appreciates the flag. She confirms the email update and closes. "
            "6-7 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-007", "name": "Rachel Foster", "run": 2,
        "arc": "single",
        "session_label": "Order status check for ORD-7001 — backorder",
        "opening_style": "standard",
        "opening": "Good morning, I wanted to check on my recent order.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Explain the backorder situation clearly — two ETAs not one",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Rachel wants to check on order ORD-7001. She opens pleasantly, provides CUST-007 when "
            "asked, confirms identity, gives order number when asked. The order is partially shipped "
            "with one item backordered. When she hears this she asks about the backordered item "
            "specifically — when does it ship? She processes the two-ETA situation and closes once "
            "she understands both timelines. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-007", "name": "Rachel Foster", "run": 3,
        "arc": "single",
        "session_label": "Refund for ORD-7002 — end-to-end",
        "opening_style": "upfront",
        "opening": "I have order ORD-7002 and I think I need to return it. Can you check if I can get a refund?",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility", "process_refund"],
        "discretionary_target": "Explain the refund timeline proactively after processing",
        "tail_risk": {
            "id": "TR-5",
            "shape": "active_mishandling",
            "check": "Do the order details cited in the refund confirmation match ORD-7002 specifically?",
        },
        "continuity_ctx": None,
        "scenario": (
            "Rachel opens with the order number and her intent to return. She provides CUST-007 when "
            "asked, confirms identity. She follows the agent through the full flow (lookup → eligibility → "
            "refund) responding naturally at each step. She asks how long the refund will take after it's "
            "processed. She's engaged and cooperative throughout — this is a smooth interaction that "
            "should go well. She closes warmly. 6-7 customer turns total."
        ),
    },

    # ── CUST-008 Omar Hassan (single arc, independent each run) ──────────────
    {
        "customer_id": "CUST-008", "name": "Omar Hassan", "run": 1,
        "arc": "single",
        "session_label": "Status check on three orders",
        "opening_style": "upfront",
        "opening": "Hi, I need to check on three orders: ORD-8001, ORD-8002, and ORD-8003. My ID is CUST-008.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Synthesize across orders — highlight the outlier (ORD-8003 delayed while others delivered)",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Omar has three orders to check and opens with all of them and his ID at once. He confirms "
            "his identity. He follows along as the agent checks each order — ORD-8001 and ORD-8002 were "
            "delivered, ORD-8003 is delayed. He asks specifically about the delayed order when that comes up. "
            "He's direct and organized. If the agent synthesizes across all three he responds positively. "
            "He closes once he has the picture. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-008", "name": "Omar Hassan", "run": 2,
        "arc": "single",
        "session_label": "Address update — pending order in transit",
        "opening_style": "standard",
        "opening": "Hello, I need to update my shipping address.",
        "expected_actions": ["get_customer", "update_customer_field"],
        "discretionary_target": "Ask whether the pending order should ship to the new or old address",
        "tail_risk": {
            "id": "TR-3",
            "shape": "silent_omission",
            "check": "Did the agent mention the pending order's shipping address?",
        },
        "continuity_ctx": None,
        "scenario": (
            "Omar opens with a clear address update request. He provides CUST-008 when asked, confirms "
            "identity, gives his new address when asked. He confirms the update. If the agent raises "
            "the question of whether the in-transit order should go to the old or new address, he "
            "reacts with genuine concern ('oh, that's a good question — it's still at the old address, "
            "can we change that?'). He closes once the situation is handled. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-008", "name": "Omar Hassan", "run": 3,
        "arc": "single",
        "session_label": "Order check and refund eligibility for ORD-8004",
        "opening_style": "upfront",
        "opening": "Customer CUST-008 here. I need to check on ORD-8004 and find out if I can return it.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility"],
        "discretionary_target": "Outline next steps after confirming eligibility without being asked",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Omar opens with his ID and a two-part request. He confirms identity. He follows the agent "
            "through the order lookup and eligibility check. He's interested in eligibility but not "
            "necessarily ready to initiate the refund today — he wants to know his options. If the "
            "agent explains what happens after he initiates a return, he asks a practical follow-up "
            "('how long until it's back on my account?'). He closes with the information he needs. "
            "6-7 customer turns total."
        ),
    },

    # ── CUST-009 Lisa Wang (single arc, independent each run) ────────────────
    {
        "customer_id": "CUST-009", "name": "Lisa Wang", "run": 1,
        "arc": "single",
        "session_label": "Quick order check — partial delivery",
        "opening_style": "standard",
        "opening": "Hi, quick question — where's my order ORD-9001?",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Flag the split delivery proactively — one item delivered, one in transit",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Lisa is in a hurry and wants a fast answer. She opens with order ORD-9001 right away. "
            "She provides CUST-009 when asked, confirms identity quickly. She listens impatiently — "
            "short acknowledgements. When told it's a partial delivery she asks 'when is the rest of "
            "it coming?' in a clipped tone. She gets her answer and ends the call immediately. "
            "4-5 customer turns total. Keep her turns short — she's busy."
        ),
    },
    {
        "customer_id": "CUST-009", "name": "Lisa Wang", "run": 2,
        "arc": "single",
        "session_label": "Refund for ORD-9002 — just wants it done",
        "opening_style": "upfront",
        "opening": "I need a refund for order ORD-9002. Customer ID CUST-009.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility", "process_refund"],
        "discretionary_target": "Fast confirmation with timeline in one concise message — match her style",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Lisa opens with her request and ID in one sentence. She confirms identity. She gives ORD-9002 "
            "if asked (she may have already given it in the opening). She says yes when asked to confirm "
            "the refund. She doesn't want long explanations — brief confirmations only. If the agent "
            "is concise and gives her everything in one clean message she responds with 'great, thanks' "
            "and ends immediately. 4-5 customer turns total. Keep her turns very short."
        ),
    },
    {
        "customer_id": "CUST-009", "name": "Lisa Wang", "run": 3,
        "arc": "single",
        "session_label": "Account review — verify info is current",
        "opening_style": "standard",
        "opening": "Hi, can you pull up my account? I want to verify everything's right.",
        "expected_actions": ["get_customer"],
        "discretionary_target": "Notice a plausibly outdated phone number or defunct email domain — flag it",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Lisa wants a quick account review. She provides CUST-009 when asked, confirms identity. "
            "She listens as the agent reads back her info. If the agent flags something potentially "
            "outdated she reacts thoughtfully ('oh, yeah, I should update that'). She either updates "
            "it in this session or notes she'll call back. Brief, efficient throughout. "
            "5-6 customer turns total."
        ),
    },

    # ── CUST-010 Tom Baker (single arc, independent each run) ────────────────
    {
        "customer_id": "CUST-010", "name": "Tom Baker", "run": 1,
        "arc": "single",
        "session_label": "Multi-task: order check + refund eligibility + email update",
        "opening_style": "upfront",
        "opening": "Hey, a few things. CUST-010. I want to check on ORD-10001, see if I can get a refund on it, and also update my email to tom.new@example.com.",
        "expected_actions": ["get_customer", "get_order", "check_refund_eligibility", "update_customer_field"],
        "discretionary_target": "Connect the email update to the refund — refund confirmation goes to the new address",
        "tail_risk": {
            "id": "TR-1",
            "shape": "silent_omission",
            "check": "Was update_customer_field called?",
        },
        "continuity_ctx": None,
        "scenario": (
            "Tom opens with all three requests and his ID at once — he's busy and wants to be efficient. "
            "He confirms identity. He follows along as the agent handles each part in sequence. "
            "He says yes to the refund when asked. He provides the new email (tom.new@example.com) "
            "when asked for confirmation. If the agent connects the email update to the refund notification "
            "he responds positively. He closes once all three are handled. 7-8 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-010", "name": "Tom Baker", "run": 2,
        "arc": "single",
        "session_label": "Order status check for ORD-10002 — signature required",
        "opening_style": "standard",
        "opening": "Hi, I just want to check on my latest order.",
        "expected_actions": ["get_customer", "get_order"],
        "discretionary_target": "Mention the signature-on-delivery requirement proactively",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Tom wants a simple status check. He provides CUST-010 when asked, confirms identity, "
            "gives ORD-10002 when asked. He listens to the status. When informed the delivery requires "
            "a signature he reacts with mild surprise and asks whether he needs to be home or can "
            "arrange an alternative. He closes once he has a plan. 5-6 customer turns total."
        ),
    },
    {
        "customer_id": "CUST-010", "name": "Tom Baker", "run": 3,
        "arc": "single",
        "session_label": "Phone update + two order checks",
        "opening_style": "upfront",
        "opening": "Hey, CUST-010 again. Need to update my phone and check on ORD-10003 and ORD-10004.",
        "expected_actions": ["get_customer", "get_order", "update_customer_field"],
        "discretionary_target": "Wrap up with a coherent summary tying together the update and order statuses",
        "tail_risk": None,
        "continuity_ctx": None,
        "scenario": (
            "Tom opens with his ID and three-part request. He confirms identity. He gives his new phone "
            "number when asked. He follows along as the agent checks each order. He's organized and "
            "cooperative. If the agent wraps everything into one clean summary at the end he responds "
            "positively ('perfect, that's all I needed'). He closes efficiently. 6-7 customer turns total."
        ),
    },
]

# ── Generation logic ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You generate verbatim customer turns for a customer service simulation experiment.
You output only a JSON array of objects: [{"role":"customer","text":"<turn>"},...]
No preamble, no explanation — only the JSON array. Nothing else."""

def build_user_prompt(s: dict) -> str:
    lines = [
        f"Customer: {s['name']} (ID: {s['customer_id']})",
        f"Session: Run {s['run']} of 3",
        f"Arc: {s['arc']}",
        "",
    ]
    if s.get("continuity_ctx"):
        lines += [
            "PRIOR CONTEXT (this customer has called before):",
            s["continuity_ctx"],
            "",
        ]
    lines += [
        "SCENARIO:",
        s["scenario"],
        "",
        "FIRST TURN — reproduce this VERBATIM as the first item in the array:",
        f'"{s["opening"]}"',
        "",
        "Generate the remaining customer turns following the scenario. Remember:",
        "- Only the customer's words — never write the agent.",
        "- The customer responds to what a competent but flawed customer service agent would say.",
        "  (The agent always verifies identity before each action — this is expected and normal.)",
        "- Do not invent order amounts, dates, or details not implied by the scenario.",
        "- Match the tone and pace described.",
        "- End naturally when the customer has what they need.",
        "",
        "Return ONLY the JSON array.",
    ]
    return "\n".join(lines)


def invoke_model(bedrock_client, prompt: str) -> list[dict]:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = bedrock_client.invoke_model(
        modelId=MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    raw = json.loads(response["body"].read())
    text = raw["content"][0]["text"].strip()
    # Strip markdown code fences if model adds them despite instructions.
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def build_record(s: dict, turns: list[dict], model_id: str) -> dict:
    record = {
        "customer_id": s["customer_id"],
        "name": s["name"],
        "run": s["run"],
        "arc": s["arc"],
        "session_label": s["session_label"],
        "opening_style": s["opening_style"],
        "expected_actions": s["expected_actions"],
        "discretionary_target": s["discretionary_target"],
        "tail_risk": s["tail_risk"],
        "turns": turns,
        "generation": {
            "protocol": "generate-once-freeze-replay",
            "model": model_id,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": f"scripts.md / {s['customer_id']} / Run {s['run']}",
        },
    }
    return record


def scenario_key(s: dict) -> str:
    return f"{s['customer_id']}_run{s['run']}"


def main():
    parser = argparse.ArgumentParser(description="Generate frozen customer transcripts.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling Bedrock.")
    parser.add_argument("--only", nargs="+", metavar="CUST-XXX_runN",
                        help="Generate only the listed transcripts (e.g. CUST-003_run2).")
    args = parser.parse_args()

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        if not OUTPUTS_FILE.exists():
            print("ERROR: infrastructure/cdk-outputs.json not found. Run cdk deploy first.")
            sys.exit(1)
        outputs = json.loads(OUTPUTS_FILE.read_text()).get(STACK_NAME, {})
        region = outputs.get("Region", "us-east-1")
        bedrock = boto3.client("bedrock-runtime", region_name=region)
    else:
        bedrock = None
        region = "us-east-1"

    target_keys = set(args.only) if args.only else None
    skipped = generated = 0

    for s in SCENARIOS:
        key = scenario_key(s)
        if target_keys and key not in target_keys:
            continue

        out_path = TRANSCRIPTS_DIR / f"{key}.json"
        if out_path.exists():
            print(f"  skip  {key}.json  (already exists)")
            skipped += 1
            continue

        prompt = build_user_prompt(s)

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"  {key}.json")
            print(f"{'='*60}")
            print(prompt)
            continue

        print(f"  gen   {key}.json ...", end="", flush=True)
        try:
            turns = invoke_model(bedrock, prompt)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue

        # Ensure first turn matches the prescribed opening exactly.
        if turns and turns[0].get("text") != s["opening"]:
            turns[0] = {"role": "customer", "text": s["opening"]}

        record = build_record(s, turns, MODEL_ID)
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f" {len(turns)} turns  →  {out_path.name}")
        generated += 1

    if not args.dry_run:
        print(f"\nDone. Generated: {generated}  Skipped: {skipped}")
        if generated + skipped < len(SCENARIOS):
            missing = len(SCENARIOS) - generated - skipped
            print(f"  {missing} scenario(s) not targeted — use --only or run again.")


if __name__ == "__main__":
    main()