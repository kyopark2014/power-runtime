"""ECS Fargate Web UI service."""

from __future__ import annotations

import json
import os

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3files as s3files
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config import (
    APP_DATA_MOUNT_PATH,
    APP_PORT,
    PROJECT_NAME,
    cloudfront_signing_key_secret_name,
    web_ecr_repository_name,
)
from stacks.agentcore_stack import AgentCoreStack
from stacks.data_stack import DataStack
from stacks.edge_stack import EdgeStack
from stacks.network_stack import NetworkStack
from stacks.secrets_stack import SecretsStack
from stacks.storage_stack import StorageStack


class ComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: NetworkStack,
        data: DataStack,
        secrets: SecretsStack,
        storage: StorageStack,
        edge: EdgeStack,
        agent: AgentCoreStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        skip_docker = str(self.node.try_get_context("skipDockerBuild") or "").lower() in (
            "1",
            "true",
            "yes",
        )

        self.task_role = iam.Role(
            self,
            "EcsTaskRole",
            role_name=f"role-ecs-task-for-{PROJECT_NAME}-{self.region}",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        self.execution_role = iam.Role(
            self,
            "EcsExecutionRole",
            role_name=f"role-ecs-execution-for-{PROJECT_NAME}-{self.region}",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )

        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail",
                    "bedrock:GetInferenceProfile",
                    "bedrock:GetFoundationModel",
                    "bedrock:StartIngestionJob",
                    "bedrock:ListIngestionJobs",
                    "bedrock:GetIngestionJob",
                    "bedrock-mantle:Get*",
                    "bedrock-mantle:List*",
                    "bedrock-mantle:CreateInference",
                    "bedrock-mantle:CallWithBearerToken",
                ],
                resources=["*"],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore-control:GetAgentRuntime",
                    "bedrock-agentcore:ListAgentRuntimes",
                    "bedrock-agentcore-control:ListAgentRuntimes",
                ],
                resources=["*"],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket", "s3:GetBucketLocation"],
                resources=[data.bucket.bucket_arn],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[data.bucket.arn_for_objects("*")],
            )
        )
        self.task_role.add_to_policy(
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
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3files:GetAccessPoint"],
                resources=[storage.access_point_arn],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3files:ListMountTargets"],
                resources=[storage.file_system_arn],
            )
        )

        s3files.CfnFileSystemPolicy(
            self,
            "S3FilesFileSystemPolicy",
            file_system_id=storage.file_system_id,
            policy={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "AWS": [
                                agent.runtime_role.role_arn,
                                self.task_role.role_arn,
                            ]
                        },
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

        secrets.session_signing_secret.grant_read(self.execution_role)
        cf_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "CfSigningSecret",
            cloudfront_signing_key_secret_name(),
        )
        cf_secret.grant_read(self.execution_role)

        log_group = logs.LogGroup(
            self,
            "EcsLogGroup",
            log_group_name=f"/ecs/app-for-{PROJECT_NAME}",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH,
        )

        # Project-scoped ECR (installer parity: ecr-for-{project_name}).
        web_repo = ecr.Repository(
            self,
            "WebEcrRepo",
            repository_name=web_ecr_repository_name(),
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True,
        )
        web_repo.grant_pull(self.execution_role)

        if skip_docker:
            image_uri = self.node.try_get_context("webImageUri")
            if not image_uri:
                raise ValueError(
                    "skipDockerBuild requires -c webImageUri="
                    f"{web_repo.repository_uri}:<tag>"
                )
            container_image = ecs.ContainerImage.from_registry(image_uri)
            resolved_image_uri = image_uri
        else:
            web_image = ecr_assets.DockerImageAsset(
                self,
                "WebUiImage",
                directory=repo_root,
                file="Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
                exclude=[
                    "cdk/cdk.out",
                    "cdk/.venv",
                    "**/__pycache__",
                    ".git",
                    "contents",
                ],
            )
            container_image = ecs.ContainerImage.from_docker_image_asset(web_image)
            resolved_image_uri = web_image.image_uri

        app_config = {
            "projectName": PROJECT_NAME,
            "accountId": self.account,
            "region": self.region,
            "knowledge_base_id": data.knowledge_base.attr_knowledge_base_id,
            "data_source_id": data.data_source.attr_data_source_id,
            "knowledge_base_role": data.kb_role.role_arn,
            "collectionArn": "",
            "opensearch_url": "",
            "vector_bucket_name": data.vector_bucket_name,
            "vector_bucket_arn": data.vector_bucket_arn,
            "vector_index_name": data.vector_index_name,
            "vector_index_arn": data.vector_index_arn,
            "s3_bucket": data.bucket.bucket_name,
            "s3_arn": data.bucket.bucket_arn,
            "sharing_url": f"https://{edge.distribution.distribution_domain_name}",
            "s3_files_file_system_id": storage.file_system_id,
            "s3_files_access_point_arn": storage.access_point_arn,
            "agent_runtime_vpc_subnets": [
                s.subnet_id for s in network.vpc.private_subnets
            ],
            "agent_runtime_security_groups": [
                network.agent_runtime_sg.security_group_id
            ],
            "agent_runtime_arn": agent.runtime.attr_agent_runtime_arn,
            "agent_runtime_role": agent.runtime_role.role_arn,
        }

        cluster = ecs.Cluster(
            self,
            f"cluster-for-{PROJECT_NAME}",
            cluster_name=f"cluster-for-{PROJECT_NAME}",
            vpc=network.vpc,
        )

        task_def = ecs.FargateTaskDefinition(
            self,
            f"task-for-{PROJECT_NAME}",
            family=f"task-for-{PROJECT_NAME}",
            cpu=1024,
            memory_limit_mib=2048,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_role=self.task_role,
            execution_role=self.execution_role,
        )

        cfn_task: ecs.CfnTaskDefinition = task_def.node.default_child  # type: ignore
        cfn_task.add_property_override(
            "Volumes",
            [
                {
                    "Name": "app-data",
                    "S3FilesVolumeConfiguration": {
                        "FileSystemArn": storage.file_system_arn,
                        "AccessPointArn": storage.access_point_arn,
                        "RootDirectory": "/",
                    },
                }
            ],
        )

        container = task_def.add_container(
            "app",
            image=container_image,
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ecs",
                log_group=log_group,
            ),
            environment={
                "APP_CONFIG_JSON": json.dumps(app_config),
                "CLOUDFRONT_KEY_PAIR_ID": secrets.cf_signing.get_att_string("PublicKeyId"),
                "TASK_DB_MOUNT": APP_DATA_MOUNT_PATH,
                "TASK_DB_PROJECT": PROJECT_NAME,
            },
            secrets={
                "SESSION_SIGNING_KEY": ecs.Secret.from_secrets_manager(
                    secrets.session_signing_secret
                ),
                "CLOUDFRONT_SIGNING_PRIVATE_KEY": ecs.Secret.from_secrets_manager(
                    cf_secret, field="private_key_pem"
                ),
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    f"curl -f http://localhost:{APP_PORT}/api/health || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )
        container.add_port_mappings(
            ecs.PortMapping(container_port=APP_PORT, protocol=ecs.Protocol.TCP)
        )
        container.add_mount_points(
            ecs.MountPoint(
                container_path=APP_DATA_MOUNT_PATH,
                source_volume="app-data",
                read_only=False,
            )
        )

        service = ecs.FargateService(
            self,
            f"service-for-{PROJECT_NAME}",
            service_name=f"service-for-{PROJECT_NAME}",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=False,
            security_groups=[network.ecs_sg],
            vpc_subnets={"subnets": network.vpc.private_subnets},
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
            max_healthy_percent=200,
        )
        service.attach_to_application_target_group(edge.target_group)

        CfnOutput(self, "EcsClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EcsServiceName", value=service.service_name)
        CfnOutput(self, "WebEcrRepositoryName", value=web_repo.repository_name)
        CfnOutput(self, "WebEcrRepositoryUri", value=web_repo.repository_uri)
        CfnOutput(self, "WebImageUri", value=resolved_image_uri)
        CfnOutput(self, "AppConfigJson", value=json.dumps(app_config))
