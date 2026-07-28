# power-runtime CDK

Python AWS CDK app that provisions power-runtime infrastructure (VPC, S3 Vectors KB, S3 Files, ALB/CloudFront, AgentCore LangGraph Runtime, ECS).

루트 `installer.py` / `uninstaller.py`는 **사용하지 않습니다**. CDK가 완성되면 해당 boto3 스크립트는 삭제할 예정입니다.

## Deploy

```bash
cd cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 최초 1회
npx aws-cdk@2 bootstrap

# Docker Desktop: docker-container buildx 드라이버면 CDK 이미지 push가
# "tag does not exist"로 실패할 수 있음. 배포 전 docker 드라이버로 전환:
#   docker buildx use desktop-linux

# 배포
npx aws-cdk@2 deploy --all --app "python3 app.py"

# 삭제
npx aws-cdk@2 destroy --all --app "python3 app.py" --force
```

컨테이너 이미지는 프로젝트명이 포함된 ECR 리포지토리를 생성합니다.

- Web UI: `ecr-for-{project_name}` (예: `ecr-for-power-runtime`)
- AgentCore Runtime: `{project_name}_langgraph` (예: `power-runtime_langgraph`)

`skipDockerBuild` 시 위 리포지토리에 미리 push한 이미지를 `-c webImageUri` / `-c runtimeImageUri`로 지정합니다. CDK `DockerImageAsset` 빌드 경로는 공유 bootstrap ECR에도 이미지를 올립니다.

스택 목록: `network`, `data` (S3 + S3 Vectors KB), `secrets`, `storage`, `edge`, `agentcore` (LangGraph), `compute`.

Outputs를 config에 쓰려면:

```bash
python3 scripts/write_config.py
```

이 스크립트는 `application/config.json`과 `runtime_agent/langgraph/config.json`을 갱신합니다.

Knowledge Base RAG는 AgentCore Runtime 환경변수 `KNOWLEDGE_BASE_ID`(Data 스택의 KB ID)로 연결됩니다.
