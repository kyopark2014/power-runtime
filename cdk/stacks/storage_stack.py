"""S3 Files session storage for AgentCore Runtime and ECS."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3files as s3files
from aws_cdk import custom_resources as cr
from constructs import Construct

from config import PROJECT_NAME, S3_FILES_SESSION_PREFIX
from stacks.network_stack import NetworkStack


class StorageStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: NetworkStack,
        bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.sync_role = iam.Role(
            self,
            f"role-s3files-sync-for-{PROJECT_NAME}",
            role_name=f"role-s3files-sync-for-{PROJECT_NAME}",
            assumed_by=iam.ServicePrincipal("elasticfilesystem.amazonaws.com"),
        )
        self.sync_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                    "s3:ListBucketVersions",
                    "s3:GetObjectVersion",
                    "s3:DeleteObjectVersion",
                ],
                resources=[bucket.bucket_arn, bucket.arn_for_objects("*")],
            )
        )
        self.sync_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "events:PutRule",
                    "events:DeleteRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:DescribeRule",
                ],
                resources=["*"],
            )
        )

        self.file_system = s3files.CfnFileSystem(
            self,
            "S3FilesFileSystem",
            bucket=bucket.bucket_arn,
            role_arn=self.sync_role.role_arn,
            prefix=S3_FILES_SESSION_PREFIX,
            accept_bucket_warning=True,
        )

        # CFN DeleteFileSystem does not pass forceDelete; pending S3 export then fails
        # stack destroy. Create order: FS → ForceDelete → MountTargets → AccessPoint.
        # Delete order: AP → MT → ForceDelete(force) → FS(already gone = success).
        force_delete = cr.AwsCustomResource(
            self,
            "S3FilesForceDelete",
            on_create=cr.AwsSdkCall(
                service="S3Files",
                action="getFileSystem",
                parameters={"fileSystemId": self.file_system.attr_file_system_id},
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"s3files-force-delete-{PROJECT_NAME}"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="S3Files",
                action="deleteFileSystem",
                parameters={
                    "fileSystemId": self.file_system.attr_file_system_id,
                    "forceDelete": True,
                },
                ignore_error_codes_matching="ResourceNotFoundException|NotFound",
            ),
            install_latest_aws_sdk=True,
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=[
                            "s3files:GetFileSystem",
                            "s3files:DeleteFileSystem",
                        ],
                        resources=["*"],
                    )
                ]
            ),
        )
        force_delete.node.add_dependency(self.file_system)

        self.mount_targets = []
        for i, subnet in enumerate(network.vpc.private_subnets):
            mt = s3files.CfnMountTarget(
                self,
                f"S3FilesMountTarget{i}",
                file_system_id=self.file_system.attr_file_system_id,
                subnet_id=subnet.subnet_id,
                security_groups=[network.s3files_mount_sg.security_group_id],
            )
            mt.node.add_dependency(force_delete)
            self.mount_targets.append(mt)

        self.access_point = s3files.CfnAccessPoint(
            self,
            "S3FilesAccessPoint",
            file_system_id=self.file_system.attr_file_system_id,
            posix_user=s3files.CfnAccessPoint.PosixUserProperty(uid="0", gid="0"),
            root_directory=s3files.CfnAccessPoint.RootDirectoryProperty(
                path="/",
                creation_permissions=s3files.CfnAccessPoint.CreationPermissionsProperty(
                    owner_uid="0",
                    owner_gid="0",
                    permissions="755",
                ),
            ),
        )
        for mt in self.mount_targets:
            self.access_point.add_dependency(mt)

        self.access_point_arn = self.access_point.attr_access_point_arn
        self.file_system_id = self.file_system.attr_file_system_id
        self.file_system_arn = self.file_system.attr_file_system_arn

        CfnOutput(self, "S3FilesFileSystemId", value=self.file_system_id)
        CfnOutput(self, "S3FilesFileSystemArn", value=self.file_system_arn)
        CfnOutput(self, "S3FilesAccessPointArn", value=self.access_point_arn)
        CfnOutput(
            self,
            "AgentRuntimeVpcSubnets",
            value=",".join(s.subnet_id for s in network.vpc.private_subnets),
        )
        CfnOutput(
            self,
            "AgentRuntimeSecurityGroups",
            value=network.agent_runtime_sg.security_group_id,
        )
