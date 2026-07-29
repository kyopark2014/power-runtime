terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    null = {
      source = "hashicorp/null"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = coalesce(var.region, data.aws_region.current.region)
  # CDK/installer parity: {project_name}_langgraph
  ecr_repo    = "${var.project_name}_langgraph"
  runtime_dir = "${var.repo_root}/runtime_agent/langgraph"
  image_tag = "tf-${substr(sha256(join("", [
    filesha256("${local.runtime_dir}/Dockerfile"),
    filesha256("${local.runtime_dir}/langgraph_agent.py"),
    filesha256("${local.runtime_dir}/mcp_config.py"),
  ])), 0, 12)}"
}

data "aws_iam_policy_document" "runtime_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name               = "AmazonBedrockAgentCoreRuntimeRoleFor${var.project_name}"
  assume_role_policy = data.aws_iam_policy_document.runtime_assume.json
}

resource "aws_iam_role_policy" "runtime" {
  name = "runtime-policy"
  role = aws_iam_role.runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3files:ClientMount",
          "s3files:ClientWrite",
          "s3files:ClientRootAccess",
        ]
        Resource = [var.s3_files_file_system_arn]
        Condition = {
          ArnEquals = {
            "s3files:AccessPointArn" = var.s3_files_access_point_arn
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["s3files:GetAccessPoint"]
        Resource = [var.s3_files_access_point_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3files:ListMountTargets"]
        Resource = [var.s3_files_file_system_arn]
      },
      {
        Sid    = "BedrockModelInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ApplyGuardrail",
          "bedrock:GetInferenceProfile",
          "bedrock:GetFoundationModel",
          "bedrock:Retrieve",
          "bedrock:RetrieveAndGenerate",
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${local.account_id}:inference-profile/*",
          "arn:aws:bedrock:${local.region}:${local.account_id}:guardrail/*",
          "arn:aws:bedrock:${local.region}:${local.account_id}:guardrail-profile/*",
          "arn:aws:bedrock:${local.region}:${local.account_id}:knowledge-base/*",
        ]
      },
      {
        Sid    = "WorkloadAccessToken"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:workload-identity-directory/default/workload-identity/*"
        ]
      },
      {
        Sid    = "ListAgentRuntimes"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:ListAgentRuntimes",
          "bedrock-agentcore-control:ListAgentRuntimes",
        ]
        Resource = ["*"]
      },
      {
        Sid    = "GetAndInvokeAgentRuntime"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore-control:GetAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:runtime/${var.agent_runtime_name}",
          "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:runtime/${var.agent_runtime_name}-*",
          "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:runtime/${var.agent_runtime_name}/runtime-endpoint/*",
          "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:runtime/${var.agent_runtime_name}-*/runtime-endpoint/*",
        ]
      },
      {
        # Remote Marketplace Tavily MCP runtime (PUBLIC, us-east-1). Parity with
        # installer.py create_aws_tavily_invoke_policy.
        Sid    = "InvokeAwsTavilyAgentRuntime"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore-control:GetAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:us-east-1:${local.account_id}:runtime/agent_runtime_aws_tavily",
          "arn:aws:bedrock-agentcore:us-east-1:${local.account_id}:runtime/agent_runtime_aws_tavily-*",
          "arn:aws:bedrock-agentcore:us-east-1:${local.account_id}:runtime/agent_runtime_aws_tavily/runtime-endpoint/*",
          "arn:aws:bedrock-agentcore:us-east-1:${local.account_id}:runtime/agent_runtime_aws_tavily-*/runtime-endpoint/*",
        ]
      },
      {
        Sid      = "ProjectS3Bucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [var.s3_bucket_arn]
      },
      {
        Sid      = "ProjectS3Objects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${var.s3_bucket_arn}/*"]
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = [
          "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:tavilyapikey-${var.project_name}*",
          "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:tavilyapikey-??????",
        ]
      },
      {
        Sid    = "ECRImagePull"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = ["*"]
      },
      {
        Sid    = "LogsAccess"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/*",
          "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/*:log-stream:*",
        ]
      },
      {
        Sid    = "VpcNetworkInterface"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeVpcs",
          "ec2:AssignPrivateIpAddresses",
          "ec2:UnassignPrivateIpAddresses",
        ]
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_bedrock_guardrail" "this" {
  name                      = "${var.project_name}-guardrail"
  blocked_input_messaging   = "Sorry, your request cannot be processed."
  blocked_outputs_messaging = "Sorry, the model response was blocked."

  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }
}

resource "aws_ecr_repository" "runtime" {
  name                 = local.ecr_repo
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

locals {
  built_image_uri = "${aws_ecr_repository.runtime.repository_url}:${local.image_tag}"
  container_uri   = var.skip_docker_build ? var.runtime_image_uri : local.built_image_uri
}

resource "null_resource" "docker_build" {
  count = var.skip_docker_build ? 0 : 1

  triggers = {
    dockerfile      = filesha256("${local.runtime_dir}/Dockerfile")
    langgraph_agent = filesha256("${local.runtime_dir}/langgraph_agent.py")
    mcp_config      = filesha256("${local.runtime_dir}/mcp_config.py")
    tag             = local.image_tag
    repo            = aws_ecr_repository.runtime.repository_url
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      REGION="${local.region}"
      REPO="${aws_ecr_repository.runtime.repository_url}"
      TAG="${local.image_tag}"
      CONTEXT="${local.runtime_dir}"
      aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
      docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
        -t "$REPO:$TAG" -t "$REPO:latest" \
        -f "$CONTEXT/Dockerfile" "$CONTEXT" --push
    EOT
  }

  depends_on = [aws_ecr_repository.runtime]
}

resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = var.agent_runtime_name
  description        = "LangGraph AgentCore Runtime for ${var.project_name}"
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.container_uri
    }
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = var.private_subnet_ids
      security_groups = [var.agent_runtime_security_group_id]
    }
  }

  filesystem_configuration {
    s3_files_access_point {
      access_point_arn = var.s3_files_access_point_arn
      mount_path       = var.session_storage_mount_path
    }
  }

  environment_variables = {
    AWS_REGION         = local.region
    AWS_DEFAULT_REGION = local.region
    KNOWLEDGE_BASE_ID  = var.knowledge_base_id
    PROJECT_NAME       = var.project_name
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  depends_on = [
    aws_iam_role_policy.runtime,
    null_resource.docker_build,
  ]
}
