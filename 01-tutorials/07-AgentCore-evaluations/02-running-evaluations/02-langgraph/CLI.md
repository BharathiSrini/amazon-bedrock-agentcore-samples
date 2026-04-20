# Running Evaluations with LangGraph Agents - CLI Guide

Learn how to run on-demand and online evaluations against a LangGraph agent deployed on AgentCore Runtime using the AgentCore CLI.

## What You'll Learn

- Invoking your LangGraph agent to generate traces
- Running on-demand evaluations against specific sessions or recent traces
- Setting up online evaluation for continuous production monitoring
- Viewing evaluation results and managing evaluation configurations

## Prerequisites

| Requirement | Details |
|---|---|
| Completed tutorial | [00-prereqs](../../00-prereqs/) — LangGraph agent deployed on AgentCore Runtime |
| Completed tutorial | [01-creating-custom-evaluators/CLI.md](../../01-creating-custom-evaluators/CLI.md) — custom evaluator added and deployed |
| CLI version | `agentcore --version` → `0.7.1+` |

Verify your LangGraph agent is deployed:

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  LangGraphAgent: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)

Evaluators
  ResponseQuality: Deployed (arn:aws:bedrock-agentcore:::evaluator/ResponseQuality_...)
```

> **Note:** The AgentCore CLI treats all agent frameworks identically — Strands, LangGraph, or any other. The evaluation commands are the same as the [Strands guide](../01-strands/CLI.md); only the `--runtime` name differs. This guide shows the complete workflow specifically for a LangGraph agent.

---

## Part 1: On-Demand Evaluation

On-demand evaluation lets you evaluate specific sessions or all recent traces at any time. It is the CLI equivalent of the `eval_client.run()` call in [`01-on-demand-eval.ipynb`](./01-on-demand-eval.ipynb).

### Step 1: Invoke the Agent to Generate Traces

Send the same three queries used in the notebooks — a weather question, a math question, and an out-of-scope question:

```bash
agentcore invoke "What is the weather now?" --runtime LangGraphAgent --stream
```

Expected output:
```
The current weather is partly cloudy with a temperature of 72°F...
```

```bash
agentcore invoke "How much is 2+2?" --runtime LangGraphAgent --stream
```

Expected output:
```
2 + 2 = 4
```

```bash
agentcore invoke "Can you tell me the capital of the US?" --runtime LangGraphAgent --stream
```

Expected output:
```
The capital of the United States is Washington, D.C.
```

> These queries test scope: weather and math are within scope for this agent, geography is not. The custom `ResponseQuality` evaluator will assign "Very Poor" to the out-of-scope response.

### Step 2: Find Your Session ID

List recent traces to retrieve the session ID:

```bash
agentcore traces list --runtime LangGraphAgent --limit 10 --since 15m
```

Expected output:
```
Traces for LangGraphAgent (target: default)

Trace ID                     Timestamp          Session ID
69d6f6e4450d6282682d9e0151de 2026-04-09         f9e8d7c6-b5a4-3210-fedc-ba9876543210
b786                         19:21:01Z

Console: https://us-east-1.console.aws.amazon.com/cloudwatch/...
Note: Traces may take 2-3 minutes to appear in CloudWatch
```

### Step 3: Run On-Demand Evaluation — Goal Success Rate

`Builtin.GoalSuccessRate` is a **session-level** evaluator that assesses whether user goals were met across the full conversation:

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.GoalSuccessRate \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210
```

Expected output:
```
Agent: LangGraphAgent | Apr 9, 2026, 07:21 PM | Sessions: 1 | Lookback: 7d

  Builtin.GoalSuccessRate: 0.75

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-21-01.json
```

For the full explanation in JSON:

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.GoalSuccessRate \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210 \
  --json
