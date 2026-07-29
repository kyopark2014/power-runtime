"""Shared deployment constants (parity with installer.py)."""

from __future__ import annotations

import os

PROJECT_NAME = os.environ.get("CDE_PROJECT_NAME", "power-runtime")
REGION = os.environ.get("CDE_REGION", "us-west-2")

SSE_ORIGIN_READ_TIMEOUT_SECONDS = 600
ALB_IDLE_TIMEOUT_SECONDS = 600
CUSTOM_HEADER_NAME = "X-Custom-Header"
APP_PORT = 8501
S3_FILES_SESSION_PREFIX = "agentcore-sessions/"
SESSION_STORAGE_MOUNT_PATH = "/mnt/workspace"
APP_DATA_MOUNT_PATH = "/mnt/app-data"

VECTOR_INDEX_NAME = PROJECT_NAME
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_DATA_TYPE = "float32"
DISTANCE_METRIC = "cosine"
BEDROCK_NON_FILTERABLE_METADATA_KEYS = [
    "AMAZON_BEDROCK_TEXT",
    "AMAZON_BEDROCK_METADATA",
]
EMBEDDING_MODEL_ARN_TEMPLATE = (
    "arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
)


def agent_runtime_name(project_name: str = PROJECT_NAME) -> str:
    return project_name.replace("-", "_")


def storage_bucket_name(account_id: str, region: str = REGION) -> str:
    return f"storage-for-{PROJECT_NAME}-{account_id}-{region}"


def vector_bucket_name(account_id: str, project_name: str = PROJECT_NAME) -> str:
    return f"{project_name}-{account_id}"


def s3_vectors_bucket_arn(
    account_id: str,
    region: str = REGION,
    bucket_name: str | None = None,
) -> str:
    name = bucket_name or vector_bucket_name(account_id)
    return f"arn:aws:s3vectors:{region}:{account_id}:bucket/{name}"


def s3_vectors_index_arn(
    account_id: str,
    region: str = REGION,
    index_name: str = VECTOR_INDEX_NAME,
    bucket_name: str | None = None,
) -> str:
    return f"{s3_vectors_bucket_arn(account_id, region, bucket_name)}/index/{index_name}"


def alb_origin_header_secret_name(project_name: str = PROJECT_NAME) -> str:
    return f"{project_name}/cloudfront-alb-origin-header"


def session_signing_key_secret_name(project_name: str = PROJECT_NAME) -> str:
    return f"{project_name}/session-signing-key"


def cloudfront_signing_key_secret_name(project_name: str = PROJECT_NAME) -> str:
    return f"{project_name}/cloudfront-signing-key"


def stack_name(suffix: str, project_name: str = PROJECT_NAME) -> str:
    return f"{project_name}-{suffix}"


def web_ecr_repository_name(project_name: str = PROJECT_NAME) -> str:
    """ECR repository for the ECS Web UI image."""
    return f"ecr-for-{project_name}"


def runtime_ecr_repository_name(project_name: str = PROJECT_NAME) -> str:
    """ECR repository for the AgentCore LangGraph runtime image."""
    return f"{project_name}_langgraph"
