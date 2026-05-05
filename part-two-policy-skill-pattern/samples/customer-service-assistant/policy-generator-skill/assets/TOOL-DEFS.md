# Gateway Tool Definitions

Tools registered on the AgentCore Gateway for this deployment. Use this file when
you need a capability that is not visible in your current toolset — consult it to
confirm the capability exists and to get the exact action name for a Cedar proposal.

If the capability you need is not listed here, stop and surface the situation to the
user. Do not propose a policy for a tool that is not in this registry.

---

## CustomerBasics

**Target:** `CustomerBasics`

| Tool | Action name | Proposal shape | Notes |
|------|-------------|----------------|-------|
| `get_customer_basics` | `CustomerBasics___get_customer_basics` | Permanent | Read-only. Returns name, tier, contact info. |

---

## OrderStatus

**Target:** `OrderStatus`

| Tool | Action name | Proposal shape | Notes |
|------|-------------|----------------|-------|
| `get_order_status` | `OrderStatus___get_order_status` | Permanent | Read-only. Returns order list and status for a customer. |

---

## CustomerEmail

**Target:** `CustomerEmail`

| Tool | Action name | Proposal shape | Notes |
|------|-------------|----------------|-------|
| `update_customer_email` | `CustomerEmail___update_customer_email` | Time-bounded (30 min) | PII write. Always time-bounded; never propose permanent. |
