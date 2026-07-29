#!/usr/bin/env python3
"""Remove post-Terraform Observability / Evaluations / Dashboard resources.

Delegates to cdk/scripts/cleanup_observability.py. Run before `terraform destroy`.
Ignores missing resources.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _terraform_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_root() -> str:
    return os.path.abspath(os.path.join(_terraform_dir(), ".."))


def main() -> int:
    cdk_script = os.path.join(_repo_root(), "cdk", "scripts", "cleanup_observability.py")
    if not os.path.isfile(cdk_script):
        raise SystemExit(f"Missing {cdk_script}")
    return subprocess.call([sys.executable, cdk_script, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
