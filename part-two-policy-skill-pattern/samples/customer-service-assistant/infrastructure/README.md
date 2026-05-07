# Infrastructure — CDK stack

Single AWS CDK (Python) stack deploying the enforcement layer and static data.

## What gets deployed

- DynamoDB table `policy-skill-customers` — Customer (id, first_name, last_name, email), seeded with two static rows
- DynamoDB table `policy-skill-orders` — Orders (order_id, customer_id, status), seeded with three static rows; GSI on customer_id
- Lambda `policy-skill-get-customer-basics` ([lambda/get_customer_basics.py](lambda/get_customer_basics.py))
- Lambda `policy-skill-get-order-status` ([lambda/get_order_status.py](lambda/get_order_status.py))
- Lambda `policy-skill-update-customer-email` ([lambda/update_customer_email.py](lambda/update_customer_email.py))
- IAM role `policy-skill-gateway-service-role` — trusts `bedrock-agentcore.amazonaws.com`. Inline policies grant `lambda:InvokeFunction` on all three Lambdas, plus `bedrock-agentcore:GetPolicyEngine`, `bedrock-agentcore:AuthorizeAction`, and `bedrock-agentcore:PartiallyAuthorizeActions`.
- AgentCore Policy Engine `policy_skill_engine` — Cedar, ENFORCE mode
- AgentCore Gateway `policy-skill-gateway` — `AuthorizerType=AWS_IAM`, `ProtocolType=MCP`, Policy Engine attached
- AgentCore Gateway Targets: `CustomerBasics`, `OrderStatus`, `CustomerEmail` — Lambda type, inline tool schemas from [tool-schema.json](tool-schema.json)

MCP tool names and Cedar action identifiers both use the triple-underscore convention:
`CustomerBasics___get_customer_basics`, `OrderStatus___get_order_status`, `CustomerEmail___update_customer_email`

## Prerequisites

- AWS account with AgentCore available (`us-east-1` is the default; set `CDK_DEFAULT_REGION` to override)
- AWS credentials with permission to deploy (Lambda, IAM, DynamoDB, `bedrock-agentcore:*Gateway*`, `bedrock-agentcore:*Policy*`)
- Python 3.10+ and Node 18+
- AWS CDK CLI: `npm install -g aws-cdk`

## One-time bootstrap

```sh
cdk bootstrap aws://<account-id>/us-east-1
```

## Deploy

Install dependencies from the **sample root** (`customer-service-assistant/`):

```sh
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
```

Then deploy from this directory (`infrastructure/`):

```sh
cd infrastructure
cdk deploy --outputs-file cdk-outputs.json
```

`cdk-outputs.json` lands in this directory and is consumed by [main.py](../main.py), [seed_policy.py](../seed_policy.py), and [cleanup.py](../cleanup.py) for infrastructure values (gateway URL/ARN, policy engine ID). It is gitignored.

## Cost

All resources use pay-per-request or on-demand pricing:
- **DynamoDB** — on-demand mode, pennies for a demo run
- **Lambda** — 3 functions, free tier covers demo usage
- **AgentCore Gateway + Policy Engine** — billed per authorization request; a demo run is single-digit requests
- **No ongoing cost when idle** — no provisioned capacity, no always-on compute

Teardown after demo use is still recommended.

## Teardown

```sh
cd infrastructure
cdk destroy
```

Removes everything the stack created: the Gateway, three Gateway Targets, Policy Engine, three Lambda functions, two DynamoDB tables, and IAM service role.

**What survives `cdk destroy`:**

- **Runtime-created Cedar policies** — created by the incorporator via `create_policy()`. These are deleted along with the Policy Engine (Policy Engines own their policies), so this is informational, not a leak.
- **`cdk-outputs.json`** — local file, not an AWS resource.
- **CDK bootstrap stack** (`CDKToolkit`) — shared across CDK deployments in the account/region; leave it alone.

**If `cdk destroy` fails:** most common cause is a resource modified out-of-band. Run `python cleanup.py` first to remove agent-created policies, then retry.
