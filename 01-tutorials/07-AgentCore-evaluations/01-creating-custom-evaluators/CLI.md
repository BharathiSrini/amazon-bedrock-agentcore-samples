# AgentCore Evaluations - Creating Evaluators with the CLI

Learn about AgentCore Evaluations built-in and custom metrics, and how to create custom evaluators using the AgentCore CLI.

## What You'll Learn

- Understanding built-in evaluators and their use cases
- Creating custom evaluators with CLI flags and config files
- Monitoring agents continuously with online evaluation
- Running on-demand evaluations against deployed agents

## Prerequisites

| Requirement | Minimum Version | Install |
|---|---|---|
| Node.js | 20.x | [nodejs.org](https://nodejs.org/) |
| AWS CLI | 2.x | [AWS CLI install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |

### Install the AgentCore CLI

```bash
npm install -g @aws/agentcore
agentcore --version
```

Expected output:
```
0.7.1
```

### Configure AWS credentials

```bash
aws configure
```

### Set up a project

This tutorial assumes you have an AgentCore project with a deployed runtime. If you don't have one yet, follow the [Getting Started guide](../../../00-getting-started/README.md) first to create and deploy an agent, then return here.

```bash
cd <your-project-directory>
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  CustomerSupport: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)
```

---

## Evaluator Types

### Built-in Evaluators

AgentCore provides 13 pre-configured evaluators that use LLMs as judges. They are ready to use with no configuration required.

| Category | Evaluator ID | What It Measures |
|---|---|---|
| Response quality | `Builtin.Correctness` | Factual accuracy of the response |
| Response quality | `Builtin.Faithfulness` | Whether response is grounded in provided context |
| Response quality | `Builtin.Helpfulness` | Usefulness of the response from the user's perspective |
| Response quality | `Builtin.ResponseRelevance` | How well the response addresses the user's query |
| Response quality | `Builtin.Conciseness` | Appropriate brevity without missing key information |
| Response quality | `Builtin.Coherence` | Logical structure and consistency |
| Response quality | `Builtin.InstructionFollowing` | Adherence to system instructions |
| Response quality | `Builtin.Refusal` | Whether the agent evades or refuses questions |
| Task completion | `Builtin.GoalSuccessRate` | Whether user goals were achieved across the session |
| Tool level | `Builtin.ToolSelectionAccuracy` | Whether the agent chose the right tool |
| Tool level | `Builtin.ToolParameterAccuracy` | Accuracy of tool parameter extraction |
| Safety | `Builtin.Harmfulness` | Presence of harmful content |
| Safety | `Builtin.Stereotyping` | Generalizations about individuals or groups |

Built-in evaluator configurations cannot be modified, which ensures consistent and reliable assessments. You can, however, use them as a starting point for custom evaluators.

### Custom Evaluators

Custom evaluators let you control the judge model, evaluation instructions, and scoring scale. Use them when:

- You have domain-specific requirements (healthcare, finance, legal)
- You need specialized scoring aligned with organizational KPIs
- Built-in evaluators don't capture the dimension you care about

---

## Step 1: Add a Custom Evaluator with CLI Flags (~2 min)

The `agentcore add evaluator` command registers a custom evaluator in your project config. Use the `--level` flag to set the scope:

- **`TRACE`** — evaluates one user-agent interaction (a single turn)
- **`SESSION`** — evaluates the full multi-turn conversation
- **`TOOL_CALL`** — evaluates individual tool invocations within a turn

Add a trace-level response quality evaluator using a built-in rating scale preset:

```bash
agentcore add evaluator \
  --name ResponseQuality \
  --level TRACE \
  --type llm-as-a-judge \
  --model "global.anthropic.claude-haiku-4-5-20251001-v1:0" \
  --instructions "You are evaluating the quality of the Assistant's response. Is this a good and accurate response to the task?\n\nContext: {context}\nCandidate Response: {assistant_turn}" \
  --rating-scale 1-5-quality
```

Expected output:
```json
{"success":true,"evaluatorName":"ResponseQuality"}
```

The `--rating-scale` preset options are:

| Preset | Scale |
|---|---|
| `1-5-quality` | Poor / Fair / Good / Very Good / Excellent (1–5) |
| `1-3-simple` | Low / Medium / High (1–3) |
| `pass-fail` | Fail / Pass (0–1) |
| `good-neutral-bad` | Bad / Neutral / Good (0–0.5–1) |

### Prompt placeholders by level

Your `--instructions` must include placeholders appropriate for the evaluator level:

| Level | Required placeholders | Optional placeholders |
|---|---|---|
| `TRACE` | `{context}`, `{assistant_turn}` | — |
| `SESSION` | `{context}` | `{available_tools}` |
| `TOOL_CALL` | `{context}` | `{tool_name}`, `{tool_input}`, `{tool_output}` |

---

## Step 2: Add a Custom Evaluator from a Config File (~2 min)

For more control — including a custom 5-level rating scale — use a JSON config file with the `--config` flag. This is equivalent to what the Python SDK's `create_evaluator()` method accepts.

A sample config file is provided in this directory: [`metric_cli.json`](./metric_cli.json). It defines a 5-point "Very Good to Very Poor" quality scale with scope enforcement in the instructions.

```bash
agentcore add evaluator \
  --name ResponseQualityDetailed \
  --level TRACE \
  --config metric_cli.json
```

Expected output:
```json
{"success":true,"evaluatorName":"ResponseQualityDetailed"}
```

### Config file format

```json
{
  "llmAsAJudge": {
    "model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "instructions": "Your evaluation prompt with {context} and {assistant_turn} placeholders...",
    "ratingScale": {
      "numerical": [
        { "value": 5, "label": "Very Good",  "definition": "Completely accurate." },
        { "value": 4, "label": "Good",        "definition": "Mostly accurate." },
        { "value": 3, "label": "OK",          "definition": "Partially correct." },
        { "value": 2, "label": "Poor",        "definition": "Mostly incorrect." },
        { "value": 1, "label": "Very Poor",   "definition": "Completely wrong." }
      ]
    }
  }
}
```

> Rating scale values must be integers. For categorical (pass/fail) scales, use `"categorical"` instead of `"numerical"` with `"label"` and `"definition"` fields.

---

## Step 3: Validate and Review Your Project Config (~1 min)

Validate the project config before deploying:

```bash
agentcore validate
```

Expected output:
```
Valid
```

Check the current status of your evaluators. Before deploying, they appear as "Local only":

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  CustomerSupport: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)

Evaluators
  ResponseQuality: Local only (TRACE — LLM-as-a-Judge)
  ResponseQualityDetailed: Local only (TRACE — LLM-as-a-Judge)
```

---

## Step 4: Add Online Evaluation Monitoring (~1 min)

Online evaluations run automatically on a sample of live traffic, without any manual triggering. Add an online eval config that monitors your agent using both a built-in and your custom evaluator:

```bash
agentcore add online-eval \
  --name QualityMonitor \
  --runtime CustomerSupport \
  --evaluator Builtin.GoalSuccessRate ResponseQuality \
  --sampling-rate 100 \
  --enable-on-create
```

Expected output:
```json
{"success":true,"configName":"QualityMonitor"}
```

`--sampling-rate 100` evaluates every session. Use a lower percentage (e.g., `10`) in production to reduce cost. `--enable-on-create` activates the config immediately after deploy.

Check the updated status:

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  CustomerSupport: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)

Evaluators
  ResponseQuality: Local only (TRACE — LLM-as-a-Judge)
  ResponseQualityDetailed: Local only (TRACE — LLM-as-a-Judge)

Online Eval Configs
  QualityMonitor: Local only (2 evaluators, 100% sampling)
```

---

## Step 5: Deploy Your Evaluators (~3 min)

Deploy to register your evaluators and activate the online eval config in AWS:

```bash
agentcore deploy
```

Expected output:
```
[done]  Load deployment target
[done]  Validate project
[done]  Build CDK project
[done]  Synthesize CloudFormation
[done]  Check bootstrap status
[done]  Check stack status
[done]  Deploy stack

Deployment complete for 'default' (stack: AgentCore-CustomerSupport-default)
```

After deploy, `agentcore status` shows the evaluators with their registered ARNs:

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  CustomerSupport: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)

