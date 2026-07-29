#!/usr/bin/env python3
"""Collect Terraform outputs and write application/runtime config.json files."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict


def _terraform_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _project_root() -> str:
    return os.path.abspath(os.path.join(_terraform_dir(), ".."))


def _terraform_output(name: str) -> Any:
    result = subprocess.run(
        ["terraform", "output", "-json", name],
        cwd=_terraform_dir(),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    # `terraform output -json <name>` returns the bare value; without a name the
    # envelope is {"value": ..., "type": ..., "sensitive": ...}.
    if (
        isinstance(payload, dict)
        and "value" in payload
        and "type" in payload
        and set(payload.keys()) <= {"value", "type", "sensitive"}
    ):
        return payload["value"]
    return payload


def collect_config() -> Dict[str, Any]:
    raw = _terraform_output("config_for_write")
    if not isinstance(raw, dict):
        raise SystemExit("terraform output config_for_write did not return an object")
    config = dict(raw)
    for key in ("agent_runtime_vpc_subnets", "agent_runtime_security_groups"):
        val = config.get(key)
        if isinstance(val, str):
            config[key] = [s for s in val.split(",") if s]
        elif val is None:
            config[key] = []
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
    parser = argparse.ArgumentParser(
        description="Write config.json from Terraform outputs"
    )
    parser.add_argument(
        "--terraform-dir",
        default=None,
        help="Override terraform working directory",
    )
    args = parser.parse_args()
    if args.terraform_dir:
        os.environ.setdefault("TF_DATA_DIR", os.path.join(args.terraform_dir, ".terraform"))

    config = collect_config()
    root = _project_root()
    app_path = os.path.join(root, "application", "config.json")
    runtime_path = os.path.join(root, "runtime_agent", "langgraph", "config.json")
    write_json(app_path, config)
    write_json(runtime_path, config)
    print(f"Wrote {app_path}")
    print(f"Wrote {runtime_path}")
    print(f"sharing_url={config.get('sharing_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
