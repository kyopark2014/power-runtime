# Copyright 2026 Amazon.com, Inc. or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""S3 Files: session (Runtime) + app-data (ECS) file systems."""

from __future__ import annotations

from typing import List, Tuple

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3files as s3files
from aws_cdk import custom_resources as cr
from constructs import Construct

from config import (
    PROJECT_NAME,
    S3_FILES_APP_DATA_PREFIX,
    S3_FILES_SESSION_PREFIX,
)
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
                sid="EventBridgeS3FilesSyncRules",
                actions=[
                    "events:PutRule",
                    "events:DeleteRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:DescribeRule",
                ],
                resources=[
                    (
                        f"arn:aws:events:{self.region}:{self.account}:"
                        f"rule/{PROJECT_NAME}-*"
                    ),
                    (
                        f"arn:aws:events:{self.region}:{self.account}:"
                        "rule/s3files-*"
                    ),
                ],
            )
        )

        (
            self.file_system,
            self.mount_targets,
            self.access_point,
        ) = self._provision_filesystem(
            id_prefix="S3Files",
            prefix=S3_FILES_SESSION_PREFIX,
            bucket_arn=bucket.bucket_arn,
            network=network,
        )
        (
            self.app_data_file_system,
            self.app_data_mount_targets,
            self.app_data_access_point,
        ) = self._provision_filesystem(
            id_prefix="S3FilesAppData",
            prefix=S3_FILES_APP_DATA_PREFIX,
            bucket_arn=bucket.bucket_arn,
            network=network,
        )

        self.access_point_arn = self.access_point.attr_access_point_arn
        self.file_system_id = self.file_system.attr_file_system_id
        self.file_system_arn = self.file_system.attr_file_system_arn
        self.app_data_access_point_arn = (
            self.app_data_access_point.attr_access_point_arn
        )
        self.app_data_file_system_id = self.app_data_file_system.attr_file_system_id
        self.app_data_file_system_arn = self.app_data_file_system.attr_file_system_arn

        CfnOutput(self, "S3FilesFileSystemId", value=self.file_system_id)
        CfnOutput(self, "S3FilesFileSystemArn", value=self.file_system_arn)
        CfnOutput(self, "S3FilesAccessPointArn", value=self.access_point_arn)
        CfnOutput(
            self, "S3FilesAppDataFileSystemId", value=self.app_data_file_system_id
        )
        CfnOutput(
            self, "S3FilesAppDataFileSystemArn", value=self.app_data_file_system_arn
        )
        CfnOutput(
            self,
            "S3FilesAppDataAccessPointArn",
            value=self.app_data_access_point_arn,
        )
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

    def _provision_filesystem(
        self,
        *,
        id_prefix: str,
        prefix: str,
        bucket_arn: str,
        network: NetworkStack,
    ) -> Tuple[
        s3files.CfnFileSystem,
        List[s3files.CfnMountTarget],
        s3files.CfnAccessPoint,
    ]:
        file_system = s3files.CfnFileSystem(
            self,
            f"{id_prefix}FileSystem",
            bucket=bucket_arn,
            role_arn=self.sync_role.role_arn,
            prefix=prefix,
            accept_bucket_warning=True,
        )

        force_delete = cr.AwsCustomResource(
            self,
            f"{id_prefix}ForceDelete",
            on_create=cr.AwsSdkCall(
                service="S3Files",
                action="getFileSystem",
                parameters={"fileSystemId": file_system.attr_file_system_id},
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"s3files-force-delete-{id_prefix.lower()}-{PROJECT_NAME}"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="S3Files",
                action="deleteFileSystem",
                parameters={
                    "fileSystemId": file_system.attr_file_system_id,
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
        force_delete.node.add_dependency(file_system)

        mount_targets: List[s3files.CfnMountTarget] = []
        for i, subnet in enumerate(network.vpc.private_subnets):
            mt = s3files.CfnMountTarget(
                self,
                f"{id_prefix}MountTarget{i}",
                file_system_id=file_system.attr_file_system_id,
                subnet_id=subnet.subnet_id,
                security_groups=[network.s3files_mount_sg.security_group_id],
            )
            mt.node.add_dependency(force_delete)
            mount_targets.append(mt)

        access_point = s3files.CfnAccessPoint(
            self,
            f"{id_prefix}AccessPoint",
            file_system_id=file_system.attr_file_system_id,
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
        for mt in mount_targets:
            access_point.add_dependency(mt)

        return file_system, mount_targets, access_point