Evaluators
  ResponseQuality: Deployed (arn:aws:bedrock-agentcore:::evaluator/ResponseQuality_...)
  ResponseQualityDetailed: Deployed (arn:aws:bedrock-agentcore:::evaluator/ResponseQualityDetailed_...)

Online Eval Configs
  QualityMonitor: Deployed - ENABLED (2 evaluators, 100% sampling)
```

> **Preview before deploying:** Run `agentcore deploy --dry-run` to validate and synthesize CloudFormation without making changes. Run `agentcore deploy --diff` to see the exact resource changes.

---

## Step 6: Run On-Demand Evaluations (~2 min)

On-demand evaluations let you evaluate existing agent traces from CloudWatch at any time. Run an evaluation against the last 7 days of traces using a built-in evaluator:

```bash
agentcore run eval \
  --runtime CustomerSupport \
  --evaluator Builtin.Correctness \
  --lookback 7
```

To evaluate with your custom evaluator (after it's deployed):

```bash
agentcore run eval \
  --runtime CustomerSupport \
  --evaluator Builtin.Correctness ResponseQuality \
  --lookback 7
```

Expected output:
```
Agent: CustomerSupport | Apr 9, 2026, 12:13 PM | Sessions: 33 | Lookback: 7d

  Builtin.Correctness: 0.95
  ResponseQuality: 0.88

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_12-13-16.json
```

### Evaluate a specific session

If you want to evaluate a single session rather than all recent traces:

```bash
agentcore run eval \
  --runtime CustomerSupport \
  --evaluator Builtin.Correctness \
  --session-id <session-id>
