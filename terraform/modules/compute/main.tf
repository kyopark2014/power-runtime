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
  ecr_repo   = "ecr-for-${var.project_name}"
  image_tag  = "tf-${substr(filesha256("${var.repo_root}/Dockerfile"), 0, 12)}"
  built_uri  = "${aws_ecr_repository.web.repository_url}:${local.image_tag}"
  image_uri  = var.skip_docker_build ? var.web_image_uri : local.built_uri
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "role-ecs-task-for-${var.project_name}-${local.region}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role" "execution" {
  name               = "role-ecs-execution-for-${var.project_name}-${local.region}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "execution-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = [
        var.session_signing_key_secret_arn,
        var.cloudfront_signing_key_secret_arn,
      ]
    }]
  })
}

# No Cognito IAM — power-runtime Web UI uses plain user_id sessions.
resource "aws_iam_role_policy" "task" {
  name = "task-policy"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
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
        ]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntimeWithWebResponse",
          "bedrock-agentcore:GetAgentRuntime",
          "bedrock-agentcore-control:GetAgentRuntime",
          "bedrock-agentcore:ListAgentRuntimes",
          "bedrock-agentcore-control:ListAgentRuntimes",
        ]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [var.s3_bucket_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${var.s3_bucket_arn}/*"]
      },
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
      }
    ]
  })
}

resource "aws_s3files_file_system_policy" "this" {
  file_system_id = var.s3_files_file_system_id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        AWS = [
          var.agent_runtime_role_arn,
          aws_iam_role.task.arn,
        ]
      }
      Action = [
        "s3files:ClientMount",
        "s3files:ClientWrite",
        "s3files:ClientRootAccess",
      ]
      Condition = {
        StringEquals = {
          "s3files:AccessPointArn" = var.s3_files_access_point_arn
        }
      }
    }]
  })
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/app-for-${var.project_name}"
  retention_in_days = 30
}

resource "aws_ecr_repository" "web" {
  name                 = local.ecr_repo
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "null_resource" "docker_build" {
  count = var.skip_docker_build ? 0 : 1

  triggers = {
    dockerfile = filesha256("${var.repo_root}/Dockerfile")
    tag        = local.image_tag
    repo       = aws_ecr_repository.web.repository_url
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      REGION="${local.region}"
      REPO="${aws_ecr_repository.web.repository_url}"
      TAG="${local.image_tag}"
      CONTEXT="${var.repo_root}"
      cp -f "$CONTEXT/runtime_agent/langgraph/mcp.list" "$CONTEXT/application/mcp.list" 2>/dev/null || true
      # Rebuild application/skills.list from skills/*/SKILL.md (runtime has no skills.list)
      SKILLS_DIR="$CONTEXT/runtime_agent/langgraph/skills"
      LIST_PATH="$CONTEXT/application/skills.list"
      : > "$LIST_PATH"
      if [ -d "$SKILLS_DIR" ]; then
        for d in "$SKILLS_DIR"/*; do
          [ -d "$d" ] && [ -f "$d/SKILL.md" ] || continue
          basename "$d"
        done | LC_ALL=C sort -u > "$LIST_PATH"
      fi
      aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
      docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
        -t "$REPO:$TAG" -t "$REPO:latest" \
        -f "$CONTEXT/Dockerfile" "$CONTEXT" --push
    EOT
  }

  depends_on = [aws_ecr_repository.web]
}

resource "aws_ecs_cluster" "this" {
  name = "cluster-for-${var.project_name}"
}

resource "aws_ecs_task_definition" "app" {
  family                   = "task-for-${var.project_name}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  volume {
    name = "app-data"
    s3files_volume_configuration {
      file_system_arn  = var.s3_files_file_system_arn
      access_point_arn = var.s3_files_access_point_arn
      root_directory   = "/"
    }
  }

  container_definitions = jsonencode([{
    name      = "app"
    image     = local.image_uri
    essential = true
    portMappings = [{
      containerPort = var.app_port
      protocol      = "tcp"
    }]
    environment = [
      { name = "APP_CONFIG_JSON", value = jsonencode(var.app_config) },
      { name = "CLOUDFRONT_KEY_PAIR_ID", value = var.cloudfront_public_key_id },
      { name = "TASK_DB_MOUNT", value = var.app_data_mount_path },
      { name = "TASK_DB_PROJECT", value = var.project_name },
      # Same S3 Files root as AgentCore /mnt/workspace (skills.list, skills/).
      { name = "SESSION_STORAGE_DIR", value = var.app_data_mount_path },
    ]
    secrets = [
      {
        name      = "SESSION_SIGNING_KEY"
        valueFrom = var.session_signing_key_secret_arn
      },
      {
        name      = "CLOUDFRONT_SIGNING_PRIVATE_KEY"
        valueFrom = "${var.cloudfront_signing_key_secret_arn}:private_key_pem::"
      },
    ]
    mountPoints = [{
      sourceVolume  = "app-data"
      containerPath = var.app_data_mount_path
      readOnly      = false
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${var.app_port}/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  depends_on = [
    null_resource.docker_build,
    aws_iam_role_policy.task,
    aws_iam_role_policy.execution_secrets,
    aws_s3files_file_system_policy.this,
  ]
}

resource "aws_ecs_service" "app" {
  name            = "service-for-${var.project_name}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "app"
    container_port   = var.app_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  depends_on = [aws_ecs_task_definition.app]
}
