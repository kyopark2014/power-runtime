"""S3 storage, S3 Vectors, and Bedrock Knowledge Base."""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import custom_resources as cr
from constructs import Construct

from config import (
    BEDROCK_NON_FILTERABLE_METADATA_KEYS,
    DISTANCE_METRIC,
    EMBEDDING_DATA_TYPE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ARN_TEMPLATE,
    PROJECT_NAME,
    VECTOR_INDEX_NAME,
    s3_vectors_bucket_arn,
    s3_vectors_index_arn,
    storage_bucket_name,
    vector_bucket_name,
)


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket_name = storage_bucket_name(self.account, self.region)
        self.bucket = s3.Bucket(
            self,
            f"storage-for-{PROJECT_NAME}",
            bucket_name=bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.GET,
                        s3.HttpMethods.POST,
                        s3.HttpMethods.PUT,
                    ],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                )
            ],
        )

        cr.AwsCustomResource(
            self,
            "DocsPrefixObject",
            on_create=cr.AwsSdkCall(
                service="S3",
                action="putObject",
                parameters={
                    "Bucket": self.bucket.bucket_name,
                    "Key": "docs/",
                    "Body": "",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"{bucket_name}-docs-prefix"
                ),
            ),
            install_latest_aws_sdk=False,
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
        )

        vb_name = vector_bucket_name(self.account)
        vector_bucket_arn = s3_vectors_bucket_arn(self.account, self.region, vb_name)
        vector_index_arn = s3_vectors_index_arn(
            self.account, self.region, VECTOR_INDEX_NAME, vb_name
        )

        self.kb_role = iam.Role(
            self,
            f"role-knowledge-base-for-{PROJECT_NAME}",
            role_name=f"role-knowledge-base-for-{PROJECT_NAME}-{self.region}",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            inline_policies={
                f"kb-s3-policy-for-{PROJECT_NAME}": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["s3:ListBucket", "s3:GetBucketLocation"],
                            resources=[self.bucket.bucket_arn],
                        ),
                        iam.PolicyStatement(
                            actions=["s3:GetObject"],
                            resources=[self.bucket.arn_for_objects("*")],
                        ),
                    ]
                ),
                f"kb-bedrock-policy-for-{PROJECT_NAME}": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                                "bedrock:GetInferenceProfile",
                                "bedrock:GetFoundationModel",
                            ],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/*",
                                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                                f"arn:aws:bedrock:{self.region}:*:inference-profile/*",
                            ],
                        )
                    ]
                ),
                f"kb-s3vectors-policy-for-{PROJECT_NAME}": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="S3VectorsAccess",
                            actions=[
                                "s3vectors:GetVectorBucket",
                                "s3vectors:ListVectorBuckets",
                                "s3vectors:GetIndex",
                                "s3vectors:ListIndexes",
                                "s3vectors:QueryVectors",
                                "s3vectors:GetVectors",
                                "s3vectors:PutVectors",
                                "s3vectors:DeleteVectors",
                                "s3vectors:ListVectors",
                            ],
                            resources=[
                                vector_bucket_arn,
                                f"{vector_bucket_arn}/index/*",
                            ],
                        )
                    ]
                ),
            },
        )
        self.kb_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("bedrock.amazonaws.com")],
                actions=["sts:AssumeRole"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"
                        )
                    },
                },
            )
        )

        s3_vectors_fn = lambda_.Function(
            self,
            "CreateS3VectorsStoreFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="index.handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            code=lambda_.Code.from_inline(_S3_VECTORS_LAMBDA),
            initial_policy=[
                iam.PolicyStatement(
                    actions=[
                        "s3vectors:CreateVectorBucket",
                        "s3vectors:GetVectorBucket",
                        "s3vectors:DeleteVectorBucket",
                        "s3vectors:CreateIndex",
                        "s3vectors:GetIndex",
                        "s3vectors:DeleteIndex",
                        "s3vectors:ListIndexes",
                    ],
                    resources=["*"],
                )
            ],
        )
        s3_vectors_provider = cr.Provider(
            self,
            "S3VectorsStoreProvider",
            on_event_handler=s3_vectors_fn,
        )
        self.s3_vectors = CustomResource(
            self,
            "S3VectorsStore",
            service_token=s3_vectors_provider.service_token,
            properties={
                "VectorBucketName": vb_name,
                "IndexName": VECTOR_INDEX_NAME,
                "Dimension": EMBEDDING_DIMENSIONS,
                "DataType": EMBEDDING_DATA_TYPE,
                "DistanceMetric": DISTANCE_METRIC,
                "NonFilterableMetadataKeys": BEDROCK_NON_FILTERABLE_METADATA_KEYS,
                "Region": self.region,
            },
        )

        self.vector_bucket_name = self.s3_vectors.get_att_string("VectorBucketName")
        self.vector_bucket_arn = self.s3_vectors.get_att_string("VectorBucketArn")
        self.vector_index_name = self.s3_vectors.get_att_string("IndexName")
        self.vector_index_arn = self.s3_vectors.get_att_string("IndexArn")

        embedding_model_arn = EMBEDDING_MODEL_ARN_TEMPLATE.format(region=self.region)
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            f"kb-for-{PROJECT_NAME}",
            name=PROJECT_NAME,
            description="Knowledge base with default parser (S3 Vectors)",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_model_arn,
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBEDDING_DIMENSIONS,
                            embedding_data_type="FLOAT32",
                        )
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=self.vector_bucket_arn,
                    index_arn=self.vector_index_arn,
                ),
            ),
        )
        self.knowledge_base.node.add_dependency(self.s3_vectors)
        self.knowledge_base.node.add_dependency(self.kb_role)

        self.data_source = bedrock.CfnDataSource(
            self,
            f"kb-datasource-for-{PROJECT_NAME}",
            name=bucket_name,
            description=f"S3 data source: {bucket_name}",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_deletion_policy="RETAIN",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.bucket.bucket_arn,
                    inclusion_prefixes=["docs/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300,
                        overlap_percentage=20,
                    ),
                )
            ),
        )

        CfnOutput(self, "S3BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "S3BucketArn", value=self.bucket.bucket_arn)
        CfnOutput(self, "KnowledgeBaseId", value=self.knowledge_base.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=self.data_source.attr_data_source_id)
        CfnOutput(self, "KnowledgeBaseRoleArn", value=self.kb_role.role_arn)
        CfnOutput(self, "VectorBucketName", value=self.vector_bucket_name)
        CfnOutput(self, "VectorBucketArn", value=self.vector_bucket_arn)
        CfnOutput(self, "VectorIndexName", value=self.vector_index_name)
        CfnOutput(self, "VectorIndexArn", value=self.vector_index_arn)


_S3_VECTORS_LAMBDA = r'''
import time
import boto3
from botocore.exceptions import ClientError

def handler(event, context):
    request_type = event["RequestType"]
    props = event["ResourceProperties"]
    bucket_name = props["VectorBucketName"]
    index_name = props["IndexName"]
    region = props.get("Region") or context.invoked_function_arn.split(":")[3]
    dimension = int(props.get("Dimension", 1024))
    data_type = props.get("DataType", "float32")
    distance_metric = props.get("DistanceMetric", "cosine")
    non_filterable = props.get("NonFilterableMetadataKeys") or [
        "AMAZON_BEDROCK_TEXT",
        "AMAZON_BEDROCK_METADATA",
    ]
    physical_id = f"{bucket_name}/{index_name}"
    client = boto3.client("s3vectors", region_name=region)

    def _bucket_arn():
        acct = context.invoked_function_arn.split(":")[4]
        return f"arn:aws:s3vectors:{region}:{acct}:bucket/{bucket_name}"

    def _index_arn():
        return f"{_bucket_arn()}/index/{index_name}"

    if request_type == "Delete":
        try:
            client.delete_index(vectorBucketName=bucket_name, indexName=index_name)
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "NotFoundException",
                "ResourceNotFoundException",
                "NoSuchIndex",
            ):
                raise
        try:
            client.delete_vector_bucket(vectorBucketName=bucket_name)
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "NotFoundException",
                "ResourceNotFoundException",
                "NoSuchBucket",
                "ConflictException",
            ):
                raise
        return {"PhysicalResourceId": physical_id, "Data": {}}

    vector_bucket_arn = _bucket_arn()
    index_arn = _index_arn()

    try:
        client.create_vector_bucket(vectorBucketName=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] not in (
            "ConflictException",
            "ResourceAlreadyExistsException",
        ):
            raise
        try:
            existing = client.get_vector_bucket(vectorBucketName=bucket_name)
            vector_bucket_arn = existing["vectorBucket"]["vectorBucketArn"]
        except ClientError:
            pass

    try:
        response = client.create_index(
            vectorBucketName=bucket_name,
            indexName=index_name,
            dataType=data_type,
            dimension=dimension,
            distanceMetric=distance_metric,
            metadataConfiguration={"nonFilterableMetadataKeys": non_filterable},
        )
        index_arn = response.get("indexArn", index_arn)
        time.sleep(10)
    except ClientError as e:
        if e.response["Error"]["Code"] not in (
            "ConflictException",
            "ResourceAlreadyExistsException",
        ):
            raise
        try:
            existing = client.get_index(
                vectorBucketName=bucket_name, indexName=index_name
            )
            index_arn = existing["index"]["indexArn"]
            vector_bucket_arn = existing["index"].get(
                "vectorBucketArn", vector_bucket_arn
            )
        except ClientError:
            pass

    return {
        "PhysicalResourceId": physical_id,
        "Data": {
            "VectorBucketName": bucket_name,
            "VectorBucketArn": vector_bucket_arn,
            "IndexName": index_name,
            "IndexArn": index_arn,
        },
    }
'''
