# power-runtime Terraform

AWS 인프라를 Terraform으로 배포합니다. CDK([`../cdk`](../cdk/))와 동일한 리소스 구성을 모듈로 포팅했습니다.

루트 `installer.py`(boto3)와 CDK와 **병행 선택** 가능합니다. 같은 계정·같은 `project_name`으로 동시에 배포하지 마세요(이름 충돌).

## 구성

| 모듈 | 리전 | 역할 |
|------|------|------|
| `network` | primary | VPC, NAT, VPC Endpoint, SG |
| `data` | primary | S3, **S3 Vectors**, Bedrock KB |
| `secrets` | primary | ALB origin / session / CloudFront signing (**Cognito 없음**) |
| `storage` | primary | S3 Files (`/mnt/workspace`) |
| `edge` | primary | ALB, CloudFront |
| `agentcore` | primary | LangGraph Runtime, Guardrail, ECR |
| `compute` | primary | ECS Fargate Web UI, ECR |

의존성: `network`/`data`/`secrets` → `storage`/`edge` → `agentcore` → `compute`

Provider: **hashicorp/aws >= 6.47.0** (AgentCore Runtime filesystem + S3 Files + S3 Vectors)

### cde-pilot Terraform과의 주요 차이

| 항목 | cde-pilot | power-runtime |
|------|-----------|---------------|
| Auth | Cognito User Pool + admin | **없음** (Web UI는 `user_id` 세션) |
| Secrets | `auth` 모듈에 Cognito+secrets | `secrets` 모듈만 |
| Vector store | OpenSearch Serverless | **S3 Vectors** |
| Gateway | AgentCore Web Search (`us-east-1`) | 없음 |
| Memory | AgentCore Memory | 없음 |
| Runtime | Strands (`runtime_agent/strands`) | LangGraph (`runtime_agent/langgraph`) |
| Runtime ECR | `ecr-runtime-for-{project}` | `{project}_langgraph` |

## 사전 준비

| 항목 | 설명 |
|------|------|
| Terraform | 1.5+ |
| AWS 자격 증명 | primary 리전 권한 |
| Docker | `linux/arm64` 빌드 (`docker buildx`) — `skip_docker_build` 시 불필요 |
| Python 3 | post-deploy 스크립트 |

## 배포

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# project_name / region 확인

terraform init
terraform apply

# Outputs → application/config.json + runtime_agent/langgraph/config.json
python3 scripts/write_config.py

# Observability / Evaluations / Dashboard (CDK와 동일, 1회)
python3 scripts/setup_observability.py --refresh-config
```

접속: `terraform output sharing_url` → Web UI에서 `user_id` 입력 후 세션 시작.

## Docker 이미지

기본값: apply 중 `null_resource`가 ECR에 ARM64 이미지를 빌드·푸시합니다.

- Runtime: `runtime_agent/langgraph/Dockerfile` → `{project}_langgraph`
- Web UI: 루트 `Dockerfile` → `ecr-for-{project}`

빌드를 건너뛰려면:

```hcl
skip_docker_build = true
runtime_image_uri = "ACCOUNT.dkr.ecr.REGION.amazonaws.com/power-runtime_langgraph:tag"
web_image_uri     = "ACCOUNT.dkr.ecr.REGION.amazonaws.com/ecr-for-power-runtime:tag"
```

## 주요 변수

| 변수 | 기본 | 설명 |
|------|------|------|
| `project_name` | `power-runtime` | 리소스 이름 prefix |
| `region` | `us-west-2` | primary 리전 |
| `skip_docker_build` | `false` | Docker 빌드 스킵 |
| `runtime_image_uri` / `web_image_uri` | `""` | skip 시 필수 |

## 삭제

```bash
terraform destroy
```

S3 버킷·S3 Vectors는 `force_destroy=true`입니다. CloudFront 삭제는 수 분이 걸릴 수 있습니다.

## CDK / boto3와의 차이

- CloudFront 서명키: Terraform `tls_private_key` (CDK는 Lambda custom resource)
- S3 Vectors: Terraform `aws_s3vectors_*` (CDK는 Lambda custom resource)
- Observability: 스택에 포함하지 않음 — `scripts/setup_observability.py` (CDK와 동일)
