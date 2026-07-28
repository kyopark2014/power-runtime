"""VPC, NAT, VPC endpoints, and security groups."""

from __future__ import annotations

from typing import List

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from config import APP_PORT, PROJECT_NAME


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            f"vpc-for-{PROJECT_NAME}",
            vpc_name=f"vpc-for-{PROJECT_NAME}",
            ip_addresses=ec2.IpAddresses.cidr("10.20.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name=f"public-subnet-for-{PROJECT_NAME}",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name=f"private-subnet-for-{PROJECT_NAME}",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
            gateway_endpoints={
                "S3": ec2.GatewayVpcEndpointOptions(
                    service=ec2.GatewayVpcEndpointAwsService.S3,
                )
            },
        )

        for subnet in self.vpc.public_subnets:
            Tags.of(subnet).add("aws-cdk:subnet-type", "Public")
            Tags.of(subnet).add("aws-cdk:subnet-name", f"public-subnet-for-{PROJECT_NAME}")
        for subnet in self.vpc.private_subnets:
            Tags.of(subnet).add("aws-cdk:subnet-type", "Private")
            Tags.of(subnet).add("aws-cdk:subnet-name", f"private-subnet-for-{PROJECT_NAME}")

        self.alb_sg = ec2.SecurityGroup(
            self,
            f"alb-sg-for-{PROJECT_NAME}",
            vpc=self.vpc,
            security_group_name=f"alb-sg-for-{PROJECT_NAME}",
            description=f"ALB security group for {PROJECT_NAME}",
            allow_all_outbound=True,
        )
        # CloudFront managed prefix list (com.amazonaws.global.cloudfront.origin-facing)
        cloudfront_prefix_list = ec2.PrefixList.from_lookup(
            self,
            "CloudFrontOriginFacing",
            prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
        )
        self.alb_sg.add_ingress_rule(
            peer=ec2.Peer.prefix_list(cloudfront_prefix_list.prefix_list_id),
            connection=ec2.Port.tcp(80),
            description="CloudFront to ALB HTTP",
        )

        self.ecs_sg = ec2.SecurityGroup(
            self,
            f"ecs-sg-for-{PROJECT_NAME}",
            vpc=self.vpc,
            security_group_name=f"ecs-sg-for-{PROJECT_NAME}",
            description=f"ECS Web UI security group for {PROJECT_NAME}",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(
            peer=self.alb_sg,
            connection=ec2.Port.tcp(APP_PORT),
            description="ALB to ECS",
        )

        self.agent_runtime_sg = ec2.SecurityGroup(
            self,
            f"agent-runtime-sg-for-{PROJECT_NAME}",
            vpc=self.vpc,
            security_group_name=f"agent-runtime-sg-for-{PROJECT_NAME}",
            description=f"AgentCore Runtime security group for {PROJECT_NAME}",
            allow_all_outbound=True,
        )

        self.s3files_mount_sg = ec2.SecurityGroup(
            self,
            f"s3files-mount-sg-for-{PROJECT_NAME}",
            vpc=self.vpc,
            security_group_name=f"s3files-mount-sg-for-{PROJECT_NAME}",
            description=f"S3 Files mount target SG for {PROJECT_NAME}",
            allow_all_outbound=True,
        )
        for client_sg in (self.ecs_sg, self.agent_runtime_sg):
            self.s3files_mount_sg.add_ingress_rule(
                peer=client_sg,
                connection=ec2.Port.tcp(2049),
                description="NFS from clients",
            )

        endpoint_sg = ec2.SecurityGroup(
            self,
            f"vpce-sg-for-{PROJECT_NAME}",
            vpc=self.vpc,
            security_group_name=f"vpce-sg-for-{PROJECT_NAME}",
            description=f"VPC interface endpoints for {PROJECT_NAME}",
            allow_all_outbound=True,
        )
        for client_sg in (self.ecs_sg, self.agent_runtime_sg):
            endpoint_sg.add_ingress_rule(
                peer=client_sg,
                connection=ec2.Port.tcp(443),
                description="HTTPS from workloads",
            )

        interface_services = [
            ("EcrApi", ec2.InterfaceVpcEndpointAwsService.ECR),
            ("EcrDkr", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER),
            ("Logs", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
            ("SecretsManager", ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER),
            (
                "BedrockRuntime",
                ec2.InterfaceVpcEndpointAwsService(
                    "bedrock-runtime", port=443
                ),
            ),
            (
                "BedrockAgentCore",
                ec2.InterfaceVpcEndpointAwsService(
                    "bedrock-agentcore", port=443
                ),
            ),
            (
                "BedrockAgentCoreControl",
                ec2.InterfaceVpcEndpointAwsService(
                    "bedrock-agentcore-control", port=443
                ),
            ),
        ]
        self.interface_endpoints: List[ec2.InterfaceVpcEndpoint] = []
        for name, service in interface_services:
            endpoint = self.vpc.add_interface_endpoint(
                f"Vpce{name}",
                service=service,
                private_dns_enabled=True,
                security_groups=[endpoint_sg],
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            )
            self.interface_endpoints.append(endpoint)

        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(
            self,
            "PublicSubnetIds",
            value=",".join(s.subnet_id for s in self.vpc.public_subnets),
        )
        CfnOutput(
            self,
            "PrivateSubnetIds",
            value=",".join(s.subnet_id for s in self.vpc.private_subnets),
        )
        CfnOutput(self, "AlbSecurityGroupId", value=self.alb_sg.security_group_id)
        CfnOutput(self, "EcsSecurityGroupId", value=self.ecs_sg.security_group_id)
        CfnOutput(
            self,
            "AgentRuntimeSecurityGroupId",
            value=self.agent_runtime_sg.security_group_id,
        )
        CfnOutput(
            self,
            "S3FilesMountSecurityGroupId",
            value=self.s3files_mount_sg.security_group_id,
        )
