# Running Evaluations with Strands Agents - CLI Guide

Learn how to run on-demand and online evaluations against a Strands agent deployed on AgentCore Runtime using the AgentCore CLI.

## What You'll Learn

- Invoking your Strands agent to generate traces
- Running on-demand evaluations against specific sessions or recent traces
- Setting up online evaluation for continuous production monitoring
- Viewing evaluation results and managing evaluation configurations

## Prerequisites

| Requirement | Details |
|---|---|
| Completed tutorial | [00-prereqs](../../00-prereqs/) — Strands agent deployed on AgentCore Runtime |
| Completed tutorial | [01-creating-custom-evaluators/CLI.md](../../01-creating-custom-evaluators/CLI.md) — custom evaluator added and deployed |
| CLI version | `agentcore --version` → `0.7.1+` |

Verify your Strands agent is deployed:

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

Agents
  StrandsAgent: Deployed - Runtime: READY (arn:aws:bedrock-agentcore:...)

Evaluators
  ResponseQuality: Deployed (arn:aws:bedrock-agentcore:::evaluator/ResponseQuality_...)
```

---

## Part 1: On-Demand Evaluation

On-demand evaluation lets you evaluate specific sessions or all recent traces at any time. It's the CLI equivalent of the `eval_client.run()` call in [`01-on-demand-eval.ipynb`](./01-on-demand-eval.ipynb).

### Step 1: Invoke the Agent to Generate Traces

Send a few queries to your agent to create sessions with traces. The notebooks use three questions — a weather question, a math question, and an out-of-scope question — to demonstrate scope enforcement:

```bash
agentcore invoke "What is the weather now?" --runtime StrandsAgent --stream
```

Expected output:
```
The current weather in your location is partly cloudy with a temperature of 72°F...
```

```bash
agentcore invoke "How much is 2+2?" --runtime StrandsAgent --stream
```

Expected output:
```
2 + 2 = 4
```

```bash
agentcore invoke "Can you tell me the capital of the US?" --runtime StrandsAgent --stream
```

Expected output:
```
The capital of the United States is Washington, D.C.
```

> These three queries test the agent's scope: the first two are within scope (weather and math), and the third is out of scope. Your custom `ResponseQuality` evaluator will score the third response as "Very Poor" because the instructions penalize answers outside the agent's original scope.

### Step 2: Find Your Session ID

List recent traces to get the session ID for the interactions above:

```bash
agentcore traces list --runtime StrandsAgent --limit 10 --since 15m
```

Expected output:
```
Traces for StrandsAgent (target: default)

Trace ID                     Timestamp          Session ID
69d6f6e4450d6282682d9e0151de 2026-04-09         a1b2c3d4-e5f6-7890-abcd-ef1234567890
b786                         19:21:01Z

Console: https://us-east-1.console.aws.amazon.com/cloudwatch/...
Note: Traces may take 2-3 minutes to appear in CloudWatch
```

If your three queries used the same session, they will share one session ID. Note the session ID for use in the next steps.

### Step 3: Run On-Demand Evaluation — Goal Success Rate

Evaluate the full session with `Builtin.GoalSuccessRate`. This is a **session-level** evaluator that assesses whether the user's overall goals were met across all turns:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.GoalSuccessRate \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Expected output:
```
Agent: StrandsAgent | Apr 9, 2026, 07:21 PM | Sessions: 1 | Lookback: 7d

  Builtin.GoalSuccessRate: 0.75

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-21-01.json
```

For a detailed JSON response including the explanation:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.GoalSuccessRate \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --json
```

