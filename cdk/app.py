#!/usr/bin/env python3
"""CDK app entrypoint for power-runtime infrastructure."""

from __future__ import annotations

import os

import aws_cdk as cdk

from config import (
    PROJECT_NAME,
    REGION,
    stack_name,
)
from stacks.agentcore_stack import AgentCoreStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.edge_stack import EdgeStack
from stacks.network_stack import NetworkStack
from stacks.secrets_stack import SecretsStack
from stacks.storage_stack import StorageStack

app = cdk.App()

account = os.environ.get("CDK_DEFAULT_ACCOUNT") or app.node.try_get_context("account")
region = os.environ.get("CDK_DEFAULT_REGION") or app.node.try_get_context("region") or REGION

primary_env = cdk.Environment(account=account, region=region)

network = NetworkStack(
    app,
    stack_name("network"),
    env=primary_env,
    description=f"VPC networking for {PROJECT_NAME}",
)

data = DataStack(
    app,
    stack_name("data"),
    env=primary_env,
    description=f"S3, S3 Vectors, Knowledge Base for {PROJECT_NAME}",
)

secrets = SecretsStack(
    app,
    stack_name("secrets"),
    env=primary_env,
    description=f"Signing secrets for {PROJECT_NAME}",
)

storage = StorageStack(
    app,
    stack_name("storage"),
    env=primary_env,
    network=network,
    bucket=data.bucket,
    description=f"S3 Files session storage for {PROJECT_NAME}",
)
storage.add_stack_dependency(network)
storage.add_stack_dependency(data)

edge = EdgeStack(
    app,
    stack_name("edge"),
    env=primary_env,
    network=network,
    secrets=secrets,
    bucket=data.bucket,
    description=f"ALB and CloudFront for {PROJECT_NAME}",
)
edge.add_stack_dependency(network)
edge.add_stack_dependency(secrets)
edge.add_stack_dependency(data)

agent = AgentCoreStack(
    app,
    stack_name("agentcore"),
    env=primary_env,
    network=network,
    storage=storage,
    data=data,
    description=f"AgentCore Runtime for {PROJECT_NAME}",
)
agent.add_stack_dependency(network)
agent.add_stack_dependency(storage)
agent.add_stack_dependency(data)

compute = ComputeStack(
    app,
    stack_name("compute"),
    env=primary_env,
    network=network,
    data=data,
    secrets=secrets,
    storage=storage,
    edge=edge,
    agent=agent,
    description=f"ECS Web UI for {PROJECT_NAME}",
)
compute.add_stack_dependency(network)
compute.add_stack_dependency(data)
compute.add_stack_dependency(secrets)
compute.add_stack_dependency(storage)
compute.add_stack_dependency(edge)
compute.add_stack_dependency(agent)

app.synth()
