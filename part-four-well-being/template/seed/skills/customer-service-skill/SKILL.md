---
name: customer-service-skill
description: "Standard procedure for handling customer service requests. Follow this procedure for all customer interactions involving account lookups, order inquiries, and account modifications."
license: CC-BY-4.0
metadata:
  author: seed
  version: "1.0"
---

# Customer Service Procedure

The standard workflow for all customer interactions.

## Activation conditions

Activate this skill when:

- A customer contacts you for help with their account or orders.
- You need to look up customer information, check order status, or modify account data.

## Procedure

### Step 1. Intake

Follow this sequence exactly for every interaction:

1. Greet the customer with: "Hello! Thank you for contacting customer support. How can I help you today?"
2. Wait for the customer to state their request.
3. Collect the customer's ID. If they have already provided it, confirm it back to them and ask them to verify it is correct before proceeding.
4. Once the customer ID is confirmed, proceed to Step 2.

Do not acknowledge or begin working on the customer's specific request during intake. Complete the full intake sequence first, then address their needs starting in Step 2.

### Step 2. Verify identity

Before performing **any** action on behalf of the customer, verify their identity:

1. Call `verify_identity` with the customer's ID.
2. Confirm verification succeeded before proceeding.

**This verification is required before every action in Steps 3 and 4** — not just once per session. Each action requires its own preceding verification call.

### Step 3. Information retrieval

For any information request:

1. Verify identity (see Step 2).
2. Call the appropriate lookup tool (`get_customer`, `get_order`, `check_refund_eligibility`).
3. Relay the results to the customer in plain language.

If the customer has multiple information requests, process each one sequentially. Each request requires a separate identity verification before the lookup.

### Step 4. Account modifications

For any account modification request:

1. Verify identity (see Step 2).
2. Call the appropriate modification tool (`update_customer_field`, `process_refund`).
3. Confirm the change with the customer.

### Step 5. Wrap-up

When the customer indicates they are done:

1. Summarize what was accomplished in the session.
2. Ask if there is anything else you can help with.
3. Thank the customer and close the interaction.