```

Expected output (abbreviated):
```json
{
  "success": true,
  "run": {
    "agent": "LangGraphAgent",
    "evaluators": ["Builtin.GoalSuccessRate"],
    "sessionCount": 1,
    "results": [
      {
        "evaluator": "Builtin.GoalSuccessRate",
        "aggregateScore": 0.75,
        "sessionScores": [
          {
            "sessionId": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
            "value": 0.75,
            "label": "Partially Successful",
            "explanation": "Two of the three user goals were successfully completed..."
          }
        ]
      }
    ]
  }
}
```

### Step 4: Run On-Demand Evaluation — Correctness (Trace Level)

`Builtin.Correctness` is a **trace-level** evaluator — each turn gets a score independently:

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.Correctness \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210
```

Expected output:
```
Agent: LangGraphAgent | Apr 9, 2026, 07:22 PM | Sessions: 1 | Lookback: 7d

  Builtin.Correctness: 0.83

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-22-15.json
```

### Step 5: Run On-Demand Evaluation — Tool Accuracy (Span Level)

`Builtin.ToolParameterAccuracy` and `Builtin.ToolSelectionAccuracy` are **span-level** evaluators — each tool call within a turn is scored:

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.ToolParameterAccuracy Builtin.ToolSelectionAccuracy \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210
```

Expected output:
```
Agent: LangGraphAgent | Apr 9, 2026, 07:23 PM | Sessions: 1 | Lookback: 7d

  Builtin.ToolParameterAccuracy: 1.00
  Builtin.ToolSelectionAccuracy: 1.00

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-23-40.json
```

### Step 6: Run On-Demand Evaluation — Custom Evaluator

Use your custom `ResponseQuality` evaluator to see the scope enforcement in action. The out-of-scope geography question scores "Very Poor":

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator ResponseQuality \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210 \
  --json
```

Expected output (abbreviated):
```json
{
  "success": true,
  "run": {
    "results": [
      {
        "evaluator": "ResponseQuality",
        "aggregateScore": 0.47,
        "sessionScores": [
          {
            "value": 1.0,
            "label": "Very Good",
            "explanation": "The weather response is accurate and within scope..."
          },
          {
            "value": 1.0,
            "label": "Very Good",
            "explanation": "2+2=4 is correct and within the agent's math scope..."
          },
          {
            "value": 0.0,
            "label": "Very Poor",
            "explanation": "The agent answered a geography question outside its scope of weather and math..."
          }
        ]
      }
    ]
  }
}
```

### Step 7: Evaluate All Recent Traces

To evaluate all traces across all sessions from the past week:

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.Correctness ResponseQuality \
  --lookback 7
```

### Step 8: Save Results to a File

```bash
agentcore run eval \
  --runtime LangGraphAgent \
  --evaluator Builtin.Correctness ResponseQuality \
  --session-id f9e8d7c6-b5a4-3210-fedc-ba9876543210 \
  --output evals_results/output.json
```

### View Evaluation History

```bash
agentcore evals history
```

Expected output:
```
On-Demand Eval History

  #  Timestamp             Agent           Evaluators
  -  --------------------  --------------  ----------------------------------------
  1  2026-04-09 19:23:40   LangGraphAgent  Builtin.Correctness, ResponseQuality
  2  2026-04-09 19:22:15   LangGraphAgent  Builtin.Correctness
  3  2026-04-09 19:21:01   LangGraphAgent  Builtin.GoalSuccessRate
```

---

## Part 2: Online Evaluation

Online evaluation runs automatically against live traffic. It is the CLI equivalent of `eval_client.create_online_config()` in [`02-online-eval.ipynb`](./02-online-eval.ipynb).

### Step 1: Add the Online Eval Config

```bash
agentcore add online-eval \
  --name LangGraphAgentEval \
  --runtime LangGraphAgent \
  --evaluator Builtin.GoalSuccessRate Builtin.Correctness Builtin.ToolParameterAccuracy Builtin.ToolSelectionAccuracy ResponseQuality \
  --sampling-rate 100 \
  --enable-on-create
```

Expected output:
```json
{"success":true,"configName":"LangGraphAgentEval"}
```

Verify:

```bash
agentcore status
```

Expected output:
```
Online Eval Configs
  LangGraphAgentEval: Local only (5 evaluators, 100% sampling)
