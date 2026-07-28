#!/usr/bin/env python3
"""Collect CDK stack outputs and write application/runtime config.json files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

import boto3

# Allow importing cdk/config when run from repo root or cdk/
_CDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CDK_DIR not in sys.path:
    sys.path.insert(0, _CDK_DIR)

from config import (  # noqa: E402
    PROJECT_NAME,
    REGION,
    stack_name,
)


def _project_root() -> str:
    return os.path.abspath(os.path.join(_CDK_DIR, ".."))


def _stack_outputs(cfn, name: str) -> Dict[str, str]:
    try:
        resp = cfn.describe_stacks(StackName=name)
    except Exception:
        return {}
    stacks = resp.get("Stacks") or []
    if not stacks:
        return {}
    return {
        o["OutputKey"]: o["OutputValue"]
        for o in stacks[0].get("Outputs") or []
        if "OutputKey" in o and "OutputValue" in o
    }


def collect_config(
    *,
    account_id: Optional[str] = None,
    region: str = REGION,
) -> Dict[str, Any]:
    session = boto3.Session(region_name=region)
    cfn = session.client("cloudformation")
    sts = session.client("sts")
    account_id = account_id or sts.get_caller_identity()["Account"]

    network = _stack_outputs(cfn, stack_name("network"))
    data = _stack_outputs(cfn, stack_name("data"))
    storage = _stack_outputs(cfn, stack_name("storage"))
    edge = _stack_outputs(cfn, stack_name("edge"))
    agent = _stack_outputs(cfn, stack_name("agentcore"))
    compute = _stack_outputs(cfn, stack_name("compute"))

    private_subnets = [
        s
        for s in (
            storage.get("AgentRuntimeVpcSubnets")
            or network.get("PrivateSubnetIds")
            or ""
        ).split(",")
        if s
    ]
    runtime_sgs = [
        s for s in (storage.get("AgentRuntimeSecurityGroups") or "").split(",") if s
    ]

    config: Dict[str, Any] = {
        "projectName": PROJECT_NAME,
        "accountId": account_id,
        "region": region,
        "knowledge_base_id": data.get("KnowledgeBaseId", ""),
        "data_source_id": data.get("DataSourceId", ""),
        "knowledge_base_role": data.get("KnowledgeBaseRoleArn", ""),
        "collectionArn": "",
        "opensearch_url": "",
        "vector_bucket_name": data.get("VectorBucketName", ""),
        "vector_bucket_arn": data.get("VectorBucketArn", ""),
        "vector_index_name": data.get("VectorIndexName", PROJECT_NAME),
        "vector_index_arn": data.get("VectorIndexArn", ""),
        "s3_bucket": data.get("S3BucketName", ""),
        "s3_arn": data.get("S3BucketArn", ""),
        "sharing_url": edge.get("SharingUrl", ""),
        "s3_files_file_system_id": storage.get("S3FilesFileSystemId", ""),
        "s3_files_access_point_arn": storage.get("S3FilesAccessPointArn", ""),
        "agent_runtime_vpc_subnets": private_subnets,
        "agent_runtime_security_groups": runtime_sgs,
        "agent_runtime_arn": agent.get("AgentRuntimeArn", ""),
        "agent_runtime_role": agent.get("AgentRuntimeRoleArn", ""),
        "latest_image_tag": "",
        "build_number": "",
    }

    web_uri = compute.get("WebImageUri", "")
    if web_uri and ":" in web_uri:
        config["latest_image_tag"] = web_uri.rsplit(":", 1)[-1]
        config["build_number"] = config["latest_image_tag"]

    return config


def write_json(path: str, data: Dict[str, Any], *, merge: bool = True) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing: Dict[str, Any] = {}
    if merge and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write config.json from CDK outputs")
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args()

    config = collect_config(region=args.region)
    root = _project_root()
    app_path = os.path.join(root, "application", "config.json")
    runtime_path = os.path.join(root, "runtime_agent", "langgraph", "config.json")
    write_json(app_path, config)
    write_json(runtime_path, config)
    print(f"Wrote {app_path}")
    print(f"Wrote {runtime_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