```

### Evaluate with ground truth

For ground-truth-based evaluation, you can provide assertions and expected responses:

```bash
agentcore run eval \
  --runtime CustomerSupport \
  --evaluator Builtin.Correctness \
  --session-id <session-id> \
  --assertion "The agent correctly looked up the return policy" \
  --assertion "The agent did not hallucinate product details" \
  --expected-response "Electronics have a 30-day return window"
```

---

## Step 7: View Evaluation History

View past on-demand evaluation runs saved locally:

```bash
agentcore evals history
```

Expected output after running evaluations:
```
On-Demand Eval History

  #  Timestamp             Agent           Evaluators
  -  --------------------  --------------  ----------------------------------------
  1  2026-04-09 12:13:16   CustomerSupport  Builtin.Correctness, ResponseQuality
  2  2026-04-09 11:45:02   CustomerSupport  Builtin.GoalSuccessRate
```

---

## What's in agentcore.json?

The `agentcore add evaluator` and `agentcore add online-eval` commands update `agentcore/agentcore.json`. Here's what the evaluator entries look like:

```json
{
  "evaluators": [
    {
      "name": "ResponseQuality",
      "level": "TRACE",
      "config": {
        "llmAsAJudge": {
          "model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
          "instructions": "...",
          "ratingScale": {
            "numerical": [
              { "value": 1, "label": "Poor",      "definition": "Fails to meet expectations" },
              { "value": 2, "label": "Fair",       "definition": "Partially meets expectations" },
              { "value": 3, "label": "Good",       "definition": "Meets expectations" },
              { "value": 4, "label": "Very Good",  "definition": "Exceeds expectations" },
              { "value": 5, "label": "Excellent",  "definition": "Far exceeds expectations" }
            ]
          }
        }
      }
    }
  ],
  "onlineEvalConfigs": [
    {
      "type": "OnlineEvaluationConfig",
      "name": "QualityMonitor",
      "agent": "CustomerSupport",
      "evaluators": [
        "arn:aws:bedrock-agentcore:::evaluator/Builtin.GoalSuccessRate",
        "ResponseQuality"
      ],
      "samplingRate": 100,
      "enableOnCreate": true
    }
  ]
}
```

You can edit this file directly instead of using CLI commands.

---

## Clean Up

Remove evaluators from your project config:

```bash
# Remove the online eval config first (evaluators referenced by configs cannot be removed)
agentcore remove online-eval --name QualityMonitor --yes

# Then remove the evaluators
agentcore remove evaluator --name ResponseQualityDetailed --yes
agentcore remove evaluator --name ResponseQuality --yes
```

Expected output:
```json
{"success":true,"resourceType":"online-eval","resourceName":"QualityMonitor","message":"Removed online eval config 'QualityMonitor'","note":"Deploy with `agentcore deploy` to apply your removal changes to AWS."}
{"success":true,"resourceType":"evaluator","resourceName":"ResponseQualityDetailed","message":"Removed evaluator 'ResponseQualityDetailed'","note":"Deploy with `agentcore deploy` to apply your removal changes to AWS."}
{"success":true,"resourceType":"evaluator","resourceName":"ResponseQuality","message":"Removed evaluator 'ResponseQuality'","note":"Deploy with `agentcore deploy` to apply your removal changes to AWS."}
```

Then redeploy to remove the resources from AWS:

```bash
agentcore deploy
```

---

## What's Next?

You now know how to create evaluators and monitor agent quality. Here are the next steps:

| Tutorial | What You'll Learn |
|---|---|
| [Running Evaluations](../02-running-evaluations/) | Run batch evaluations across session history |
| [Using Evaluation Results](../04-using-evaluation-results/) | Interpret scores and drive improvements |
| [Ground Truth Evaluations](../05-groundtruth-based-evalautions/) | Evaluate against labeled expected outputs |
| [Programmatic Evaluators](../06-programmatic_evaluators/) | Create code-based evaluators using Lambda |

### Python SDK equivalent

The CLI commands in this tutorial map to the following AgentCore Starter Toolkit methods:

| CLI command | Python SDK equivalent |
|---|---|
| `agentcore add evaluator` | `Evaluation(region).create_evaluator(name, level, config)` |
| `agentcore run eval` | `EvaluationClient().evaluate(...)` |
| Built-in evaluator IDs | `Evaluation(region).list_evaluators()` |
| Get evaluator details | `Evaluation(region).get_evaluator(evaluator_id)` |

For the Python SDK approach, see [`01-agentcore-evaluators.ipynb`](./01-agentcore-evaluators.ipynb).

### Useful resources

- [AgentCore CLI documentation](https://github.com/aws/agentcore-cli)
- [Amazon Bedrock AgentCore documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AgentCore Python SDK](https://github.com/aws/bedrock-agentcore-sdk-python)