Expected output (abbreviated):
```json
{
  "success": true,
  "run": {
    "agent": "StrandsAgent",
    "evaluators": ["Builtin.GoalSuccessRate"],
    "sessionCount": 1,
    "results": [
      {
        "evaluator": "Builtin.GoalSuccessRate",
        "aggregateScore": 0.75,
        "sessionScores": [
          {
            "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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

`Builtin.Correctness` is a **trace-level** evaluator — each individual turn gets its own score:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.Correctness \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Expected output:
```
Agent: StrandsAgent | Apr 9, 2026, 07:22 PM | Sessions: 1 | Lookback: 7d

  Builtin.Correctness: 0.83

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-22-15.json
```

### Step 5: Run On-Demand Evaluation — Tool Accuracy (Span Level)

`Builtin.ToolParameterAccuracy` and `Builtin.ToolSelectionAccuracy` are **span-level** evaluators — each tool call gets its own score. Run both in a single command:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.ToolParameterAccuracy Builtin.ToolSelectionAccuracy \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Expected output:
```
Agent: StrandsAgent | Apr 9, 2026, 07:23 PM | Sessions: 1 | Lookback: 7d

  Builtin.ToolParameterAccuracy: 1.00
  Builtin.ToolSelectionAccuracy: 1.00

Results saved to: agentcore/.cli/eval-results/eval_2026-04-09_19-23-40.json
```

### Step 6: Run On-Demand Evaluation — Custom Evaluator

Use your custom `ResponseQuality` evaluator to see per-trace scope enforcement scores. The out-of-scope question (capital of the US) should score "Very Poor":

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator ResponseQuality \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
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

### Step 7: Evaluate All Recent Traces (No Session ID)

To evaluate all recent traces without specifying a session ID, use `--lookback`:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.Correctness ResponseQuality \
  --lookback 7
```

→ Evaluates all traces from the last 7 days across all sessions.

### Step 8: Save Results to a File

Use `--output` to save results to a specific path:

```bash
agentcore run eval \
  --runtime StrandsAgent \
  --evaluator Builtin.Correctness ResponseQuality \
  --session-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --output evals_results/output.json
```

→ Saves full results to `evals_results/output.json` in addition to the default local log.

### View Evaluation History

```bash
agentcore evals history
```

Expected output:
```
On-Demand Eval History

  #  Timestamp             Agent         Evaluators
  -  --------------------  ------------  ----------------------------------------
  1  2026-04-09 19:23:40   StrandsAgent  Builtin.Correctness, ResponseQuality
  2  2026-04-09 19:22:15   StrandsAgent  Builtin.Correctness
  3  2026-04-09 19:21:01   StrandsAgent  Builtin.GoalSuccessRate
```

---

## Part 2: Online Evaluation

Online evaluation runs automatically against live traffic as your agent is invoked. It is the CLI equivalent of `eval_client.create_online_config()` in [`02-online-eval.ipynb`](./02-online-eval.ipynb).

### Step 1: Add the Online Eval Config

Add an online evaluation config that monitors your Strands agent with all five evaluators used in the notebook — three built-in and two project evaluators:

```bash
agentcore add online-eval \
  --name StrandsAgentEval \
  --runtime StrandsAgent \
  --evaluator Builtin.GoalSuccessRate Builtin.Correctness Builtin.ToolParameterAccuracy Builtin.ToolSelectionAccuracy ResponseQuality \
  --sampling-rate 100 \
  --enable-on-create
```

Expected output:
```json
{"success":true,"configName":"StrandsAgentEval"}
```

`--sampling-rate 100` evaluates every session. For production use, set a lower value (e.g., `10` for 10% of sessions).

Verify the config was added:

```bash
agentcore status
```

Expected output:
```
AgentCore Status (target: default, us-east-1)

...

Online Eval Configs
  StrandsAgentEval: Local only (5 evaluators, 100% sampling)
```

### Step 2: Deploy to Activate

Deploy to register and enable the online eval configuration in AWS:

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

Deployment complete for 'default' (stack: AgentCore-StrandsAgent-default)
```

After deploy, the config is active and will evaluate new sessions automatically:

```bash
agentcore status
```

Expected output:
```
Online Eval Configs
  StrandsAgentEval: Deployed - ENABLED (5 evaluators, 100% sampling)
