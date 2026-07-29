#!/usr/bin/env python3
"""Remove post-deploy observability resources created by setup_observability.py.

Safe to run before `cdk destroy --all`. Ignores missing resources.
"""

from __future__ import annotations

import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

_CDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.abspath(os.path.join(_CDK_DIR, ".."))
_LANGGRAPH_CONFIG = os.path.join(_REPO_ROOT, "runtime_agent", "langgraph", "config.json")
_APP_CONFIG = os.path.join(_REPO_ROOT, "application", "config.json")


def _load_config() -> dict:
    for path in (_LANGGRAPH_CONFIG, _APP_CONFIG):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _ignore_missing(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in (
            "ResourceNotFoundException",
            "ResourceNotFound",
            "NoSuchEntity",
            "404",
            "AccessDeniedException",
        ):
            print(f"  skip: {code}")
            return None
        raise


def main() -> int:
    cfg = _load_config()
    project = cfg.get("projectName") or os.environ.get("CDE_PROJECT_NAME", "power-runtime")
    region = cfg.get("region") or os.environ.get("CDE_REGION", "us-west-2")
    print(f"Cleanup observability for project={project} region={region}")

    ctrl = boto3.client("bedrock-agentcore-control", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)
    iam = boto3.client("iam")
    logs = boto3.client("logs", region_name=region)

    eval_id = cfg.get("online_evaluation_config_id")
    eval_name = cfg.get("online_evaluation_config_name")
    if eval_id or eval_name:
        print(f"Deleting online evaluation: {eval_id or eval_name}")
        try:
            if eval_id:
                _ignore_missing(
                    ctrl.delete_online_evaluation_config,
                    onlineEvaluationConfigId=eval_id,
                )
            else:
                _ignore_missing(
                    ctrl.delete_online_evaluation_config,
                    onlineEvaluationConfigName=eval_name,
                )
        except TypeError:
            _ignore_missing(
                ctrl.delete_online_evaluation_config,
                onlineEvaluationConfigName=eval_name or eval_id,
            )

    dash = cfg.get("cloudwatch_dashboard_name") or f"{project}-monitoring"
    print(f"Deleting dashboard: {dash}")
    _ignore_missing(cw.delete_dashboards, DashboardNames=[dash])

    role_name = f"AmazonBedrockAgentCoreEvaluationRoleFor{project}"
    policy_name = f"{role_name}Policy"
    print(f"Deleting IAM role/policy: {role_name}")
    try:
        for p in iam.list_attached_role_policies(RoleName=role_name).get(
            "AttachedPolicies", []
        ):
            iam.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
            if p["PolicyName"] == policy_name or project in p["PolicyArn"]:
                arn = p["PolicyArn"]
                for v in iam.list_policy_versions(PolicyArn=arn).get("Versions", []):
                    if not v.get("IsDefaultVersion"):
                        iam.delete_policy_version(
                            PolicyArn=arn, VersionId=v["VersionId"]
                        )
                _ignore_missing(iam.delete_policy, PolicyArn=arn)
        for p in iam.list_role_policies(RoleName=role_name).get("PolicyNames", []):
            iam.delete_role_policy(RoleName=role_name, PolicyName=p)
        _ignore_missing(iam.delete_role, RoleName=role_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        print("  role already gone")

    runtime_arn = cfg.get("agent_runtime_arn") or ""
    runtime_id = runtime_arn.rsplit("/", 1)[-1] if runtime_arn else ""
    if runtime_id:
        lg = cfg.get("evaluation_log_group") or (
            f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
        )
        print(f"Deleting log group: {lg}")
        _ignore_missing(logs.delete_log_group, logGroupName=lg)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
