#!/usr/bin/env python3
"""Post-CDK setup: Observability → Evaluations → CloudWatch dashboards.

Reuses runtime_agent/langgraph installer helpers (same as boto3 installer).
Run after `cdk deploy` and preferably after `write_config.py`.

  python3 scripts/write_config.py
  python3 scripts/setup_observability.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_CDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.abspath(os.path.join(_CDK_DIR, ".."))
_LANGGRAPH_DIR = os.path.join(_REPO_ROOT, "runtime_agent", "langgraph")


def _ensure_runtime_config() -> dict:
    path = os.path.join(_LANGGRAPH_DIR, "config.json")
    if not os.path.isfile(path):
        raise SystemExit(
            f"Missing {path}. Run first:\n"
            f"  python3 {_CDK_DIR}/scripts/write_config.py"
        )
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    if not config.get("agent_runtime_arn"):
        raise SystemExit(
            "config.json has no agent_runtime_arn. Deploy the agentcore stack "
            "and run write_config.py first."
        )
    if not config.get("region") or not config.get("accountId"):
        raise SystemExit("config.json needs region and accountId (write_config.py).")
    return config


def _refresh_config(region: str | None) -> None:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _CDK_DIR not in sys.path:
        sys.path.insert(0, _CDK_DIR)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from config import REGION  # noqa: WPS433
    from write_config import collect_config, write_json  # noqa: WPS433

    cfg = collect_config(region=region or REGION)
    write_json(os.path.join(_REPO_ROOT, "application", "config.json"), cfg)
    write_json(os.path.join(_LANGGRAPH_DIR, "config.json"), cfg)
    print("Refreshed application/ and runtime_agent/langgraph/config.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure AgentCore Observability, Evaluations, and dashboards"
    )
    parser.add_argument(
        "--refresh-config",
        action="store_true",
        help="Run write_config collection before setup",
    )
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    if args.refresh_config:
        _refresh_config(args.region)

    config = _ensure_runtime_config()
    print(f"Project: {config.get('projectName')}")
    print(f"Region:  {config.get('region')}")
    print(f"Runtime: {config.get('agent_runtime_arn')}")

    if _LANGGRAPH_DIR not in sys.path:
        sys.path.insert(0, _LANGGRAPH_DIR)

    from installer import (  # noqa: WPS433
        create_monitoring_dashboard,
        setup_agentcore_evaluations,
        setup_agentcore_observability,
    )

    steps = [
        ("AgentCore Observability", setup_agentcore_observability),
        ("AgentCore Evaluations", setup_agentcore_evaluations),
        ("CloudWatch dashboards", create_monitoring_dashboard),
    ]
    for name, fn in steps:
        print(f"\n>>> {name}")
        ok = fn()
        if not ok:
            print(f"Failed: {name}")
            return 1

    config = _ensure_runtime_config()
    region = config.get("region", "us-west-2")
    print("\n" + "=" * 60)
    print("Observability / Evaluations / Dashboard setup complete")
    print("=" * 60)
    for key, label in (
        ("bedrock_usage_dashboard_name", "Bedrock Usage Dashboard"),
        ("cloudwatch_dashboard_name", "CloudWatch Dashboard"),
        ("online_evaluation_config_name", "Online Evaluation Config"),
        ("evaluation_log_group", "Evaluation Results Log Group"),
    ):
        value = config.get(key)
        if not value:
            continue
        print(f"{label}: {value}")
        if "dashboard" in key:
            print(
                f"  https://{region}.console.aws.amazon.com/cloudwatch/home"
                f"?region={region}#dashboards/dashboard/{value}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