```

### Step 3: Invoke the Agent to Trigger Evaluation

Send new queries — the online eval config will automatically evaluate them:

```bash
agentcore invoke "How much is 7+9+10*2?" --runtime StrandsAgent --stream
agentcore invoke "Is it raining?" --runtime StrandsAgent --stream
agentcore invoke "how much is 20% of 300?" --runtime StrandsAgent --stream
agentcore invoke "What can you do?" --runtime StrandsAgent --stream
agentcore invoke "What is the capital of NY State?" --runtime StrandsAgent --stream
```

No additional steps needed — the online evaluation processes the traces in the background automatically.

### Step 4: View Online Eval Logs

Stream online evaluation results as they arrive:

```bash
agentcore logs evals --runtime StrandsAgent --follow
```

Expected output (once eval results arrive, ~2-3 minutes after invocations):
```
2026-04-09T19:35:12Z  {"evaluator":"Builtin.Correctness","score":1.0,"label":"Perfectly Correct","sessionId":"b5c6d7e8-..."}
2026-04-09T19:35:15Z  {"evaluator":"Builtin.GoalSuccessRate","score":0.8,"label":"Mostly Successful","sessionId":"b5c6d7e8-..."}
2026-04-09T19:35:18Z  {"evaluator":"ResponseQuality","score":0.0,"label":"Very Poor","sessionId":"b5c6d7e8-..."}
```

> **Note:** Evaluation results may take 2–5 minutes to appear in CloudWatch after the agent is invoked.

Search recent eval logs instead of streaming:

```bash
agentcore logs evals --runtime StrandsAgent --since 30m --limit 20
```

### Step 5: Visualize in CloudWatch

Once results are available, open the AgentCore Observability console to view dashboards with aggregated scores and trends:

```bash
agentcore traces list --runtime StrandsAgent --limit 10
```

The output includes a direct CloudWatch console link to the GenAI Observability dashboard for your agent. Navigate to the `DEFAULT` endpoint and select the **Evaluations** tab to see scores plotted over time.

### Pause and Resume Online Evaluation

Temporarily pause evaluation (e.g., during maintenance):

```bash
agentcore pause online-eval StrandsAgentEval
```

Expected output:
```
Paused online eval config 'StrandsAgentEval'
```

Resume when ready:

```bash
agentcore resume online-eval StrandsAgentEval
```

Expected output:
```
Resumed online eval config 'StrandsAgentEval'
```

---

## Clean Up

Remove the online eval config and redeploy to stop the continuous evaluation:

```bash
agentcore remove online-eval --name StrandsAgentEval --yes
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

The CLI commands in this tutorial map to the following Starter Toolkit calls:

| CLI command | Python SDK equivalent |
|---|---|
| `agentcore run eval --evaluator Builtin.GoalSuccessRate --session-id ...` | `eval_client.run(agent_id=..., session_id=..., evaluators=["Builtin.GoalSuccessRate"])` |
| `agentcore run eval --evaluator Builtin.Correctness ...` | `eval_client.run(agent_id=..., session_id=..., evaluators=["Builtin.Correctness"])` |
| `agentcore run eval --output evals_results/output.json` | `eval_client.run(..., output="evals_results/output.json")` |
| `agentcore add online-eval` + `agentcore deploy` | `eval_client.create_online_config(agent_id=..., config_name=..., evaluator_list=[...])` |

For the Python SDK approach, see [`01-on-demand-eval.ipynb`](./01-on-demand-eval.ipynb) and [`02-online-eval.ipynb`](./02-online-eval.ipynb).

## What's Next

- [LangGraph evaluation](../02-langgraph/CLI.md) — same evaluation workflow for a LangGraph agent
- [Advanced evaluations](../../03-advanced/) — boto3 SDK patterns and custom CloudWatch dashboards
