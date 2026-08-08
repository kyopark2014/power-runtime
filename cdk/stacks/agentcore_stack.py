"""AgentCore Runtime, IAM role, Guardrail, and runtime ECR image."""

from __future__ import annotations

import os

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3files as s3files
from constructs import Construct

from config import (
    PROJECT_NAME,
    SESSION_STORAGE_MOUNT_PATH,
    agent_runtime_name,
    runtime_ecr_repository_name,
)
from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.data_stack import DataStack


class AgentCoreStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: NetworkStack,
        storage: StorageStack,
        data: DataStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        runtime_dir = os.path.join(repo_root, "runtime_agent", "langgraph")
        skip_docker = str(self.node.try_get_context("skipDockerBuild") or "").lower() in (
            "1",
            "true",
            "yes",
        )

        self.runtime_role = iam.Role(
            self,
            f"AgentCoreRuntimeRole",
            role_name=f"AmazonBedrockAgentCoreRuntimeRoleFor{PROJECT_NAME}",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "S3FilesAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "s3files:ClientMount",
                                "s3files:ClientWrite",
                                "s3files:ClientRootAccess",
                            ],
                            resources=[storage.file_system_arn],
                            conditions={
                                "ArnEquals": {
                                    "s3files:AccessPointArn": storage.access_point_arn,
                                }
                            },
                        ),
                        iam.PolicyStatement(
                            actions=["s3files:GetAccessPoint"],
                            resources=[storage.access_point_arn],
                        ),
                        iam.PolicyStatement(
                            actions=["s3files:ListMountTargets"],
                            resources=[storage.file_system_arn],
                        ),
                    ]
                )
            },
        )
        runtime_name = agent_runtime_name()

        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockModelInvoke",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail",
                    "bedrock:GetInferenceProfile",
                    "bedrock:GetFoundationModel",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:guardrail/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:guardrail-profile/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*",
                ],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="WorkloadAccessToken",
                actions=[
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                resources=[
                    (
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:"
                        "workload-identity-directory/default/workload-identity/*"
                    ),
                ],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="ListAgentRuntimes",
                actions=[
                    "bedrock-agentcore:ListAgentRuntimes",
                    "bedrock-agentcore-control:ListAgentRuntimes",
                ],
                resources=["*"],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="GetAndInvokeAgentRuntime",
                actions=[
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore-control:GetAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
                ],
                resources=[
                    (
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:"
                        f"runtime/{runtime_name}"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:"
                        f"runtime/{runtime_name}-*"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:"
                        f"runtime/{runtime_name}/runtime-endpoint/*"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:"
                        f"runtime/{runtime_name}-*/runtime-endpoint/*"
                    ),
                ],
            )
        )
        # Remote Marketplace Tavily MCP runtime (PUBLIC, us-east-1).
        # Parity with installer.py create_aws_tavily_invoke_policy.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeAwsTavilyAgentRuntime",
                actions=[
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore-control:GetAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
                ],
                resources=[
                    (
                        f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:"
                        "runtime/agent_runtime_aws_tavily"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:"
                        "runtime/agent_runtime_aws_tavily-*"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:"
                        "runtime/agent_runtime_aws_tavily/runtime-endpoint/*"
                    ),
                    (
                        f"arn:aws:bedrock-agentcore:us-east-1:{self.account}:"
                        "runtime/agent_runtime_aws_tavily-*/runtime-endpoint/*"
                    ),
                ],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="ProjectS3BucketMeta",
                actions=["s3:GetBucketLocation"],
                resources=[data.bucket.bucket_arn],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="ProjectS3ListAllowedPrefixes",
                actions=["s3:ListBucket"],
                resources=[data.bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            "artifacts",
                            "artifacts/*",
                            "images",
                            "images/*",
                            "docs",
                            "docs/*",
                        ]
                    }
                },
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="ProjectS3Objects",
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[
                    data.bucket.arn_for_objects("artifacts/*"),
                    data.bucket.arn_for_objects("images/*"),
                    data.bucket.arn_for_objects("docs/*"),
                ],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="DenySensitiveS3Prefixes",
                effect=iam.Effect.DENY,
                actions=[
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:DeleteObjectVersion",
                ],
                resources=[
                    data.bucket.arn_for_objects("app-data/*"),
                    data.bucket.arn_for_objects("agentcore-sessions/*"),
                ],
            )
        )
        # Session FS policy: Runtime only (ECS uses dedicated app-data FS).
        s3files.CfnFileSystemPolicy(
            self,
            "S3FilesSessionFileSystemPolicy",
            file_system_id=storage.file_system_id,
            policy={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": self.runtime_role.role_arn},
                        "Action": [
                            "s3files:ClientMount",
                            "s3files:ClientWrite",
                            "s3files:ClientRootAccess",
                        ],
                        "Condition": {
                            "StringEquals": {
                                "s3files:AccessPointArn": storage.access_point_arn,
                            }
                        },
                    }
                ],
            },
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="SecretsManagerRead",
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                resources=[
                    (
                        f"arn:aws:secretsmanager:{self.region}:{self.account}:"
                        f"secret:tavilyapikey-{PROJECT_NAME}*"
                    ),
                    (
                        f"arn:aws:secretsmanager:{self.region}:{self.account}:"
                        "secret:tavilyapikey-??????"
                    ),
                ],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRImagePull",
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                resources=["*"],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="LogsAccess",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    (
                        f"arn:aws:logs:{self.region}:{self.account}:"
                        "log-group:/aws/bedrock-agentcore/*"
                    ),
                    (
                        f"arn:aws:logs:{self.region}:{self.account}:"
                        "log-group:/aws/bedrock-agentcore/*:log-stream:*"
                    ),
                ],
            )
        )
        # OTEL → X-Ray / CloudWatch metrics. Parity with installer.py +
        # AgentCore runtime execution-role docs (sampling APIs).
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchMetricsAndXRay",
                actions=[
                    "cloudwatch:PutMetricData",
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:PutAttributes",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="VpcNetworkInterface",
                actions=[
                    "ec2:CreateNetworkInterface",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DeleteNetworkInterface",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeVpcs",
                    "ec2:AssignPrivateIpAddresses",
                    "ec2:UnassignPrivateIpAddresses",
                ],
                resources=["*"],
            )
        )

        self.guardrail = bedrock.CfnGuardrail(
            self,
            f"guardrail-for-{PROJECT_NAME}",
            name=f"{PROJECT_NAME}-guardrail",
            blocked_input_messaging="Sorry, your request cannot be processed.",
            blocked_outputs_messaging="Sorry, the model response was blocked.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="HATE",
                        input_strength="MEDIUM",
                        output_strength="MEDIUM",
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="VIOLENCE",
                        input_strength="MEDIUM",
                        output_strength="MEDIUM",
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="SEXUAL",
                        input_strength="MEDIUM",
                        output_strength="MEDIUM",
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="MISCONDUCT",
                        input_strength="MEDIUM",
                        output_strength="MEDIUM",
                    ),
                ]
            ),
        )

        # Project-scoped ECR (installer parity: {project_name}_langgraph).
        runtime_repo = ecr.Repository(
            self,
            "RuntimeEcrRepo",
            repository_name=runtime_ecr_repository_name(),
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True,
        )
        runtime_repo.grant_pull(self.runtime_role)

        if skip_docker:
            # Expect an already-pushed image URI via context
            image_uri = self.node.try_get_context("runtimeImageUri")
            if not image_uri:
                raise ValueError(
                    "skipDockerBuild requires -c runtimeImageUri="
                    f"{runtime_repo.repository_uri}:<tag>"
                )
            container_uri = image_uri
        else:
            runtime_image = ecr_assets.DockerImageAsset(
                self,
                "RuntimeImage",
                directory=runtime_dir,
                platform=ecr_assets.Platform.LINUX_ARM64,
                file="Dockerfile",
            )
            container_uri = runtime_image.image_uri

        self.runtime = agentcore.CfnRuntime(
            self,
            "AgentRuntime",
            agent_runtime_name=runtime_name,
            role_arn=self.runtime_role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=container_uri,
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="VPC",
                network_mode_config=agentcore.CfnRuntime.VpcConfigProperty(
                    subnets=[s.subnet_id for s in network.vpc.private_subnets],
                    security_groups=[network.agent_runtime_sg.security_group_id],
                ),
            ),
            filesystem_configurations=[
                agentcore.CfnRuntime.FilesystemConfigurationProperty(
                    s3_files_access_point=agentcore.CfnRuntime.S3FilesAccessPointConfigurationProperty(
                        access_point_arn=storage.access_point_arn,
                        mount_path=SESSION_STORAGE_MOUNT_PATH,
                    )
                )
            ],
            environment_variables={
                "AWS_REGION": self.region,
                "AWS_DEFAULT_REGION": self.region,
                "KNOWLEDGE_BASE_ID": data.knowledge_base.attr_knowledge_base_id,
                "PROJECT_NAME": PROJECT_NAME,
            },
            protocol_configuration="HTTP",
            description=f"LangGraph AgentCore Runtime for {PROJECT_NAME}",
        )
        # Runtime validates role permissions at create-time; wait for all policies.
        self.runtime.node.add_dependency(self.runtime_role)
        default_policy = self.runtime_role.node.try_find_child("DefaultPolicy")
        if default_policy is not None:
            self.runtime.node.add_dependency(default_policy)

        CfnOutput(self, "AgentRuntimeArn", value=self.runtime.attr_agent_runtime_arn)
        CfnOutput(self, "AgentRuntimeId", value=self.runtime.attr_agent_runtime_id)
        CfnOutput(self, "AgentRuntimeRoleArn", value=self.runtime_role.role_arn)
        CfnOutput(self, "GuardrailId", value=self.guardrail.attr_guardrail_id)
        CfnOutput(self, "GuardrailArn", value=self.guardrail.attr_guardrail_arn)
        CfnOutput(self, "RuntimeEcrRepositoryName", value=runtime_repo.repository_name)
        CfnOutput(self, "RuntimeEcrRepositoryUri", value=runtime_repo.repository_uri)
        CfnOutput(self, "RuntimeImageUri", value=container_uri)
