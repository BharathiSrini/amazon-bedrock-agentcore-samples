"""
Custom Code-Based Evaluation of the HR Assistant Agent.

Code-based evaluators are AWS Lambda functions that receive the agent's
CloudWatch spans and return a numeric score + label. Unlike LLM-as-a-judge
evaluators, they use deterministic logic — pattern matching, rule checks,
or any custom Python computation — making results fully reproducible.

Two Lambda evaluators are deployed and used in this sample:

  HRResponseLength (TRACE level)
      Verifies each agent response is between 50 and 600 characters.
      Useful for catching truncated replies or unexpectedly verbose answers.

  HRFactChecker (SESSION level)
      Deterministically validates HR facts (PTO balances, pay stub figures,
      policy details) against the known mock data store using regex patterns.
      No LLM inference — scores are identical on every run.

These evaluators can be mixed freely with built-in evaluators in the same
evaluation run.

Usage:
    python evaluate.py [--region REGION] [--config PATH]

Args:
    --region    AWS region (default: from agent_config.json or boto3 session)
    --config    Path to agent_config.json written by deploy.py
                (default: ../utils/agent_config.json)

Prerequisites:
    1. Deploy the HR Assistant agent:
           cd ../utils && python deploy.py [--region REGION]
    2. Create the Lambda execution role (once per account):
           See Step 2 in this script — role is created automatically.
    3. Install evaluation dependencies:
           pip install -r requirements.txt

Outputs:
    results/code_evaluator_ids.json    - Lambda ARNs and evaluator IDs
    results/on_demand_results.json     - EvaluationClient per-session scores
    results/dataset_runner_results.json - OnDemandDatasetRunner per-scenario scores
    results/online_eval_config.json    - Online evaluation config details
"""

import argparse
import io
import json
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import boto3
from boto3.session import Session
from botocore.config import Config

# ============================================================
# 0. Parse args and load agent config
# ============================================================

_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_CONFIG = _SCRIPT_DIR / ".." / "utils" / "agent_config.json"
_RESULTS_DIR = _SCRIPT_DIR / "results"
_RESULTS_DIR.mkdir(exist_ok=True)

parser = argparse.ArgumentParser(description="Code-based evaluation for the HR Assistant agent")
parser.add_argument("--region", default=None, help="AWS region")
parser.add_argument(
    "--config",
    default=str(_DEFAULT_CONFIG),
    help="Path to agent_config.json (written by deploy.py)",
)
parser.add_argument(
    "--with-jev",
    action="store_true",
    default=False,
    help="Deploy JEV-based Lambda evaluators and run a demo session (requires --jev-secret-arn)",
)
parser.add_argument(
    "--jev-secret-arn",
    default="",
    help="AWS Secrets Manager ARN containing the Jev API key (required when --with-jev is set)",
)
parser.add_argument(
    "--with-decider",
    action="store_true",
    default=False,
    help="Deploy Strands Decider Lambda evaluators and run a demo session (requires --decider-url)",
)
parser.add_argument(
    "--decider-url",
    default="http://localhost:8000",
    help="URL of the running Strands Decider server, e.g. http://<host>:8000 (required when --with-decider is set)",
)
args = parser.parse_args()

_config_path = Path(args.config)
if not _config_path.exists():
    print(f"ERROR: Agent config not found at {_config_path}")
    print("Run deploy.py first:  cd ../utils && python deploy.py")
    sys.exit(1)

_cfg = json.loads(_config_path.read_text())
AGENT_ID = _cfg["agent_id"]
AGENT_ARN = _cfg["agent_arn"]
CW_LOG_GROUP = _cfg["cw_log_group"]
REGION = args.region or _cfg.get("region") or Session().region_name or "us-east-1"

ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

_runtime_id = AGENT_ARN.split("/")[-1]
_agent_runtime_name = _runtime_id.rsplit("-", 1)[0]
OTEL_SERVICE_NAME = f"{_agent_runtime_name}.DEFAULT"

print("=" * 60)
print("HR Assistant Agent — Code-Based Evaluation")
print("=" * 60)
print(f"  Region       : {REGION}")
print(f"  Agent ID     : {AGENT_ID}")
print(f"  Agent ARN    : {AGENT_ARN}")
print(f"  CW Log Group : {CW_LOG_GROUP}")

agentcore_client = boto3.client(
    "bedrock-agentcore",
    region_name=REGION,
    config=Config(read_timeout=120, connect_timeout=30),
)
_cp = boto3.client("bedrock-agentcore-control", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
iam_client = boto3.client("iam")

RUN_SUFFIX = uuid.uuid4().hex[:8]
print(f"  Run suffix   : {RUN_SUFFIX}")

# ============================================================
# 1. Create Lambda execution role
# ============================================================

print("\n[1/5] Setting up Lambda execution role ...")

LAMBDA_ROLE_NAME = "AgentCoreLambdaEvaluatorRole"
LAMBDA_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{LAMBDA_ROLE_NAME}"

_lambda_trust = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)

try:
    iam_client.get_role(RoleName=LAMBDA_ROLE_NAME)
    print(f"  Using existing role: {LAMBDA_ROLE_ARN}")
