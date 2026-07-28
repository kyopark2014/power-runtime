"""Secrets Manager materials for ALB origin header and CloudFront signing."""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import custom_resources as cr
from constructs import Construct

from config import (
    PROJECT_NAME,
    alb_origin_header_secret_name,
    cloudfront_signing_key_secret_name,
    session_signing_key_secret_name,
)


class SecretsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.origin_header_secret = secretsmanager.Secret(
            self,
            "AlbOriginHeaderSecret",
            secret_name=alb_origin_header_secret_name(),
            description=f"CloudFront to ALB origin verification header for {PROJECT_NAME}",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=48,
                exclude_punctuation=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.session_signing_secret = secretsmanager.Secret(
            self,
            "SessionSigningKeySecret",
            secret_name=session_signing_key_secret_name(),
            description=f"HMAC session signing key for {PROJECT_NAME}",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64,
                exclude_punctuation=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        cf_key_fn = lambda_.Function(
            self,
            "GenerateCloudFrontSigningKeyFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.minutes(2),
            code=lambda_.Code.from_inline(_CF_SIGNING_KEY_LAMBDA),
            initial_policy=[
                iam.PolicyStatement(
                    actions=[
                        "secretsmanager:CreateSecret",
                        "secretsmanager:PutSecretValue",
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                        "cloudfront:CreatePublicKey",
                        "cloudfront:CreateKeyGroup",
                        "cloudfront:ListPublicKeys",
                        "cloudfront:ListKeyGroups",
                        "cloudfront:GetPublicKey",
                        "cloudfront:GetKeyGroup",
                    ],
                    resources=["*"],
                )
            ],
        )
        cf_provider = cr.Provider(self, "CfSigningKeyProvider", on_event_handler=cf_key_fn)
        self.cf_signing = CustomResource(
            self,
            "CloudFrontSigningMaterial",
            service_token=cf_provider.service_token,
            properties={
                "SecretName": cloudfront_signing_key_secret_name(),
                "PublicKeyName": f"{PROJECT_NAME}-cf-public-key",
                "KeyGroupName": f"{PROJECT_NAME}-cf-key-group",
                "ProjectName": PROJECT_NAME,
            },
        )

        CfnOutput(
            self,
            "AlbOriginHeaderSecretArn",
            value=self.origin_header_secret.secret_arn,
        )
        CfnOutput(
            self,
            "SessionSigningKeySecretArn",
            value=self.session_signing_secret.secret_arn,
        )
        CfnOutput(
            self,
            "CloudFrontSigningKeySecretArn",
            value=self.cf_signing.get_att_string("SecretArn"),
        )
        CfnOutput(
            self,
            "CloudFrontPublicKeyId",
            value=self.cf_signing.get_att_string("PublicKeyId"),
        )
        CfnOutput(
            self,
            "CloudFrontKeyGroupId",
            value=self.cf_signing.get_att_string("KeyGroupId"),
        )


_CF_SIGNING_KEY_LAMBDA = r'''
import json
import os
import subprocess
import tempfile
import boto3

def _gen_rsa_pem():
    with tempfile.TemporaryDirectory() as tmp:
        key_path = os.path.join(tmp, "key.pem")
        pub_path = os.path.join(tmp, "pub.pem")
        subprocess.check_call(["openssl", "genrsa", "-out", key_path, "2048"])
        subprocess.check_call(
            ["openssl", "rsa", "-in", key_path, "-pubout", "-out", pub_path]
        )
        with open(key_path, "r", encoding="utf-8") as f:
            private_pem = f.read()
        with open(pub_path, "r", encoding="utf-8") as f:
            public_pem = f.read()
    return private_pem, public_pem

def handler(event, context):
    request_type = event["RequestType"]
    props = event["ResourceProperties"]
    secret_name = props["SecretName"]
    public_key_name = props["PublicKeyName"]
    key_group_name = props["KeyGroupName"]
    physical_id = secret_name

    if request_type == "Delete":
        return {"PhysicalResourceId": physical_id, "Data": {}}

    sm = boto3.client("secretsmanager")
    cf = boto3.client("cloudfront")

    try:
        existing = sm.get_secret_value(SecretId=secret_name)
        payload = json.loads(existing["SecretString"])
        public_key_id = payload.get("public_key_id")
        key_group_id = payload.get("key_group_id")
        secret_arn = sm.describe_secret(SecretId=secret_name)["ARN"]
        if public_key_id and key_group_id:
            return {
                "PhysicalResourceId": physical_id,
                "Data": {
                    "SecretArn": secret_arn,
                    "PublicKeyId": public_key_id,
                    "KeyGroupId": key_group_id,
                },
            }
    except sm.exceptions.ResourceNotFoundException:
        pass

    private_pem, public_pem = _gen_rsa_pem()

    public_key_id = None
    marker = None
    while True:
        kwargs = {}
        if marker:
            kwargs["Marker"] = marker
        resp = cf.list_public_keys(**kwargs)
        for item in resp.get("PublicKeyList", {}).get("Items", []):
            if item.get("Name") == public_key_name:
                public_key_id = item["Id"]
                break
        marker = resp.get("PublicKeyList", {}).get("NextMarker")
        if public_key_id or not marker:
            break
    if not public_key_id:
        resp = cf.create_public_key(
            PublicKeyConfig={
                "CallerReference": f"{public_key_name}-{context.aws_request_id}",
                "Name": public_key_name,
                "EncodedKey": public_pem,
            }
        )
        public_key_id = resp["PublicKey"]["Id"]

    key_group_id = None
    marker = None
    while True:
        kwargs = {}
        if marker:
            kwargs["Marker"] = marker
        resp = cf.list_key_groups(**kwargs)
        for item in resp.get("KeyGroupList", {}).get("Items", []):
            kg = item.get("KeyGroup") or item
            conf = kg.get("KeyGroupConfig") or {}
            name = conf.get("Name") or kg.get("Name")
            if name == key_group_name:
                key_group_id = kg.get("Id")
                break
        marker = resp.get("KeyGroupList", {}).get("NextMarker")
        if key_group_id or not marker:
            break
    if not key_group_id:
        resp = cf.create_key_group(
            KeyGroupConfig={"Name": key_group_name, "Items": [public_key_id]}
        )
        key_group_id = resp["KeyGroup"]["Id"]

    payload = {
        "private_key_pem": private_pem,
        "public_key_pem": public_pem,
        "public_key_id": public_key_id,
        "key_group_id": key_group_id,
    }
    try:
        sm.create_secret(Name=secret_name, SecretString=json.dumps(payload))
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(payload))
    secret_arn = sm.describe_secret(SecretId=secret_name)["ARN"]

    return {
        "PhysicalResourceId": physical_id,
        "Data": {
            "SecretArn": secret_arn,
            "PublicKeyId": public_key_id,
            "KeyGroupId": key_group_id,
        },
    }
'''
