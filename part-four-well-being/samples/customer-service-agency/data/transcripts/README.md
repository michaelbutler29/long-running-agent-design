# Template Transcripts — Archetype Design

10 template files (`A01.json` through `A10.json`) plus one cosmetic variation table (`cosmetics.json`). Together they produce 100 realized transcripts (10 archetypes × 10 runs) with constant task structure and cosmetic-only variation.

## How it works

1. Each `A{NN}.json` defines one archetypal customer-service scenario: turn structure, emotional beats, expected actions, discretionary target, dropped mention, tail-risk tag. Turn text contains `{{placeholder}}` tokens.
2. `cosmetics.json` maps `(archetype, run)` to concrete values — customer ID, name, order ID, product names, etc.
3. At load time, `load_transcript(archetype, run)` reads the template, substitutes all `{{key}}` tokens from the cosmetics entry, and returns a fully realized transcript.

## What's constant across runs (by construction)

- Number of turns and their sentence structure
- Emotional tone and customer posture
- Opening style (upfront vs. standard)
- Required actions and redundant verify call count
- Whether a dropped mention or tail-risk tag is present
- Discretionary opportunity category

## What varies per run (cosmetic only)

- Customer ID (CUST-1xx through CUST-10xx)
- Customer name
- Order ID(s)
- Product names and prices
- Specific values in dropped mentions (phone numbers, email addresses)

## Session order

Fixed: A01 through A10 in order, every run, every experiment. No shuffling.

## Schema

```jsonc
{
  "archetype": "A01",
  "session_label": "Frustrated order inquiry",
  "opening_style": "upfront",
  "expected_actions": ["get_customer", "get_order"],
  "discretionary_target": "Proactively surface status of customer's other pending order",
  "tail_risk": null,
  "dropped_mention": null,
  "turns": [
    {"role": "customer", "text": "Hi, I got the wrong item in my order {{order_id}}..."},
    ...
  ]
}
```

After load-time substitution, additional fields are injected: `customer_id`, `name`, `run`, `arc`.

### `tail_risk` object (tagged sessions only)

```jsonc
"tail_risk": {
  "id": "TR-A05",
  "shape": "active_mishandling",
  "check": "Was check_refund_eligibility called before process_refund?"
}
```

Tagged archetypes: TR-A05 (active mishandling), TR-A10 (silent omission). Both repeat every run.

### `dropped_mention` object

```jsonc
"dropped_mention": {"field": "phone"}
```

5 archetypes carry dropped mentions: A03 (phone, through-line), A04 (email), A07 (phone), A08 (phone), A09 (email).