except iam_client.exceptions.NoSuchEntityException:
    iam_client.create_role(
        RoleName=LAMBDA_ROLE_NAME,
        AssumeRolePolicyDocument=_lambda_trust,
        Description="Execution role for AgentCore code-based evaluator Lambda functions",
    )
    iam_client.attach_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    print(f"  Created role: {LAMBDA_ROLE_ARN}")
    print("  Waiting 15s for IAM propagation ...")
    time.sleep(15)

# ============================================================
# 2. Package and deploy Lambda functions
# ============================================================
#
# Each Lambda function is packaged with the bedrock-agentcore SDK
# (which provides @custom_code_based_evaluator(), EvaluatorInput,
# EvaluatorOutput) plus its Python dependencies.
#
# The lambda source files live in lambdas/<name>/lambda_function.py
# alongside this script. They use the @custom_code_based_evaluator()
# decorator which handles the Lambda handler protocol automatically.

print("\n[2/5] Packaging and deploying Lambda evaluators ...")


def _make_zip(source_dir: str) -> bytes:
    """Bundle Lambda source + bedrock-agentcore SDK into an in-memory zip."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "packages"
        pkg_dir.mkdir()

        print("    Bundling bedrock-agentcore SDK ...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "bedrock-agentcore>=1.6.0",
                "--no-deps",
                "--target",
                str(pkg_dir),
                "--quiet",
            ],
            check=True,
        )

        print("    Bundling pydantic (Linux x86_64 Python 3.12) ...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "pydantic>=2.0.0",
                "--target",
                str(pkg_dir),
                "--platform",
                "manylinux2014_x86_64",
                "--implementation",
                "cp",
                "--python-version",
                "312",
                "--only-binary=:all:",
                "--quiet",
            ],
            check=True,
        )

        # bedrock-agentcore imports starlette/uvicorn/websockets/requests at module load
        print("    Bundling starlette, uvicorn, websockets, typing-extensions, requests ...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "starlette",
                "uvicorn",
                "websockets",
                "typing-extensions",
                "requests",
                "--target",
                str(pkg_dir),
                "--quiet",
            ],
            check=True,
        )

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for py_file in sorted(Path(source_dir).glob("*.py")):
                zf.write(py_file, py_file.name)
            for pkg_file in sorted(pkg_dir.rglob("*")):
                if pkg_file.is_file():
                    zf.write(pkg_file, str(pkg_file.relative_to(pkg_dir)))

    buf.seek(0)
    data = buf.read()
    print(f"    Zip size: {len(data) // 1024} KB")
    return data


def _deploy_lambda(function_name: str, source_dir: str, timeout_s: int = 60) -> str:
    """Create or update a Lambda function. Returns the function ARN."""
    print(f"\n  Packaging {function_name} ...")
    zip_bytes = _make_zip(source_dir)

    try:
        resp = lambda_client.get_function(FunctionName=function_name)
        print("  Updating existing function ...")
        lambda_client.update_function_code(FunctionName=function_name, ZipFile=zip_bytes)
        waiter = lambda_client.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=function_name)
        arn = resp["Configuration"]["FunctionArn"]
    except lambda_client.exceptions.ResourceNotFoundException:
        print("  Creating new function ...")
        resp = lambda_client.create_function(
            FunctionName=function_name,
            Runtime="python3.12",
            Role=LAMBDA_ROLE_ARN,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=timeout_s + 10,
            MemorySize=128,
            Description=f"AgentCore code-based evaluator: {function_name}",
        )
        waiter = lambda_client.get_waiter("function_active_v2")
        waiter.wait(FunctionName=function_name)
        arn = resp["FunctionArn"]
    print(f"  ARN: {arn}")
    return arn


def _add_invoke_permission(function_name: str) -> None:
    """Grant bedrock-agentcore.amazonaws.com permission to invoke the Lambda."""
    statement_id = "AllowAgentCoreEvaluateInvoke"
    try:
        lambda_client.remove_permission(FunctionName=function_name, StatementId=statement_id)
    except lambda_client.exceptions.ResourceNotFoundException:
        pass
    lambda_client.add_permission(
        FunctionName=function_name,
        StatementId=statement_id,
        Action="lambda:InvokeFunction",
        Principal="bedrock-agentcore.amazonaws.com",
        SourceAccount=ACCOUNT_ID,
    )
    print("  Granted lambda:InvokeFunction to bedrock-agentcore.amazonaws.com")


LAMBDAS_DIR = _SCRIPT_DIR / "lambdas"

ARN_RESPONSE_LENGTH = _deploy_lambda(
    "hr-response-length",
    str(LAMBDAS_DIR / "hr_response_length"),
    timeout_s=30,
)
_add_invoke_permission("hr-response-length")

ARN_FACT_CHECKER = _deploy_lambda(
    "hr-fact-checker",
    str(LAMBDAS_DIR / "hr_fact_checker"),
    timeout_s=60,
)
_add_invoke_permission("hr-fact-checker")

# ============================================================
# 3. Register evaluators with AgentCore
# ============================================================
#
# Each Lambda is registered as an evaluator via the control plane.
# Once registered, the evaluator ID can be used anywhere built-in
# evaluator IDs are accepted (EvaluationClient, dataset runner, batch eval,
# online evaluation configs).

print("\n[3/5] Registering code-based evaluators ...")
print("  Waiting 5s for IAM policy propagation ...")
time.sleep(5)


def _create_code_evaluator(name: str, lambda_arn: str, level: str, timeout_s: int) -> str:
    unique_name = f"{name}_{RUN_SUFFIX}"
    print(f"  Creating '{unique_name}' (level={level}) ...")
    resp = _cp.create_evaluator(
        evaluatorName=unique_name,
        level=level,
        evaluatorConfig={
            "codeBased": {
                "lambdaConfig": {
                    "lambdaArn": lambda_arn,
                    "lambdaTimeoutInSeconds": timeout_s,
                }
            }
        },
    )
    evaluator_id = resp["evaluatorId"]
    print(f"    evaluatorId: {evaluator_id}")
    return evaluator_id


EVAL_ID_RESPONSE_LENGTH = _create_code_evaluator("HRResponseLength", ARN_RESPONSE_LENGTH, level="TRACE", timeout_s=30)
EVAL_ID_FACT_CHECKER = _create_code_evaluator("HRFactChecker", ARN_FACT_CHECKER, level="SESSION", timeout_s=60)

CODE_EVAL_IDS = {
    "HRResponseLength": EVAL_ID_RESPONSE_LENGTH,
    "HRFactChecker": EVAL_ID_FACT_CHECKER,
}

# Save evaluator IDs for reuse
_ids_path = _RESULTS_DIR / "code_evaluator_ids.json"
_ids_path.write_text(
    json.dumps(
        {
            "HRResponseLength": {
                "id": EVAL_ID_RESPONSE_LENGTH,
                "level": "TRACE",
                "lambda_arn": ARN_RESPONSE_LENGTH,
            },
            "HRFactChecker": {
                "id": EVAL_ID_FACT_CHECKER,
                "level": "SESSION",
                "lambda_arn": ARN_FACT_CHECKER,
            },
        },
        indent=2,
    )
)
print(f"\n  Evaluator IDs saved: {_ids_path}")

# ============================================================
# 4. On-Demand Evaluation (EvaluationClient)
# ============================================================
#
# Invoke the agent to generate a session with HR data facts,
# then evaluate it with both code-based and built-in evaluators.

print("\n[4/5] Running on-demand evaluation ...")


def _invoke_agent(prompt: str, session_id: str) -> str:
    resp = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )
    raw = resp["response"].read().decode("utf-8")
    parts = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            chunk = line[len("data: ") :]
            try:
                chunk = json.loads(chunk)
            except Exception:
                pass
            parts.append(str(chunk))
    return "".join(parts) if parts else raw


ONDEMAND_SESSION_ID = f"code-eval-{uuid.uuid4()}"
print(f"\n  Invoking agent (session: {ONDEMAND_SESSION_ID[:30]}...) ...")

ON_DEMAND_TURNS = [
    "What is the current PTO balance for employee EMP-001?",
    "Please submit a PTO request for EMP-001 from 2026-08-04 to 2026-08-06.",
    "What is the company PTO policy?",
]

for prompt in ON_DEMAND_TURNS:
    print(f"    > {prompt[:70]}")
    reply = _invoke_agent(prompt, ONDEMAND_SESSION_ID)
    print(f"    < {reply[:100]}")

print("\n  Waiting 150s for CloudWatch log ingestion ...")
time.sleep(150)

from bedrock_agentcore.evaluation import EvaluationClient  # noqa: E402
from datetime import timedelta  # noqa: E402

ec = EvaluationClient(region_name=REGION)
ec._evaluator_level_cache.update(
    {
        "Builtin.Correctness": "TRACE",
        "Builtin.GoalSuccessRate": "SESSION",
        EVAL_ID_RESPONSE_LENGTH: "TRACE",
        EVAL_ID_FACT_CHECKER: "SESSION",
    }
)

od_results = ec.run(
    evaluator_ids=[
        "Builtin.Correctness",
        "Builtin.GoalSuccessRate",
        EVAL_ID_RESPONSE_LENGTH,
        EVAL_ID_FACT_CHECKER,
    ],
    agent_id=AGENT_ID,
    session_id=ONDEMAND_SESSION_ID,
    look_back_time=timedelta(hours=1),
)

print(f"\n  On-demand results ({len(od_results)} result(s)):\n")
_name_map = {v: k for k, v in CODE_EVAL_IDS.items()}
print(f"  {'Evaluator':<45} {'Value':<8} {'Label'}")
print("  " + "-" * 75)
for r in od_results:
    eid = r.get("evaluatorId", "")
    name = eid if eid.startswith("Builtin.") else _name_map.get(eid, eid[:20])
    value = r.get("value", r.get("score", "N/A"))
    label = r.get("label", r.get("rating", "N/A"))
    error = r.get("errorCode")
    if error:
        label = f"ERR:{error}"
    print(f"  {name:<45} {str(value):<8} {str(label)}")

(_RESULTS_DIR / "on_demand_results.json").write_text(
    json.dumps(
        {
            "session_id": ONDEMAND_SESSION_ID,
            "results": od_results,
            "code_evaluator_ids": CODE_EVAL_IDS,
        },
        indent=2,
        default=str,
    )
)

# ============================================================
# 4b. OnDemandEvaluationDatasetRunner — mixed evaluator set
# ============================================================
#
# The dataset runner invokes the agent once per scenario, waits for
# CloudWatch ingestion, then evaluates all sessions in one pass.
# Mixing code-based with built-in evaluators is fully supported.

print("\n  Running OnDemandEvaluationDatasetRunner (mixed evaluators) ...")

from bedrock_agentcore.evaluation import (  # noqa: E402
    AgentInvokerInput,
    AgentInvokerOutput,
    CloudWatchAgentSpanCollector,
    Dataset,
    EvaluationRunConfig,
    EvaluatorConfig,
    OnDemandEvaluationDatasetRunner,
    PredefinedScenario,
    Turn,
)


def _agent_invoker(invoker_input: AgentInvokerInput) -> AgentInvokerOutput:
    payload = invoker_input.payload
    body = {"prompt": payload} if isinstance(payload, str) else payload
    resp = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=invoker_input.session_id,
        payload=json.dumps(body).encode("utf-8"),
    )
    raw = resp["response"].read().decode("utf-8")
    parts = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            chunk = line[len("data: ") :]
            try:
                chunk = json.loads(chunk)
            except Exception:
                pass
            parts.append(str(chunk))
    return AgentInvokerOutput(agent_output="".join(parts) if parts else raw)


DATASET_SCENARIOS = [
    PredefinedScenario(
        scenario_id="pto-balance-emp001",
        turns=[
            Turn(
                input="What is the current PTO balance for employee EMP-001?",
                expected_response="Employee EMP-001 has 10 remaining PTO days out of 15 total (5 days used).",
            )
        ],
        expected_trajectory=["get_pto_balance"],
        assertions=[
            "Agent called get_pto_balance with employee_id=EMP-001",
            "Agent reported 10 remaining PTO days",
        ],
    ),
    PredefinedScenario(
        scenario_id="submit-pto-request",
        turns=[
            Turn(
                input="Please submit a PTO request for EMP-001 from 2026-09-01 to 2026-09-05.",
                expected_response="PTO request submitted for EMP-001 from 2026-09-01 to 2026-09-05. Request ID: PTO-2026-NNN.",
            )
        ],
        expected_trajectory=["submit_pto_request"],
        assertions=["Agent submitted a PTO request", "Agent returned a PTO request ID"],
    ),
    PredefinedScenario(
        scenario_id="pay-stub-lookup",
        turns=[
            Turn(
                input="Can you pull up the January 2026 pay stub for employee EMP-001?",
                expected_response="Gross pay: $8,333.33. Net pay: $5,362.50 for January 2026.",
            )
        ],
        expected_trajectory=["get_pay_stub"],
        assertions=[
            "Agent called get_pay_stub",
            "Agent reported gross and net pay figures",
        ],
    ),
    PredefinedScenario(
        scenario_id="pto-policy-lookup",
        turns=[
            Turn(
                input="What is the company's PTO accrual policy?",
                expected_response="Full-time employees accrue 15 days of PTO per year. Requests require 2 business days advance notice.",
            )
        ],
        expected_trajectory=["lookup_hr_policy"],
        assertions=[
            "Agent described the PTO accrual policy",
            "Agent mentioned 15 days",
        ],
    ),
    PredefinedScenario(
        scenario_id="benefits-summary",
        turns=[
            Turn(
                input="What health insurance and 401k benefits does the company offer?",
                expected_response="The company covers 90% of health insurance premiums and matches 401(k) contributions up to 4%.",
            )
        ],
        expected_trajectory=["get_benefits_summary"],
        assertions=[
            "Agent described health insurance coverage",
            "Agent described 401k match",
        ],
    ),
]

_span_collector = CloudWatchAgentSpanCollector(
    log_group_name=CW_LOG_GROUP,
    region=REGION,
)

_all_evaluator_ids = [
    "Builtin.Correctness",
    "Builtin.Helpfulness",
    "Builtin.ResponseRelevance",
    EVAL_ID_RESPONSE_LENGTH,
    EVAL_ID_FACT_CHECKER,
]

_evaluator_levels = {
    "Builtin.Correctness": "TRACE",
    "Builtin.Helpfulness": "TRACE",
    "Builtin.ResponseRelevance": "TRACE",
    EVAL_ID_RESPONSE_LENGTH: "TRACE",
    EVAL_ID_FACT_CHECKER: "SESSION",
}

_evaluator_config = EvaluatorConfig(evaluator_ids=_all_evaluator_ids)

_config = EvaluationRunConfig(
    evaluator_config=_evaluator_config,
    evaluation_delay_seconds=150,
)

_runner = OnDemandEvaluationDatasetRunner(region=REGION)
_runner._evaluator_level_cache.update(_evaluator_levels)

print(f"  Scenarios  : {len(DATASET_SCENARIOS)}")
print(f"  Evaluators : {len(_all_evaluator_ids)} ({3} builtin + {2} code-based)")
print(f"  Delay      : {_config.evaluation_delay_seconds}s\n")

_dataset_result = _runner.run(
    config=_config,
    dataset=Dataset(scenarios=DATASET_SCENARIOS),
    agent_invoker=_agent_invoker,
    span_collector=_span_collector,
)

_completed = sum(1 for sr in _dataset_result.scenario_results if sr.status == "COMPLETED")
_failed = sum(1 for sr in _dataset_result.scenario_results if sr.status == "FAILED")
print(f"\n  Dataset runner complete: {_completed} completed, {_failed} failed.\n")

for sr in _dataset_result.scenario_results:
    if sr.status == "FAILED":
        print(f"  [{sr.scenario_id}] FAILED: {sr.error}")
        continue
    print(f"  [{sr.scenario_id}]")
    for er in sr.evaluator_results:
        eid = er.evaluator_id
        name = eid if eid.startswith("Builtin.") else _name_map.get(eid, eid[:20])
        for res in er.results:
            value = res.get("value", res.get("score", "N/A"))
            label = res.get("label", res.get("rating", "N/A"))
            error = res.get("errorCode")
            if error:
                label = f"ERR:{error}"
            print(f"    {name:<40} {str(value):<8} {str(label)}")

(_RESULTS_DIR / "dataset_runner_results.json").write_text(
    json.dumps(_dataset_result.model_dump(), indent=2, default=str)
)

# ============================================================
# 5. Online Evaluation with Code-Based Evaluators
# ============================================================
#
# Code-based evaluators can be used in online evaluation configs
# just like built-in evaluators.

print("\n[5/5] Creating online evaluation config with code-based evaluators ...")

ONLINE_EVAL_ROLE_NAME = "AgentCoreOnlineEvaluationRole"
ONLINE_EVAL_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{ONLINE_EVAL_ROLE_NAME}"

_online_trust = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)

_online_policy = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeLambdaEvaluators",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction", "lambda:GetFunction"],
                "Resource": [ARN_RESPONSE_LENGTH, ARN_FACT_CHECKER],
            },
            {
                "Sid": "CloudWatchLogsAccess",
                "Effect": "Allow",
                "Action": [
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:StopQuery",
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "*",
            },
        ],
    }
)

try:
    iam_client.get_role(RoleName=ONLINE_EVAL_ROLE_NAME)
    iam_client.put_role_policy(
        RoleName=ONLINE_EVAL_ROLE_NAME,
        PolicyName="AgentCoreOnlineCodeEvalPermissions",
        PolicyDocument=_online_policy,
    )
    print(f"  Using existing IAM role: {ONLINE_EVAL_ROLE_ARN}")
except iam_client.exceptions.NoSuchEntityException:
    iam_client.create_role(
        RoleName=ONLINE_EVAL_ROLE_NAME,
        AssumeRolePolicyDocument=_online_trust,
        Description="Execution role for AgentCore online evaluation",
    )
    iam_client.put_role_policy(
        RoleName=ONLINE_EVAL_ROLE_NAME,
        PolicyName="AgentCoreOnlineCodeEvalPermissions",
        PolicyDocument=_online_policy,
    )
    print(f"  Created IAM role: {ONLINE_EVAL_ROLE_ARN}")

print("  Waiting 10s for IAM propagation ...")
time.sleep(10)

ONLINE_CONFIG_NAME = f"hr_code_eval_{RUN_SUFFIX}"

_online_resp = _cp.create_online_evaluation_config(
    onlineEvaluationConfigName=ONLINE_CONFIG_NAME,
    rule={"samplingConfig": {"samplingPercentage": 100.0}},
    dataSourceConfig={
        "cloudWatchLogs": {
            "logGroupNames": [CW_LOG_GROUP],
            "serviceNames": [OTEL_SERVICE_NAME],
        }
    },
    evaluators=[
        {"evaluatorId": EVAL_ID_RESPONSE_LENGTH},
        {"evaluatorId": EVAL_ID_FACT_CHECKER},
    ],
    evaluationExecutionRoleArn=ONLINE_EVAL_ROLE_ARN,
    enableOnCreate=True,
)

ONLINE_CONFIG_ID = _online_resp["onlineEvaluationConfigId"]
print("\n  Online eval config created:")
print(f"    ID  : {ONLINE_CONFIG_ID}")
print(f"    ARN : {_online_resp.get('onlineEvaluationConfigArn', '')}")
print()
print("  Evaluators HRResponseLength + HRFactChecker are now LOCKED to this config.")

(_RESULTS_DIR / "online_eval_config.json").write_text(
    json.dumps(
        {
            "config_name": ONLINE_CONFIG_NAME,
            "config_id": ONLINE_CONFIG_ID,
            "code_evaluator_ids": CODE_EVAL_IDS,
            "lambda_arns": {
                "hr-response-length": ARN_RESPONSE_LENGTH,
                "hr-fact-checker": ARN_FACT_CHECKER,
            },
        },
        indent=2,
    )
)
print(f"  Config saved: {_RESULTS_DIR / 'online_eval_config.json'}")

# ============================================================
# 6. JEV Decision-Model Evaluators  (opt-in: --with-jev)
# ============================================================
#
# Jev is a decision model hosted by TypeSafe that replaces LLM-as-a-judge
# with a specialized, calibrated inference API. The Lambda below is a thin
# wrapper that:
#   1. Reconstructs conversation turns from the OTel spans
#   2. Sends the structured state + question to the Jev API
#   3. Converts the probability-weighted answer to an AgentCore score
#
# Three evaluators share one Lambda function. AgentCore passes the evaluator
# name in each event so the Lambda can look up the right Jev question.
#
# Prerequisite: store your Jev API key in AWS Secrets Manager and pass the
# secret ARN via --jev-secret-arn.

if args.with_jev:
    if not args.jev_secret_arn:
        print("\n[6/7] SKIPPED JEV: --jev-secret-arn is required when using --with-jev")
    else:
        print("\n[6/7] Deploying and registering Jev decision-model evaluators ...")

        JEV_LAMBDAS_DIR = LAMBDAS_DIR / "jev_evaluator"

        def _make_zip_lightweight(source_dir: str) -> bytes:
            """Bundle Lambda source files only (no extra pip packages).

            The Jev and Strands Decider Lambda functions use only the Python
            standard library plus boto3 (provided by the Lambda runtime), so
            no additional packages need to be downloaded.
            """
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(Path(source_dir).iterdir()):
                    if f.is_file() and not f.name.endswith(".pyc"):
                        zf.write(f, f.name)
            buf.seek(0)
            data = buf.read()
            print(f"    Zip size: {len(data) // 1024} KB")
            return data

        def _deploy_lambda_lightweight(function_name: str, source_dir: str, env_vars: dict) -> str:
            """Create or update a Lambda function with no extra pip dependencies."""
            print(f"\n  Packaging {function_name} ...")
            zip_bytes = _make_zip_lightweight(source_dir)
            try:
                resp = lambda_client.get_function(FunctionName=function_name)
                print("  Updating existing function ...")
                lambda_client.update_function_code(FunctionName=function_name, ZipFile=zip_bytes)
                waiter = lambda_client.get_waiter("function_updated_v2")
                waiter.wait(FunctionName=function_name)
                lambda_client.update_function_configuration(
                    FunctionName=function_name,
                    Environment={"Variables": env_vars},
                )
                arn = resp["Configuration"]["FunctionArn"]
            except lambda_client.exceptions.ResourceNotFoundException:
                print("  Creating new function ...")
                resp = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime="python3.12",
                    Role=LAMBDA_ROLE_ARN,
                    Handler="lambda_function.lambda_handler",
                    Code={"ZipFile": zip_bytes},
                    Timeout=120,
                    MemorySize=128,
                    Description=f"AgentCore decision-model evaluator: {function_name}",
                    Environment={"Variables": env_vars},
                )
                waiter = lambda_client.get_waiter("function_active_v2")
                waiter.wait(FunctionName=function_name)
                arn = resp["FunctionArn"]
            print(f"  ARN: {arn}")
            return arn

        # Grant Secrets Manager access to the Lambda execution role
        _sm_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "JevSecretRead",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": args.jev_secret_arn,
            }],
        })
        iam_client.put_role_policy(
            RoleName=LAMBDA_ROLE_NAME,
            PolicyName="JevSecretReadPolicy",
            PolicyDocument=_sm_policy,
        )
        print("  Added secretsmanager:GetSecretValue to Lambda role")
        time.sleep(5)

        ARN_JEV = _deploy_lambda_lightweight(
            "jev-evaluator",
            str(JEV_LAMBDAS_DIR),
            env_vars={
                "JEV_API_KEY_SECRET_ARN": args.jev_secret_arn,
                "JEV_MODEL": "jev-latest",
            },
        )
        # Publish a Lambda version so we can create per-evaluator aliases.
        # AgentCore's code-based evaluator contract does NOT pass evaluatorName or
        # evaluatorId in the Lambda event — the Lambda identifies which evaluator
        # triggered it via context.invoked_function_arn (alias ARN, 8 colon-parts).
        _jev_ver = lambda_client.publish_version(FunctionName="jev-evaluator")["Version"]
        print(f"  Published Lambda version: {_jev_ver}")

        JEV_EVALUATOR_DEFS = [
            ("JevGroundedness", "TRACE", 90),
            ("JevHelpfulness", "TRACE", 90),
            ("JevGoalCompletion", "SESSION", 90),
        ]

        jev_ids: dict[str, str] = {}
        for eval_name, eval_level, timeout_s in JEV_EVALUATOR_DEFS:
            unique_name = f"{eval_name}_{RUN_SUFFIX}"
            # Create/update Lambda alias — the alias name becomes arn_parts[7] in the handler
            try:
                lambda_client.create_alias(
                    FunctionName="jev-evaluator",
                    Name=unique_name,
                    FunctionVersion=_jev_ver,
                )
            except lambda_client.exceptions.ResourceConflictException:
                lambda_client.update_alias(
                    FunctionName="jev-evaluator",
                    Name=unique_name,
                    FunctionVersion=_jev_ver,
                )
            alias_arn = f"{ARN_JEV}:{unique_name}"
            # Add invoke permission on this specific alias
            try:
                lambda_client.add_permission(
                    FunctionName=f"jev-evaluator:{unique_name}",
                    StatementId="AgentCoreInvoke",
                    Action="lambda:InvokeFunction",
                    Principal="bedrock-agentcore.amazonaws.com",
                )
            except lambda_client.exceptions.ResourceConflictException:
                pass
            print(f"  Creating '{unique_name}' (level={eval_level}) ...")
            resp = _cp.create_evaluator(
                evaluatorName=unique_name,
                level=eval_level,
                evaluatorConfig={
                    "codeBased": {
                        "lambdaConfig": {
                            "lambdaArn": alias_arn,
                            "lambdaTimeoutInSeconds": timeout_s,
                        }
                    }
                },
            )
            jev_ids[eval_name] = resp["evaluatorId"]
            print(f"    evaluatorId: {resp['evaluatorId']}")

        (_RESULTS_DIR / "jev_evaluator_ids.json").write_text(
            json.dumps({"lambda_arn": ARN_JEV, "evaluator_ids": jev_ids}, indent=2)
        )

        # Invoke agent and evaluate with Jev evaluators
        JEV_SESSION_ID = f"jev-eval-{uuid.uuid4()}"
        print(f"\n  Invoking agent for Jev evaluation (session: {JEV_SESSION_ID[:30]}...) ...")
        for prompt in ON_DEMAND_TURNS:
            print(f"    > {prompt[:70]}")
            _invoke_agent(prompt, JEV_SESSION_ID)

        print("\n  Waiting 150s for CloudWatch log ingestion ...")
        time.sleep(150)

        jev_ec = EvaluationClient(region_name=REGION)
        jev_ec._evaluator_level_cache.update(
            {jev_ids["JevGroundedness"]: "TRACE",
             jev_ids["JevHelpfulness"]: "TRACE",
             jev_ids["JevGoalCompletion"]: "SESSION"}
        )

        jev_results = jev_ec.run(
            evaluator_ids=list(jev_ids.values()),
            agent_id=AGENT_ID,
            session_id=JEV_SESSION_ID,
            look_back_time=timedelta(hours=1),
        )

        _jev_name_map = {v: k for k, v in jev_ids.items()}
        print(f"\n  Jev results ({len(jev_results)} result(s)):\n")
        print(f"  {'Evaluator':<30} {'Value':<8} {'Label'}")
        print("  " + "-" * 60)
        for r in jev_results:
            eid = r.get("evaluatorId", "")
            name = _jev_name_map.get(eid, eid[:20])
            value = r.get("value", "N/A")
            label = r.get("label", "N/A")
            if r.get("errorCode"):
                label = f"ERR:{r['errorCode']}"
            print(f"  {name:<30} {str(value):<8} {str(label)}")

        (_RESULTS_DIR / "jev_results.json").write_text(
            json.dumps({"session_id": JEV_SESSION_ID, "results": jev_results,
                        "evaluator_ids": jev_ids}, indent=2, default=str)
        )
        print(f"\n  Jev results saved: {_RESULTS_DIR / 'jev_results.json'}")


# ============================================================
# 7. Strands Decider Evaluators  (opt-in: --with-decider)
# ============================================================
#
# Strands Decider 2B is an open-source, self-hostable decision model that
# exposes the same /v1/systemone HTTP API as Jev. Because it runs on your
# own hardware, there is no external API key and no data egress.
#
# The Lambda connects to a running Strands Decider server via DECIDER_SERVER_URL.
# Conversation turns are serialized to plain text before sending to the server,
# since Strands Decider operates on text state rather than structured JSON.
#
# Start the server before running this script:
#   pip install strands-decider
#   strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --port 8000
#
# Or via Docker:
#   docker run --rm -p 8000:8000 \
#       -e MODEL=StrandsAgents/strands-decider-2B-hobson-v21 \
#       public.ecr.aws/strands/decider:latest
#
# Then pass the URL: python evaluate.py --with-decider --decider-url http://<host>:8000

if args.with_decider:
    print("\n[7/7] Deploying and registering Strands Decider evaluators ...")
    print(f"  Decider server : {args.decider_url}")

    DECIDER_LAMBDAS_DIR = LAMBDAS_DIR / "strands_decider_evaluator"

    if "_make_zip_lightweight" not in dir():
        def _make_zip_lightweight(source_dir: str) -> bytes:  # type: ignore[no-redef]
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(Path(source_dir).iterdir()):
                    if f.is_file() and not f.name.endswith(".pyc"):
                        zf.write(f, f.name)
            buf.seek(0)
            data = buf.read()
            print(f"    Zip size: {len(data) // 1024} KB")
            return data

        def _deploy_lambda_lightweight(function_name: str, source_dir: str, env_vars: dict) -> str:  # type: ignore[no-redef]
            print(f"\n  Packaging {function_name} ...")
            zip_bytes = _make_zip_lightweight(source_dir)
            try:
                resp = lambda_client.get_function(FunctionName=function_name)
                print("  Updating existing function ...")
                lambda_client.update_function_code(FunctionName=function_name, ZipFile=zip_bytes)
                waiter = lambda_client.get_waiter("function_updated_v2")
                waiter.wait(FunctionName=function_name)
                lambda_client.update_function_configuration(
                    FunctionName=function_name,
                    Environment={"Variables": env_vars},
                )
                arn = resp["Configuration"]["FunctionArn"]
            except lambda_client.exceptions.ResourceNotFoundException:
                print("  Creating new function ...")
                resp = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime="python3.12",
                    Role=LAMBDA_ROLE_ARN,
                    Handler="lambda_function.lambda_handler",
                    Code={"ZipFile": zip_bytes},
                    Timeout=120,
                    MemorySize=128,
                    Description=f"AgentCore decision-model evaluator: {function_name}",
                    Environment={"Variables": env_vars},
                )
                waiter = lambda_client.get_waiter("function_active_v2")
                waiter.wait(FunctionName=function_name)
                arn = resp["FunctionArn"]
            print(f"  ARN: {arn}")
            return arn

    ARN_DECIDER = _deploy_lambda_lightweight(
        "strands-decider-evaluator",
        str(DECIDER_LAMBDAS_DIR),
        env_vars={"DECIDER_SERVER_URL": args.decider_url},
    )
    # Publish a Lambda version so we can create per-evaluator aliases.
    # AgentCore's code-based evaluator contract does NOT pass evaluatorName or
    # evaluatorId in the Lambda event — the Lambda identifies which evaluator
    # triggered it via context.invoked_function_arn (alias ARN, 8 colon-parts).
    _decider_ver = lambda_client.publish_version(FunctionName="strands-decider-evaluator")["Version"]
    print(f"  Published Lambda version: {_decider_ver}")

    DECIDER_EVALUATOR_DEFS = [
        ("DeciderGroundedness", "TRACE", 90),
        ("DeciderHelpfulness", "TRACE", 90),
        ("DeciderGoalCompletion", "SESSION", 90),
    ]

    decider_ids: dict[str, str] = {}
    for eval_name, eval_level, timeout_s in DECIDER_EVALUATOR_DEFS:
        unique_name = f"{eval_name}_{RUN_SUFFIX}"
        # Create/update Lambda alias — the alias name becomes arn_parts[7] in the handler
        try:
            lambda_client.create_alias(
                FunctionName="strands-decider-evaluator",
                Name=unique_name,
                FunctionVersion=_decider_ver,
            )
        except lambda_client.exceptions.ResourceConflictException:
            lambda_client.update_alias(
                FunctionName="strands-decider-evaluator",
                Name=unique_name,
                FunctionVersion=_decider_ver,
            )
        alias_arn = f"{ARN_DECIDER}:{unique_name}"
        # Add invoke permission on this specific alias
        try:
            lambda_client.add_permission(
                FunctionName=f"strands-decider-evaluator:{unique_name}",
                StatementId="AgentCoreInvoke",
                Action="lambda:InvokeFunction",
                Principal="bedrock-agentcore.amazonaws.com",
            )
        except lambda_client.exceptions.ResourceConflictException:
            pass
        print(f"  Creating '{unique_name}' (level={eval_level}) ...")
        resp = _cp.create_evaluator(
            evaluatorName=unique_name,
            level=eval_level,
            evaluatorConfig={
                "codeBased": {
                    "lambdaConfig": {
                        "lambdaArn": alias_arn,
                        "lambdaTimeoutInSeconds": timeout_s,
                    }
                }
            },
        )
        decider_ids[eval_name] = resp["evaluatorId"]
        print(f"    evaluatorId: {resp['evaluatorId']}")

    (_RESULTS_DIR / "decider_evaluator_ids.json").write_text(
        json.dumps({"lambda_arn": ARN_DECIDER, "server_url": args.decider_url,
                    "evaluator_ids": decider_ids}, indent=2)
    )

    # Invoke agent and evaluate with Strands Decider evaluators
    DECIDER_SESSION_ID = f"decider-eval-{uuid.uuid4()}"
    print(f"\n  Invoking agent for Decider evaluation (session: {DECIDER_SESSION_ID[:30]}...) ...")
    for prompt in ON_DEMAND_TURNS:
        print(f"    > {prompt[:70]}")
        _invoke_agent(prompt, DECIDER_SESSION_ID)

    print("\n  Waiting 150s for CloudWatch log ingestion ...")
    time.sleep(150)

    decider_ec = EvaluationClient(region_name=REGION)
    decider_ec._evaluator_level_cache.update(
        {decider_ids["DeciderGroundedness"]: "TRACE",
         decider_ids["DeciderHelpfulness"]: "TRACE",
         decider_ids["DeciderGoalCompletion"]: "SESSION"}
    )

    decider_results = decider_ec.run(
        evaluator_ids=list(decider_ids.values()),
        agent_id=AGENT_ID,
        session_id=DECIDER_SESSION_ID,
        look_back_time=timedelta(hours=1),
    )

    _dec_name_map = {v: k for k, v in decider_ids.items()}
    print(f"\n  Strands Decider results ({len(decider_results)} result(s)):\n")
    print(f"  {'Evaluator':<30} {'Value':<8} {'Label'}")
    print("  " + "-" * 60)
    for r in decider_results:
        eid = r.get("evaluatorId", "")
        name = _dec_name_map.get(eid, eid[:20])
        value = r.get("value", "N/A")
        label = r.get("label", "N/A")
        if r.get("errorCode"):
            label = f"ERR:{r['errorCode']}"
        print(f"  {name:<30} {str(value):<8} {str(label)}")

    (_RESULTS_DIR / "decider_results.json").write_text(
        json.dumps({"session_id": DECIDER_SESSION_ID, "results": decider_results,
                    "evaluator_ids": decider_ids}, indent=2, default=str)
    )
    print(f"\n  Strands Decider results saved: {_RESULTS_DIR / 'decider_results.json'}")


# ============================================================
# Summary
# ============================================================

print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print("  Lambda evaluators deployed : hr-response-length, hr-fact-checker")
print("  Evaluators registered      : HRResponseLength (TRACE), HRFactChecker (SESSION)")
print("  On-demand results          : results/on_demand_results.json")
print("  Dataset runner results     : results/dataset_runner_results.json")
print(f"  Online eval config active  : {ONLINE_CONFIG_NAME}")
if args.with_jev and args.jev_secret_arn:
    print("  Jev evaluators             : JevGroundedness, JevHelpfulness, JevGoalCompletion")
    print("  Jev results                : results/jev_results.json")
if args.with_decider:
    print("  Decider evaluators         : DeciderGroundedness, DeciderHelpfulness, DeciderGoalCompletion")
    print("  Decider results            : results/decider_results.json")
print()
print("  Disable online config when done:")
print("    aws bedrock-agentcore-control update-online-evaluation-config \\")
print(f"        --online-evaluation-config-id {ONLINE_CONFIG_ID} \\")
print("        --enable-config false")
