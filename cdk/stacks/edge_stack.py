"""ALB and CloudFront edge distribution."""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_s3 as s3
from constructs import Construct

from config import (
    ALB_IDLE_TIMEOUT_SECONDS,
    APP_PORT,
    CUSTOM_HEADER_NAME,
    PROJECT_NAME,
    SSE_ORIGIN_READ_TIMEOUT_SECONDS,
)
from stacks.network_stack import NetworkStack
from stacks.secrets_stack import SecretsStack


class EdgeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: NetworkStack,
        secrets: SecretsStack,
        bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            f"alb-for-{PROJECT_NAME}",
            load_balancer_name=f"alb-for-{PROJECT_NAME}",
            vpc=network.vpc,
            internet_facing=True,
            security_group=network.alb_sg,
            vpc_subnets={"subnets": network.vpc.public_subnets},
            idle_timeout=Duration.seconds(ALB_IDLE_TIMEOUT_SECONDS),
        )

        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            f"tg-ecs-for-{PROJECT_NAME}",
            target_group_name=f"tg-ecs-for-{PROJECT_NAME}"[:32],
            vpc=network.vpc,
            port=APP_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/api/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            # app_cookie on agent_user_id — avoids AWSALB/AWSALBCORS (no Secure/HttpOnly)
            stickiness_cookie_duration=Duration.days(1),
            stickiness_cookie_name="agent_user_id",
        )

        origin_header_value = secrets.origin_header_secret.secret_value.unsafe_unwrap()

        self.listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=403,
                content_type="text/plain",
                message_body="Forbidden",
            ),
        )
        self.listener.add_action(
            "ForwardWithOriginHeader",
            priority=10,
            conditions=[
                elbv2.ListenerCondition.http_header(
                    CUSTOM_HEADER_NAME,
                    [origin_header_value],
                )
            ],
            action=elbv2.ListenerAction.forward([self.target_group]),
        )

        key_group_id = secrets.cf_signing.get_att_string("KeyGroupId")
        key_group = cloudfront.KeyGroup.from_key_group_id(
            self, "ImportedKeyGroup", key_group_id
        )

        alb_origin = origins.LoadBalancerV2Origin(
            self.alb,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            http_port=80,
            read_timeout=Duration.seconds(SSE_ORIGIN_READ_TIMEOUT_SECONDS),
            custom_headers={CUSTOM_HEADER_NAME: origin_header_value},
        )

        s3_origin = origins.S3BucketOrigin.with_origin_access_identity(bucket)

        self.distribution = cloudfront.Distribution(
            self,
            f"cf-for-{PROJECT_NAME}",
            comment=f"Distribution for {PROJECT_NAME}",
            default_behavior=cloudfront.BehaviorOptions(
                origin=alb_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
            additional_behaviors={
                path: cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                    trusted_key_groups=[key_group],
                    response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                )
                for path in ("/images/*", "/docs/*", "/artifacts/*")
            },
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
        )

        CfnOutput(self, "AlbDnsName", value=self.alb.load_balancer_dns_name)
        CfnOutput(self, "AlbArn", value=self.alb.load_balancer_arn)
        CfnOutput(self, "TargetGroupArn", value=self.target_group.target_group_arn)
        CfnOutput(self, "CloudFrontDomain", value=self.distribution.distribution_domain_name)
        CfnOutput(
            self,
            "CloudFrontDistributionId",
            value=self.distribution.distribution_id,
        )
        CfnOutput(
            self,
            "SharingUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
        )
