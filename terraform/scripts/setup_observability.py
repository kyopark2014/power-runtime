#!/usr/bin/env python3
"""Post-Terraform setup: Observability → Evaluations → CloudWatch dashboards.

Delegates to cdk/scripts/setup_observability.py after optionally refreshing
config from Terraform outputs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def _terraform_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_root() -> str:
    return os.path.abspath(os.path.join(_terraform_dir(), ".."))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure AgentCore Observability after Terraform apply"
    )
    parser.add_argument(
        "--refresh-config",
        action="store_true",
        help="Run terraform/scripts/write_config.py before setup",
    )
    parser.add_argument("--region", default=None)
    args, unknown = parser.parse_known_args()

    if args.refresh_config:
        write_cfg = os.path.join(_terraform_dir(), "scripts", "write_config.py")
        subprocess.check_call([sys.executable, write_cfg])

    cdk_script = os.path.join(_repo_root(), "cdk", "scripts", "setup_observability.py")
    if not os.path.isfile(cdk_script):
        raise SystemExit(f"Missing {cdk_script}")

    argv = [sys.executable, cdk_script]
    if args.region:
        argv.extend(["--region", args.region])
    argv.extend(unknown)
    return subprocess.call(argv)


if __name__ == "__main__":
    raise SystemExit(main())