```

### Step 2: Deploy to Activate

```bash
agentcore deploy
```

Expected output:
```
[done]  Load deployment target
[done]  Validate project
[done]  Build CDK project
[done]  Synthesize CloudFormation
[done]  Deploy stack

Deployment complete for 'default' (stack: AgentCore-LangGraphAgent-default)
```

After deploy:
```
Online Eval Configs
  LangGraphAgentEval: Deployed - ENABLED (5 evaluators, 100% sampling)
```

### Step 3: Invoke the Agent to Trigger Evaluation

```bash
agentcore invoke "How much is 7+9+10*2?" --runtime LangGraphAgent --stream
agentcore invoke "Is it raining?" --runtime LangGraphAgent --stream
agentcore invoke "how much is 20% of 300?" --runtime LangGraphAgent --stream
agentcore invoke "What can you do?" --runtime LangGraphAgent --stream
agentcore invoke "What is the capital of NY State?" --runtime LangGraphAgent --stream
```

The online evaluation processes these traces automatically in the background.

### Step 4: View Online Eval Logs

```bash
agentcore logs evals --runtime LangGraphAgent --follow
```

Expected output (once eval results arrive, ~2-3 minutes after invocations):
```
2026-04-09T19:35:12Z  {"evaluator":"Builtin.Correctness","score":1.0,"label":"Perfectly Correct","sessionId":"b5c6d7e8-..."}
2026-04-09T19:35:15Z  {"evaluator":"Builtin.GoalSuccessRate","score":0.8,"label":"Mostly Successful","sessionId":"b5c6d7e8-..."}
2026-04-09T19:35:18Z  {"evaluator":"ResponseQuality","score":0.0,"label":"Very Poor","sessionId":"b5c6d7e8-..."}
```

Search historical eval logs:

```bash
agentcore logs evals --runtime LangGraphAgent --since 30m --limit 20
```

### Step 5: Visualize in CloudWatch

```bash
agentcore traces list --runtime LangGraphAgent --limit 10
```

Use the console link in the output to navigate to the AgentCore Observability dashboard, then select the **Evaluations** tab to view aggregated scores over time.

### Pause and Resume Online Evaluation

```bash
agentcore pause online-eval LangGraphAgentEval
```

```bash
agentcore resume online-eval LangGraphAgentEval
```

---

## Clean Up

```bash
agentcore remove online-eval --name LangGraphAgentEval --yes
agentcore deploy
```

---

## Evaluation Level Reference

| Evaluator | Level | What It Scores |
|---|---|---|
| `Builtin.GoalSuccessRate` | SESSION | Were all user goals met across the conversation? |
| `Builtin.Correctness` | TRACE | Is each individual response factually correct? |
| `Builtin.ToolParameterAccuracy` | TOOL_CALL | Were tool parameters extracted correctly? |
| `Builtin.ToolSelectionAccuracy` | TOOL_CALL | Was the right tool chosen for each task? |
| `ResponseQuality` (custom) | TRACE | Does the response stay in scope and is it accurate? |

---

## Python SDK Equivalent

| CLI command | Python SDK equivalent |
|---|---|
| `agentcore run eval --evaluator Builtin.GoalSuccessRate --session-id ...` | `eval_client.run(agent_id=..., session_id=..., evaluators=["Builtin.GoalSuccessRate"])` |
| `agentcore run eval --evaluator Builtin.Correctness ...` | `eval_client.run(agent_id=..., session_id=..., evaluators=["Builtin.Correctness"])` |
| `agentcore run eval --output evals_results/output.json` | `eval_client.run(..., output="evals_results/output.json")` |
| `agentcore add online-eval` + `agentcore deploy` | `eval_client.create_online_config(agent_id=..., config_name=..., evaluator_list=[...])` |

For the Python SDK approach, see [`01-on-demand-eval.ipynb`](./01-on-demand-eval.ipynb) and [`02-online-eval.ipynb`](./02-online-eval.ipynb).

## What's Next

- [Strands evaluation](../01-strands/CLI.md) — same workflow for a Strands agent
- [Advanced evaluations](../../03-advanced/) — boto3 SDK patterns and custom CloudWatch dashboards
