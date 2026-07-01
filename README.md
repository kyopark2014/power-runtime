# Power Agent의 AgentCore 배포 및 활용

여기에서는 Streamlit app은 Amazon ECS에 배포하고, Agent는 AgentCore Runtime을 활용해 배포합니다. 

## 주요 구현 

### 전체 Architecture

전체적인 Architecture는 아래와 같습니다. 여기서는 MCP/SKILL를 지원하는 LangGraph agent를 [AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)를 이용해 배포하고, Amazon ECS에 배포된 streamlit 애플리케이션에서 활용합니다. AWS 인프라는 루트 [installer.py](./installer.py)로 배포하고, LangGraph agent 이미지는 [Dockerfile](./runtime_agent/langgraph/Dockerfile)로 빌드한 뒤 [installer.py](./runtime_agent/langgraph/installer.py)로 AgentCore Runtime에 배포합니다. Streamlit UI는 루트 [Dockerfile](./Dockerfile)로 ECS에 배포하며, Agent 추론은 AgentCore에서 수행합니다. 애플리케이션에서 AgentCore의 runtime을 호출할 때에는 [bedrock-agentcore](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore.html)의 [invoke_agent_runtime](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html)을 이용합니다. 이때에 각 agent를 생성할 때에 확인할 수 있는 [agentRuntimeArn](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_Agent.html)을 이용합니다. Agent는 [MCP](https://modelcontextprotocol.io/introduction)을 이용해 RAG, AWS Document, Tavily와 같은 검색 서비스를 활용할 수 있습니다. RAG는 Bedrock Knowledge Base와 S3 Vectors를 사용하며, Agent에 필요한 S3, CloudFront, VPC, ECS, ECR 등의 배포는 루트 [installer.py](./installer.py)로 수행합니다.

<img width="1000" alt="image" src="https://github.com/user-attachments/assets/3a4bea0c-edb3-4eb5-8f2b-a071f03fd6d3" />

AgentCore의 runtime은 배포를 위해 Docker를 이용합니다. 현재(2025.7) 기준으로 arm64와 1GB 이하의 docker image를 지원합니다.
 
### Operation Architecture

Streamlit UI(`application/app.py`)에서 MCP·Skill·모델·대화 모드를 선택하면 `application/agentcore_client.py`가 AgentCore Runtime(`invoke_agent_runtime`)으로 요청을 보냅니다. Runtime은 `runtime_agent/langgraph/agent.py`의 `BedrockAgentCoreApp` 엔트리포인트에서 LangGraph 워크플로우를 실행하고, 선택된 MCP는 `runtime_agent/langgraph/mcp_config.py`에 따라 **동일 컨테이너 내 stdio 서브프로세스**로 기동됩니다. Skill은 `runtime_agent/langgraph/skills/`의 `SKILL.md`와 `get_skill_instructions` 도구로 제공되며, MCP와는 별도 체계입니다.

```mermaid
flowchart TB
  subgraph UI["Streamlit app.py"]
    MODE["Mode: Agent or Agent Chat"]
    SEL["Select MCP Skill Model"]
  end

  subgraph Client["agentcore_client.py"]
    RA[run_agent]
    RD["run_agent_in_docker local"]
  end

  subgraph Runtime["AgentCore runtime_agent/langgraph"]
    AG["agent.py BedrockAgentCoreApp"]
    CHAT["chat.py AsyncSqliteSaver bind_memory"]
    LGA["langgraph_agent.py StateGraph astream"]
  end

  subgraph BuiltIn["Built in tools"]
    LGB["execute_code bash read_file write_file upload_file_to_s3 get_current_time"]
  end

  subgraph Skills["Skills skill.py skills"]
    SKM[SkillManager]
    SKT[get_skill_instructions]
    SKD["docx pptx xlsx pdf skill_creator and more"]
  end

  subgraph MCPConfig["MCP config mcp_config.py"]
    LSC[load_selected_config]
  end

  subgraph MCPLocal["MCP servers stdio subprocess same container"]
    TV["tavily web search"]
    KB["knowledge base RAG retrieve"]
    AD["aws documentation uvx"]
    TI["trade info stock trend"]
    WF["web_fetch npx"]
    IG[image generation]
    UC["user config"]
  end

  subgraph MCPClient["langchain mcp adapters"]
    LGM[MultiServerMCPClient]
  end

  subgraph LLM["Amazon Bedrock runtime"]
    BR[Bedrock Runtime]
  end

  subgraph Storage["Artifacts and S3"]
    ART[artifacts]
    S3[(S3)]
  end

  MODE --> RA
  SEL --> RA
  RD -.-> AG

  RA --> AG
  AG --> CHAT
  CHAT --> LGA
  LGA --> BR
  LGA --> LGB
  LGA --> LGM
  LGA --> SKT

  SKT --> SKM
  SKM --> SKD

  AG --> LSC
  LSC --> MCPLocal
  LGM --> MCPLocal

  LGB --> ART
  LGB --> S3
```

| 모드 | 모듈 | 설명 |
|------|------|------|
| **Agent** | `application/app.py` → `agentcore_client.run_agent` | 단일 턴 Agent. `history_mode=Disable`로 매 요청을 독립 처리 |
| **Agent (Chat)** | `application/app.py` → `agentcore_client.run_agent` | 대화 이력 유지. `history_mode=Enable`로 세션 기반 interactive 대화 |
| LangGraph Runtime | `runtime_agent/langgraph/agent.py` | LangGraph StateGraph + `MultiServerMCPClient` + 내장 도구 |
| Skill | `runtime_agent/langgraph/skill.py` · `runtime_agent/langgraph/skills/` | `SKILL.md` 기반 지침. UI `application/skills.list`에서 선택 후 `get_skill_instructions`로 로드 |
| MCP (로컬 stdio) | `runtime_agent/langgraph/mcp_server_*.py` | Agent 컨테이너 안에서 subprocess로 기동 (`runtime_agent/langgraph/mcp_config.py`가 command/args 정의) |
| Streamlit 앱 | 루트 `Dockerfile` → ECS | Streamlit용 최소 패키지. Agent 추론은 AgentCore에서 수행 |

UI에서 MCP는 `application/mcp.list` 기준으로 `tavily`, `knowledge base`, `aws documentation`, `trade info`, `web_fetch`, `image generation`, `사용자 설정`을 체크박스로 선택합니다. Skill은 `application/skills.list`에서 `docx`, `pptx`, `xlsx`, `skill-creator` 등을 별도로 선택합니다. 로컬 개발 시에는 `application/agentcore_client.py`의 `run_agent_in_docker`로 `runtime_agent/langgraph/Dockerfile` 이미지(`localhost:8080`)에 직접 요청할 수 있습니다.

### 네트워크 설정

`power-runtime`은 **ECS(Streamlit UI)** 와 **AgentCore Runtime(LangGraph 서버)** 가 모두 **private subnet** 에 배포됩니다. 이 환경에서는 인터넷으로 직접 나가지 않으므로, AWS API 호출은 **VPC Interface/Gateway Endpoint** 로, 외부 MCP·npm·cross-region 트래픽은 **NAT Gateway** 로 egress 를 열어야 합니다.

[installer.py](./installer.py) 가 신규 VPC 생성뿐 아니라 **기존 VPC 재사용 시**에도 아래 리소스를 자동으로 맞춥니다.

#### 구성 요약

```text
[사용자] → CloudFront → ALB (public subnet)
                              ↓
                    ECS App (private subnet)
                              ↓ bedrock-agentcore VPC Endpoint
                    AgentCore Runtime (private subnet, VPC mode)
                              ↓
              MCP: aws-tavily (us-east-1 Runtime) / web_fetch (npm)
                              ↓ NAT Gateway (public subnet 경유)
                         Internet
```

| 구성 요소 | Subnet | 인터넷 egress |
|-----------|--------|----------------|
| ALB | Public | IGW |
| ECS Fargate | Private | VPC Endpoint + NAT |
| AgentCore Runtime | Private | VPC Endpoint + NAT |

#### VPC Interface Endpoint (us-west-2)

Private subnet 워크로드가 **같은 리전(us-west-2)** AWS API 에 도달할 때 사용합니다. `ensure_private_subnet_vpc_endpoints()` 가 생성·재사용합니다.

| AWS 서비스 | Endpoint 서비스 이름 | 용도 |
|------------|----------------------|------|
| Amazon ECR API | `com.amazonaws.us-west-2.ecr.api` | ECS/Runtime 이미지 pull 메타데이터 |
| Amazon ECR DKR | `com.amazonaws.us-west-2.ecr.dkr` | 컨테이너 이미지 레이어 pull |
| CloudWatch Logs | `com.amazonaws.us-west-2.logs` | ECS·Runtime 로그 전송 |
| Secrets Manager | `com.amazonaws.us-west-2.secretsmanager` | Runtime cold start 시 Tavily API 키 로드 ([runtime_agent/langgraph/utils.py](./runtime_agent/langgraph/utils.py)) |
| Bedrock AgentCore | `com.amazonaws.us-west-2.bedrock-agentcore` | ECS → `invoke_agent_runtime` |
| Bedrock AgentCore Control | `com.amazonaws.us-west-2.bedrock-agentcore-control` | Runtime ARN 검증, gateway 조회 |
| Amazon Bedrock Runtime | `com.amazonaws.us-west-2.bedrock-runtime` | LangGraph 모델 호출 (별도 생성) |
| Amazon S3 | `com.amazonaws.us-west-2.s3` (Gateway) | ECR 레이어·아티팩트·스토리지 |

Endpoint 는 private subnet 에 배치되며, ECS security group 과 Agent Runtime security group 모두 ingress(443) 를 허용해야 합니다.

#### NAT Gateway 와 private route table

아래 트래픽은 **VPC Endpoint 만으로는 처리할 수 없습니다.** Public subnet 에 **NAT Gateway** 를 두고, private subnet 전용 route table 에 `0.0.0.0/0 → NAT` 를 연결합니다 (`ensure_private_subnet_nat_routing()`).

| 트래픽 | 이유 |
|--------|------|
| **aws-tavily MCP** | 별도 AgentCore Runtime 이 **us-east-1** 에 있음. us-west-2 VPC Endpoint 로는 **다른 리전 Runtime HTTPS** 에 도달 불가 |
| **aws-tavily Runtime ARN 조회** | [runtime_agent/langgraph/mcp_config.py](./runtime_agent/langgraph/mcp_config.py) 가 `bedrock-agentcore-control` **us-east-1** API 호출 (`list_agent_runtimes`) |
| **Web_fetch MCP** | `npx -y mcp-server-fetch-typescript` 가 **npm registry** (`registry.npmjs.org`) 접속 필요 |
| **aws documentation MCP** | `uvx awslabs.aws-documentation-mcp-server` 가 PyPI 접속 필요 |
| **외부 URL fetch** | web_fetch·일반 HTTP 도구가 public 인터넷 대상에 접근 |

채팅 UI 기본 MCP 가 `['web_fetch', 'aws-tavily']` 이므로, **NAT 없이** 배포하면 MCP 초기화 단계에서 요청이 멈춘 것처럼 보일 수 있습니다. MCP 없이 동작 확인 시 payload 에 `mcp_servers: []` 를 사용할 수 있습니다.

#### aws-tavily / Web_fetch 동작 경로

**aws-tavily** ([runtime_agent/langgraph/mcp_config.py](./runtime_agent/langgraph/mcp_config.py) → `aws-tavily`):

1. `bedrock-agentcore-control` us-east-1 에서 `agent_runtime_aws_tavily` Runtime ARN 조회  
2. `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/.../invocations` 로 MCP streamable HTTP 연결 (SigV4)

**Web_fetch** (`mcp_config.py` → `web_fetch`):

1. `npx` 로 `mcp-server-fetch-typescript` 패키지 다운로드 (인터넷)  
2. 런타임 중 대상 URL HTTP fetch (인터넷)

#### installer 자동 설정

루트 [installer.py](./installer.py) 실행 시 네트워크 관련 단계:

1. **VPC** — public/private subnet, security group  
2. **NAT Gateway** — public subnet 에 생성, private subnet → `private-rt-{project}` 연결  
3. **VPC Endpoint** — 위 표의 Interface/Gateway Endpoint  
4. **Agent Runtime VPC** — Runtime 을 private subnet + 전용 SG 로 배포 (`networkMode: VPC`)  
5. **S3 Files** — 세션 스토리지(NFS)용 mount target  

기존 VPC 를 재사용해도 private subnet 이 이미 있으면 NAT·route table 연결을 **다시 검증·보완**합니다.

#### 증상별 점검

| 증상 | CloudWatch 로그 힌트 | 확인 사항 |
|------|----------------------|-----------|
| UI 는 열리나 채팅 무응답 | ECS: `agentcore_client` 이후 로그 없음 | `bedrock-agentcore`, `bedrock-agentcore-control` Endpoint |
| Runtime cold start 120초 초과 | Runtime: `utils.py` 까지만 반복 | `secretsmanager` Endpoint |
| MCP 로드 후 멈춤 | Runtime: `mcp_servers: ['web_fetch', 'aws-tavily']` 이후 정지 | **NAT Gateway**, private route `0.0.0.0/0 → NAT` |
| aws-tavily 만 실패 | us-east-1 Runtime 관련 timeout | NAT + IAM(bedrock-agentcore) |

로그 그룹:

- ECS UI: `/ecs/app-for-power-runtime`  
- Agent Runtime: `/aws/bedrock-agentcore/runtimes/power_runtime_langgraph-*-DEFAULT`

#### 비용 참고

- **VPC Interface Endpoint**: 시간당·데이터 처리 요금  
- **NAT Gateway**: 시간당 요금 + NAT 처리 데이터 요금 (aws-tavily/web_fetch 사용 시 발생)

운영 환경에서 MCP 를 쓰지 않는다면 NAT 없이 VPC Endpoint 만으로도 기본 채팅(`mcp_servers: []`)은 가능합니다. aws-tavily·Web_fetch 를 쓰려면 NAT 구성을 권장합니다.

### AgentCore 소개

- AgentCore Runtime: AI agent와 tool을 배포하고 트래픽에 따라 자동으로 확장(Scaling)이 가능한 serverless runtime입니다. LangGraph, CrewAI, Strands Agents를 포함한 다양한 오픈소스 프레임워크을 지원합니다. 빠른 cold start, 세션 격리, 내장된 신원 확인(built-in identity), multimodal payload를 지원합니다. 이를 통해 안전하고 빠른 출시가 가능합니다.
- AgentCore Memory: Agent가 편리하게 short term, long term 메모리를 관리할 수 있습니다.
- AgentCore Code Interpreter: 분리된 sandbox 환경에서 안전하게 코드를 실행할 수 있습니다.
- AgentCore Broswer: 브라우저를 이용해 빠르고 안전하게 웹크롤링과 같은 작업을 수행할 수 있습니다.
- AgentCore Gateway: API, Lambda를 비롯한 서비스들을 쉽게 Tool로 활용할 수 있습니다.
- AgentCore Observability: 상용 환경에서 개발자가 agent의 동작을 trace, debug, monitor 할 수 있습니다.



## Agent 구현

AgentCore는 SSE 방식의 stream을 제공합니다. 

### LangGraph Agent

아래는 LangGraph로 구현한 ReAct agent입니다. 

```python
def buildChatAgentWithHistory(tools):
    tool_node = ToolNode(tools)

    workflow = StateGraph(State)

    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "action",
            "end": END,
        },
    )
    workflow.add_edge("action", "agent")

    return workflow.compile(
        checkpointer=chat.checkpointer
    )
```


[runtime_agent/langgraph/agent.py](./runtime_agent/langgraph/agent.py)와 같이 stream 방식으로 처리하면 agent가 좀 더 동적으로 동작하게 할 수 있습니다. 아래와 같이 MCP 서버의 정보로 json 파일을 만든 후에 MultiServerMCPClient으로 client를 설정하고 나서 agent를 생성합니다. 이후 stream을 이용해 출력할때 json 형태의 결과값을 stream으로 전달합니다. 

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
async def agent_langgraph(payload):
    mcp_json = mcp_config.load_selected_config(mcp_servers)
    server_params = load_multiple_mcp_server_parameters(mcp_json)
    client = MultiServerMCPClient(server_params)

    app = buildChatAgentWithHistory(tools)
    config = {
        "recursion_limit": 50,
        "configurable": {"thread_id": user_id},
        "tools": tools
    }    
    inputs = {
        "messages": [HumanMessage(content=query)]
    }
            
    value = None
    async for output in app.astream(inputs, config):
        for key, value in output.items():
            logger.info(f"--> key: {key}, value: {value}")

            if "messages" in value:
                for message in value["messages"]:
                    if isinstance(message, AIMessage):
                        yield({'data': message.content})
                        tool_calls = message.tool_calls
                        if tool_calls:
                            for tool_call in tool_calls:
                                tool_name = tool_call["name"]
                                tool_content = tool_call["args"]
                                toolUseId = tool_call["id"]
                                yield({'tool': tool_name, 'input': tool_content, 'toolUseId': toolUseId})
                    elif isinstance(message, ToolMessage):
                        toolResult = message.content
                        toolUseId = message.tool_call_id
                        yield({'toolResult': toolResult, 'toolUseId': toolUseId})
```

### Client

AgentCore로 agent_runtime_arn을 이용해 request에 대한 응답을 얻습니다. 이때 content-type이 "text/event-stream"인 경우에 prefix인 "data:"를 제거한 후에 json parser를 이용해 얻어진 값을 목적에 맞게 활용합니다.

```python
agent_core_client = boto3.client('bedrock-agentcore', region_name=bedrock_region)
response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn=agent_runtime_arn,
    runtimeSessionId=runtime_session_id,
    payload=payload,
    qualifier="DEFAULT" # DEFAULT or LATEST
)

result = current = ""
processed_data = set()  # Prevent duplicate data

# stream response
if "text/event-stream" in response.get("contentType", ""):
    for line in response["response"].iter_lines(chunk_size=10):
        line = line.decode("utf-8")        
        if line.startswith('data: '):
            data = line[6:].strip()  # Remove "data:" prefix and whitespace
            if data:  # Only process non-empty data
                # Check for duplicate data
                if data in processed_data:
                    continue
                processed_data.add(data)
                
                data_json = json.loads(data)
                if 'data' in data_json:
                    text = data_json['data']
                    logger.info(f"[data] {text}")
                    current += text
                    containers['result'].markdown(current)
                elif 'result' in data_json:
                    result = data_json['result']
                elif 'tool' in data_json:
                    tool = data_json['tool']
                    input = data_json['input']
                    toolUseId = data_json['toolUseId']
                    if toolUseId not in tool_info_list: # new tool info
                        tool_info_list[toolUseId] = index                                        
                        add_notification(containers, f"Tool: {tool}, Input: {input}")
                    else: # overwrite tool info
                        containers['notification'][tool_info_list[toolUseId]].info(f"Tool: {tool}, Input: {input}")                    
                elif 'toolResult' in data_json:
                    toolResult = data_json['toolResult']
                    toolUseId = data_json['toolUseId']
                    if toolUseId not in tool_result_list:  # new tool result
                        tool_result_list[toolUseId] = index
                        add_notification(containers, f"Tool Result: {toolResult}")
                    else: # overwrite tool result
                        containers['notification'][tool_result_list[toolUseId]].info(f"Tool Result: {toolResult}")
```

## 코드 구조

프로젝트는 **Streamlit UI(`application/`)** 와 **LangGraph Agent Runtime(`runtime_agent/langgraph/`)** 으로 나뉩니다. UI는 ECS에서 사용자 입력·MCP/Skill 선택·스트리밍 결과 표시만 담당하고, Agent 추론·MCP·Skill 실행은 AgentCore Runtime 컨테이너에서 수행합니다.

### `application/` — Streamlit UI (ECS)

루트 [Dockerfile](./Dockerfile)로 빌드되어 ECS에 배포됩니다. AgentCore Runtime을 `invoke_agent_runtime`으로 호출하며, Agent 로직은 포함하지 않습니다.

```text
application/
├── app.py                  # Streamlit 진입점. 모드·MCP·Skill·모델 선택, 채팅 UI
├── agentcore_client.py     # AgentCore Runtime 호출 (invoke_agent_runtime, SSE 파싱)
├── chat.py                 # UI 세션·대화 상태 관리
├── utils.py                # config.json 로드, 공통 유틸
├── notification_queue.py   # 도구 호출·스트리밍 알림 큐
├── info.py                 # 앱 메타 정보
├── bedrock_data_retention.py
├── mcp.list                # UI MCP 체크박스 목록 (Runtime의 mcp.list와 대응)
├── skills.list             # UI Skill 체크박스 목록 (Runtime의 skills.list와 대응)
└── config.json             # region, projectName, agentRuntimeArn 등 (배포 시 생성)
```

| 파일 | 역할 |
|------|------|
| `app.py` | Agent / Agent (Chat) 모드, MCP·Skill·모델 선택 후 `agentcore_client.run_agent` 호출 |
| `agentcore_client.py` | payload(prompt, mcp_servers, skill_list, history_mode)를 Runtime으로 전송하고 SSE 스트림 처리 |
| `mcp.list` · `skills.list` | UI에 노출할 MCP·Skill 이름 목록. 선택값은 Runtime payload로 전달됨 |

### `runtime_agent/langgraph/` — LangGraph Agent (AgentCore Runtime)

[runtime_agent/langgraph/Dockerfile](./runtime_agent/langgraph/Dockerfile)로 arm64 이미지를 빌드하고, [runtime_agent/langgraph/installer.py](./runtime_agent/langgraph/installer.py)로 AgentCore Runtime에 배포합니다.

```text
runtime_agent/langgraph/
├── agent.py                # BedrockAgentCoreApp 엔트리포인트
├── langgraph_agent.py      # LangGraph StateGraph, Bedrock LLM, 도구 바인딩
├── chat.py                 # AsyncSqliteSaver 기반 대화 메모리
├── skill.py                # SkillManager, get_skill_instructions 도구
├── mcp_config.py           # 선택된 MCP → stdio subprocess command/args 매핑
├── mcp_server_*.py         # MCP 서버 (tavily, retrieve, trade_info, image_generation 등)
├── mcp.list                # 지원 MCP 목록
├── skills.list             # 지원 Skill 목록
├── utils.py                # config 로드, Tavily API key(Secrets Manager) 등
├── installer.py            # AgentCore Runtime·IAM·ECR 배포
├── Dockerfile              # AgentCore Runtime 컨테이너 이미지
├── config.json             # Knowledge Base ID, region, projectName 등
└── skills/                 # Skill 정의 (아래 참조)
    ├── docx/
    ├── pptx/
    ├── xlsx/
    ├── pdf/
    ├── skill-creator/
    └── ...
```

| 구분 | 모듈 | 설명 |
|------|------|------|
| **엔트리포인트** | `agent.py` | AgentCore 요청 수신 → `langgraph_agent` 실행 |
| **MCP** | `mcp_config.py`, `mcp_server_*.py` | UI에서 선택된 MCP를 컨테이너 내 stdio subprocess로 기동 |
| **Skill** | `skill.py`, `skills/` | `SKILL.md` 기반 지침. `get_skill_instructions` 도구로 로드 |
| **설정·배포** | `utils.py`, `installer.py`, `config.json` | AWS 리소스 연동, Secrets Manager, Runtime 배포 |

### Skill 구조 (`runtime_agent/langgraph/skills/`)

각 Skill은 `SKILL.md` 파일이 핵심이며, 필요에 따라 `scripts/`, `references/`, `assets/` 등의 보조 폴더를 포함할 수 있습니다. UI의 `application/skills.list`에서 선택한 이름과 `runtime_agent/langgraph/skills/` 하위 디렉터리가 대응합니다.

```text
skills/
├── docx/
│   ├── SKILL.md          # YAML 프론트매터 + 상세 지침
│   └── scripts/          # 문서 처리 스크립트
├── pptx/
│   └── SKILL.md
├── xlsx/
│   └── SKILL.md
└── skill-creator/
    └── SKILL.md
```


## Runtime Agent

LangGraph agent는 [runtime_agent/langgraph/](./runtime_agent/langgraph/)에 구현되어 있으며, AgentCore Runtime 컨테이너에서 `agent.py`의 `BedrockAgentCoreApp` 엔트리포인트로 실행됩니다.

### IAM 인증

LangGraph agent에 대한 이미지를 [runtime_agent/langgraph/Dockerfile](./runtime_agent/langgraph/Dockerfile)을 이용해 빌드후 ECR에 배포합니다. 또한, Agent Runtime 배포 시 IAM 인증을 사용합니다. [create_agent_runtime](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore-control/client/create_agent_runtime.html)에서 authorizerConfiguration을 포함하지 않은 경우에 IAM으로 인증하게 됩니다. Runtime 생성시 client는 bedrock-agentcore-control을 사용하고 Agent 이미지에 대한 ECR 경로를 가지고 있어야 합니다. 

Agent에서 외부 AgentCore endpoint로 요청을 보낼때에는 아래와 같이 IAM 인증을 수행하기 위하여 request에 X-Amz-Security-Token을 포함합니다. 이를 위해 httpx의 event hook을 이용해 아래와 같이 구현할 수 있습니다. 상세코드는 [runtime_agent/langgraph/agent.py](./runtime_agent/langgraph/agent.py)을 참조합니다.

```python
original_init = httpx.AsyncClient.__init__
def patched_init(self, *args, **kwargs):
    # Add SigV4 signing event hook if needed
    async def sign_request(request: httpx.Request) -> None:
        """Sign the request with AWS SigV4 including the body"""
        # Only sign requests to bedrock-agentcore
        if "bedrock-agentcore" not in str(request.url):
            return
        
        # Get credentials
        boto_session = boto3.Session()
        credentials = boto_session.get_credentials().get_frozen_credentials()
        
        # Parse URL
        parsed_url = urlparse(str(request.url))
        host = parsed_url.netloc
        
        # Generate timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        
        # Read request body if available
        body = None
        if request.content:
            if isinstance(request.content, bytes):
                body = request.content
            else:
                try:
                    body = await request.aread()
                    if hasattr(request, '_content'):
                        request._content = body
                except Exception:
                    pass
        
        # Create AWS request headers
        aws_headers = {
            'host': host,
            'x-amz-date': timestamp,
            'Content-Type': request.headers.get('Content-Type', 'application/json'),
            'Accept': request.headers.get('Accept', 'application/json, text/event-stream')
        }
        
        if body:
            aws_headers['Content-Length'] = str(len(body))
        
        # Create AWS request for signing
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            headers=aws_headers,
            data=body
        )
        
        # Sign the request
        region = utils.load_config().get("region", "us-west-2")
        auth = BotocoreSigV4Auth(credentials, "bedrock-agentcore", region)
        auth.add_auth(aws_request)
        
        # Update request headers
        request.headers['X-Amz-Date'] = timestamp
        request.headers['Authorization'] = aws_request.headers['Authorization']
        
        if credentials.token:
            request.headers['X-Amz-Security-Token'] = credentials.token
    
    # Add event_hooks to kwargs if not already present
    if 'event_hooks' not in kwargs:
        kwargs['event_hooks'] = {'request': [], 'response': []}
    elif not isinstance(kwargs['event_hooks'], dict):
        kwargs['event_hooks'] = {'request': [], 'response': []}
    
    if 'request' not in kwargs['event_hooks']:
        kwargs['event_hooks']['request'] = []
    
    # Add the sign_request hook
    kwargs['event_hooks']['request'].append(sign_request)

    # Call original init with modified kwargs
    original_init(self, *args, **kwargs)
```

Streamlit에서 입력하면 AgentCore endpoint로 전달되는데 이때에 아래와 같이 BedrockAgentCoreApp의 entrypoint로 받아서 실행합니다.

```python
import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
async def agent_langgraph(payload):
    httpx.AsyncClient.__init__ = patched_init
    
    client = MultiServerMCPClient(server_params)
    tools = await client.get_tools()
    
    app = langgraph_agent.buildChatAgentWithHistory(tools)
    config = {
        "recursion_limit": 50,
        "configurable": {"thread_id": user_id},
        "tools": tools,
        "system_prompt": None
    }
    
    inputs = {"messages": [HumanMessage(content=query)]}
            
    value = final_output = None
    async for output in app.astream(inputs, config):
        for key, value in output.items():
            logger.info(f"--> key: {key}, value: {value}")

            if key == "messages" or key == "agent":
                if isinstance(value, dict) and "messages" in value:
                    final_output = value
                elif isinstance(value, list):
                    final_output = {"messages": value, "image_url": []}
                else:
                    final_output = {"messages": [value], "image_url": []}
```


## Session Storage

AgentCore Runtime에서 대화 context를 유지하려면 **Session Storage**를 사용합니다. `create_agent_runtime` 시 `filesystemConfigurations`에 `sessionStorage`를 설정하면, `invoke_agent_runtime`의 **`runtimeSessionId`마다** 컨테이너에 임시 디스크가 마운트됩니다. 이 프로젝트에서는 LangGraph checkpointer가 해당 경로의 SQLite 파일에 대화 이력을 저장합니다.

### Runtime 생성 시 sessionStorage 설정

[runtime_agent/langgraph/installer.py](./runtime_agent/langgraph/installer.py)에서 runtime을 생성할 때 아래와 같이 `/mnt/workspace`를 마운트합니다. (`/mnt/` 하위 경로 필수)

```python
client = boto3.client('bedrock-agentcore-control', region_name=aws_region)

response = client.create_agent_runtime(
    agentRuntimeName=runtime_name,
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': f"{account_id}.dkr.ecr.{aws_region}.amazonaws.com/{repository_name}:{image_tag}"
        }
    },
    filesystemConfigurations=[
        {
            "sessionStorage": {
                "mountPath": "/mnt/workspace"
            }
        }
    ],
    networkConfiguration={"networkMode": "PUBLIC"},
    roleArn=agent_runtime_role
)
```

### LangGraph checkpointer 연동

기존 `MemorySaver`는 프로세스 메모리에만 저장되어 컨테이너가 재시작되면 history가 사라집니다. `history_mode=Enable`일 때 [runtime_agent/langgraph/chat.py](./runtime_agent/langgraph/chat.py)의 `ensure_checkpointer()`가 **AsyncSqliteSaver**를 초기화하고, `buildChatAgentWithHistory()`가 이를 checkpointer로 사용합니다.

| 구분 | Strands (참고) | LangGraph (본 프로젝트) |
|------|----------------|-------------------------|
| 저장소 | `FileSessionManager(storage_dir="/mnt/workspace")` | `AsyncSqliteSaver` → `/mnt/workspace/langgraph_checkpoints.sqlite` |
| 세션 키 | `session_id` | `config["configurable"]["thread_id"]` |

```python
# chat.py — 요약
SESSION_STORAGE_DIR = os.environ.get("SESSION_STORAGE_DIR", "/mnt/workspace")
CHECKPOINT_DB = os.path.join(SESSION_STORAGE_DIR, "langgraph_checkpoints.sqlite")

async def ensure_checkpointer():
    saver = AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB)
    checkpointer = await saver.__aenter__()
    await checkpointer.setup()
    return checkpointer
```

`buildChatAgentWithHistory()`는 아래와 같이 checkpointer를 compile 시 전달합니다.

```python
return workflow.compile(
    checkpointer=chat.checkpointer
)
```



### 클라이언트 runtimeSessionId

Streamlit 클라이언트([application/agentcore_client.py](./application/agentcore_client.py))는 history 모드에서 **user_id 기반 고정 `runtimeSessionId`**를 사용합니다. 같은 사용자가 재접속해도 동일한 `/mnt/workspace`가 붙어 SQLite checkpoint를 이어서 읽을 수 있습니다.

```python
def runtime_session_id_for(user_id: str, history_mode: str) -> str:
    if history_mode == "Enable" and user_id:
        seed = f"agentcore-session-{user_id}"
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))
    else:
        session_id = str(uuid.uuid4())
    return session_id
```

```mermaid
sequenceDiagram
    participant UI as Streamlit
    participant Client as agentcore_client
    participant AC as AgentCore Runtime
    participant LG as LangGraph

    UI->>Client: history_mode=Enable, user_id
    Client->>AC: invoke(runtimeSessionId=uuid5(user_id))
    Note over AC: /mnt/workspace 마운트
    AC->>LG: astream(..., thread_id=user_id:scope)
    LG->>LG: AsyncSqliteSaver → langgraph_checkpoints.sqlite
    Client->>AC: 다음 턴 (동일 runtimeSessionId)
    LG->>LG: thread_id로 이전 checkpoint 로드
```

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SESSION_STORAGE_DIR` | `/mnt/workspace` | checkpoint SQLite 디렉터리 |
| `SESSION_STORAGE_ENABLED` | `true` | `false`이면 `MemorySaver`로 폴백 |

로컬에서 session storage 없이 실행할 때는 `SESSION_STORAGE_DIR`이 없으면 `runtime_agent/langgraph/.session_storage`를 사용합니다.

### 주의사항

- **세션 범위**: `/mnt/workspace`는 `runtimeSessionId` 수명에 묶인 **임시 저장소**입니다. 일반적으로 세션이 종료되면 데이터가 사라지지만, AgentCore를 사용할 경우에는 14일간 보관이 됩니다. 추가 입력이 있을 경우에 기간은 다시 14일로 갱신됩니다. 세션당 최대 1MB까지 저장합니다. 다른 방법으로 S3, DynamoDB, RDS 등을 별도로 설정할 수 있습니다.
- **요청마다 agent 재생성**: `agent.py`는 매 요청 `create_agent()`를 호출하지만, checkpointer가 파일에 있으면 `thread_id`만 같으면 history를 복원합니다.
- **`InMemoryStore`는 휘발성**: `store=chat.memorystore`는 LangGraph Store API용이며 메모리에만 있습니다. 대화 history만 필요하면 checkpointer만으로 충분합니다.
- **의존성**: [runtime_agent/langgraph/Dockerfile](./runtime_agent/langgraph/Dockerfile)에 `langgraph-checkpoint-sqlite`, `aiosqlite`가 포함되어 있습니다.





### 세션 관리

AgentCore Runtime에서 대화 history를 유지하려면 **managed session storage**(`filesystemConfigurations.sessionStorage`)와 **동일한 `runtimeSessionId`**, 그리고 LangGraph **checkpointer**(SQLite)가 함께 동작해야 합니다. 상세 구현은 위 [Session Storage](#session-storage) 절을 참조합니다.

#### sessionStorage (managed session storage)

[AWS 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)에 따르면, `sessionStorage`는 **runtimeSessionId마다** 격리된 persistent 디렉터리(`/mnt/workspace` 등)를 제공합니다. agent가 일반 파일 I/O로 쓴 내용은 서비스가 durable storage에 비동기 복제하고, microVM이 stop/resume(cold start)되어도 **같은 `runtimeSessionId`로 invoke하면** 파일 상태가 복원됩니다.

| 항목 | 내용 |
|------|------|
| 설정 위치 | `create_agent_runtime` / `update_agent_runtime`의 `filesystemConfigurations` |
| mount path | `/mnt/` 하위 1단계 필수 (예: `/mnt/workspace`) |
| 세션 격리 | `runtimeSessionId`마다 별도 storage (세션 간 공유 불가) |
| session당 용량 | 최대 1 GB |
| idle 만료 | **14일**간 invoke 없으면 데이터 삭제 |
| version 업데이트 | **agent runtime version 변경 시 session data 초기화** |

**stop/resume lifecycle (AWS):**

1. 첫 invoke — microVM 생성, mount path는 빈 디렉터리
2. agent write — 로컬 파일 시스템에 쓰기, durable storage로 비동기 복제
3. session stop — microVM 종료, 미 flush 데이터는 graceful shutdown 시 flush
4. 같은 session resume — 새 microVM에 storage 복원

본 프로젝트는 `/mnt/workspace/langgraph_checkpoints.sqlite`에 LangGraph checkpoint를 저장합니다. cold start 후 `ensure_checkpointer()` 로그가 `opened (existing)`이면 복원 성공, `initialized`이면 **새 DB 생성(이전 history 없음)** 입니다.

> **중요:** Dockerfile의 `ENV SESSION_STORAGE_DIR=/mnt/workspace`만으로는 영속 storage가 활성화되지 않습니다. **반드시** runtime API에 `filesystemConfigurations.sessionStorage`를 설정해야 합니다. `create_agent_runtime`뿐 아니라 **`update_agent_runtime`에도 동일하게 포함**해야 합니다. update 시 누락하면 `get-agent-runtime` 응답에 `filesystemConfigurations`가 없고, cold start마다 checkpoint가 사라집니다.

#### maxLifetime · idleRuntimeSessionTimeout (lifecycle)

[Lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)의 **8시간**은 checkpoint **데이터 보관 기간이 아닙니다.** microVM **인스턴스 최대 수명**입니다.

| 설정 | 기본값 | 의미 |
|------|--------|------|
| `idleRuntimeSessionTimeout` | 900초 (**15분**) | idle 상태가 이 시간 지속되면 해당 session의 microVM 종료 |
| `maxLifetime` | 28,800초 (**8시간**) | microVM이 한 번 생성된 뒤 살아 있을 수 있는 **최대 시간** (리셋 불가) |

- idle timeout 도달 → microVM만 종료. sessionStorage가 설정되어 있고 **같은 `runtimeSessionId`**로 다시 invoke하면 storage가 복원되어야 합니다.
- maxLifetime 도달 → microVM 교체. session 자체는 새 microVM으로 **resume 가능** (문서: *"The session itself can persist beyond this with a new instance provisioned."*)
- idle timer는 **같은 session에 invoke할 때마다 리셋**됩니다.

#### runtimeSessionId (클라이언트)

[application/agentcore_client.py](./application/agentcore_client.py)의 `runtime_session_id_for()`는 history 모드에서 user_id 기반 **고정 UUID**를 생성합니다. sessionStorage 복원은 **invoke마다 동일한 `runtimeSessionId`**가 전달될 때만 동작합니다.

- history 모드에서 `runtimeSessionId`는 `user_id`만으로 고정 (`agentcore_client.py`)

#### 배포·운영 체크리스트

1. `get-agent-runtime`으로 `filesystemConfigurations`에 `sessionStorage` 존재 확인
2. create/update 모두 `/mnt/workspace` mount path 포함
3. history 모드에서 `runtimeSessionId`가 user_id마다 고정인지 확인
4. runtime **version 업데이트 직후**에는 session data가 wipe됨 (정상 동작)
5. CloudWatch(`/aws/bedrock-agentcore/runtimes/...`)에서 `checkpointer` 로그로 `initialized` vs `opened (existing)` 확인

#### 참고 문서

- [File system configurations for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)
- [Configure lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore quotas (session storage limits)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)


### Message Trim

LangGraph 에이전트([runtime_agent/langgraph/langgraph_agent.py](./runtime_agent/langgraph/langgraph_agent.py)의 `call_model`)는 LLM 호출 직전에 **HumanMessage 기준 최근 N턴**만 남깁니다. LangGraph state의 `messages`는 checkpointer에 그대로 두고, **모델에 넘기는 메시지만** trim합니다. `history_mode=Enable`/`Disable` 모두 동일하게 적용됩니다.

**기본값:** `MAX_CONTEXT_TURNS = 5`

**설정 변경:**

- [runtime_agent/langgraph/langgraph_agent.py](./runtime_agent/langgraph/langgraph_agent.py)의 `MAX_CONTEXT_TURNS` 상수 수정
- 또는 [runtime_agent/langgraph/chat.py](./runtime_agent/langgraph/chat.py)의 `create_agent()`에서 config의 `max_turns` / `configurable.max_turns` 지정
- `max_turns=0`이면 trim 비활성화

상수와 trim 함수는 `langgraph_agent.py`에 정의합니다.

```python
# runtime_agent/langgraph/langgraph_agent.py
MAX_CONTEXT_TURNS = 5


def trim_messages_by_human_turns(messages: list, max_turns: int) -> list:
    """Keep messages from the last N HumanMessage turns (inclusive)."""
    if max_turns <= 0 or not messages:
        return messages

    human_indices = [i for i, msg in enumerate(messages) if isinstance(msg, HumanMessage)]
    if len(human_indices) <= max_turns:
        return messages

    return messages[human_indices[-max_turns]:]
```

`call_model`에서는 Bedrock용 메시지 정규화(`sanitize_messages_for_bedrock`) 후 trim을 적용합니다.

```python
# runtime_agent/langgraph/langgraph_agent.py — call_model() 내부
        max_turns = (
            config.get("configurable", {}).get("max_turns")
            or config.get("max_turns")
            or MAX_CONTEXT_TURNS
        )
        trimmed = trim_messages_by_human_turns(messages, max_turns)
        if len(trimmed) < len(messages):
            logger.info(
                f"trimmed messages from {len(messages)} to {len(trimmed)} "
                f"(max_turns={max_turns})"
            )
            messages = trimmed

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        chain = prompt | model
        async for chunk in chain.astream({"messages": messages}):
            ...
```

에이전트 config는 `chat.py`의 `create_agent()`에서 생성하며, `history_mode`와 관계없이 `max_turns`를 전달합니다.

```python
# runtime_agent/langgraph/chat.py — create_agent()
    if history_mode == "Enable":
        app = langgraph_agent.buildChatAgentWithHistory(tools)
        config = {
            "recursion_limit": 100,
            "configurable": {
                "thread_id": thread_id,
                "tools": tools,
                "system_prompt": system_prompt,
            },
            "max_turns": langgraph_agent.MAX_CONTEXT_TURNS,
        }
    else:
        app = langgraph_agent.buildChatAgent(tools)
        config = {
            "recursion_limit": 100,
            "configurable": {
                "thread_id": thread_id,
                "tools": tools,
                "system_prompt": system_prompt,
            },
            "max_turns": langgraph_agent.MAX_CONTEXT_TURNS,
        }
```

**`max_turns=5`의 의미**

- **사용자 HumanMessage 5개**와, 각 턴에 이어진 **모든 후속 메시지**를 유지
- 1턴 = `HumanMessage` 1개 + 그 뒤의 `AIMessage`, `ToolMessage`, 도구 feedback loop 전체
- 도구를 여러 번 호출해도 **같은 사용자 질문이면 1턴**으로 카운트

**예 (도구 사용 포함)**

```
Human(Q1) → AI(tool_calls) → ToolMessage → AI(A1)
Human(Q2) → AI(A2)
Human(Q3) → AI(tool_calls) → ToolMessage → AI(A3)
```

`max_turns=2`이면 **Q2부터** 유지:

```
Human(Q2) → AI(A2) → Human(Q3) → AI(tool_calls) → ToolMessage → AI(A3)
```

**메시지 개수 trim과의 차이**

| 방식 | `N=5`일 때 |
|------|------------|
| 이전 (메시지 개수) | 메시지 객체 5개만 유지 → 도구 루프 때문에 사용자 턴 수가 불규칙 |
| 현재 (HumanMessage 턴) | 사용자 질문 5개 + 각 턴의 AI/Tool 응답 전체 유지 |

**Session Storage와의 관계**

- checkpointer(SQLite)에는 **전체 대화 이력**이 저장됩니다.
- trim은 LLM 컨텍스트 윈도우 관리용이며, 저장된 history를 삭제하지 않습니다.
- CloudWatch 로그에서 `trimmed messages from X to Y (max_turns=5)`로 trim 여부를 확인할 수 있습니다.



## AWS Tavily 설치 및 활용

[AWS Marketplace의 Tavily MCP Server](https://aws.amazon.com/marketplace/pp/prodview-twjga5bwmoszq)를 Bedrock AgentCore Runtime에 배포하고, LangGraph Agent에서 **원격 MCP(streamable HTTP)** 로 연동하는 기능입니다. 로컬 stdio 방식의 `tavily`(`mcp_server_tavily.py`)와 달리, `aws-tavily`는 **별도 AgentCore Runtime**에서 Marketplace 컨테이너를 실행합니다.

### `tavily` vs `aws-tavily`

| 항목 | `tavily` | `aws-tavily` |
|------|----------|--------------|
| 실행 위치 | LangGraph Agent Runtime 컨테이너 내부 (stdio subprocess) | 별도 AgentCore Runtime (`agent_runtime_aws_tavily`) |
| 이미지 | `mcp_server_tavily.py` | Marketplace 사전 빌드 ECR 이미지 |
| 연결 방식 | `command` / `args` | `streamable_http` + SigV4 |
| 리전 | Agent Runtime과 동일 | **`us-east-1` 고정** |

UI의 MCP 체크박스(`application/mcp.list`, `runtime_agent/langgraph/mcp.list`)에 `aws-tavily`가 포함되어 있으며, Agent 모드에서 선택하면 Runtime이 Tavily MCP에 연결합니다.

### 사전 준비

1. [Tavily MCP Server](https://aws.amazon.com/marketplace/pp/prodview-twjga5bwmoszq) Marketplace 구독
2. Tavily API Key 확보
3. AWS CLI credential 및 Bedrock AgentCore 사용 권한

### 설치

[runtime_agent/langgraph/installer.py](./runtime_agent/langgraph/installer.py)의 `main()`은 LangGraph Agent Runtime 배포 후 **aws-tavily 전용 Runtime**을 추가로 생성·갱신합니다.

```text
...
4. Creating/updating AgentCore runtime          ← LangGraph Agent
5. Creating/updating aws-tavily AgentCore runtime  ← Tavily MCP (Marketplace 컨테이너)
```

**컨테이너 이미지** (기본값, `config.json`의 `tavily_container_image_uri`로 override 가능):

```text
709825985650.dkr.ecr.us-east-1.amazonaws.com/tavily/tavily-mcp:v0.1.2
```

**Runtime 이름·리전 고정 (교차 프로젝트 재활용)**

| 항목 | 값 |
|------|-----|
| Runtime 이름 | `agent_runtime_aws_tavily` |
| 리전 | `us-east-1` |

`aws-tavily` 전용 [aws-tavily](https://github.com/kyopark2014/aws-tavily) 저장소나 다른 프로젝트에서 이미 동일 이름의 Runtime을 배포했다면, installer는 새로 만들지 않고 **기존 Runtime을 찾아 update** 합니다. 설치 완료 후 ARN은 `runtime_agent/langgraph/config.json`의 `aws_tavily_agent_runtime_arn`에 저장됩니다.

**Tavily API Key 설정** (`installer.py`의 `_load_tavily_api_key_for_runtime`)

다음 순서로 API Key를 조회해 Runtime 환경 변수 `TAVILY_API_KEY`로 주입합니다.

1. `config.json`의 `tavily_api_key`
2. 환경 변수 `TAVILY_API_KEY`
3. Secrets Manager (`tavilyapikey-{knowledge_base_name}` 또는 `tavilyapikey-{projectName}`)

API Key가 없으면 Runtime은 생성되지만 Tavily 검색은 동작하지 않습니다.

```mermaid
flowchart TD
  A[installer.py] --> B{agent_runtime_aws_tavily 존재?}
  B -->|없음| C[create_agent_runtime in us-east-1]
  B -->|있음| D[update_agent_runtime]
  C --> E[aws_tavily_agent_runtime_arn → config.json]
  D --> E
  F[LangGraph Agent] -->|aws-tavily 선택| G[mcp_config.py ARN 조회]
  G --> H[streamable_http + SigV4]
  H --> I[Tavily MCP Runtime]
```

### MCP 연동 (`mcp_config.py`)

`aws-tavily` 선택 시 [runtime_agent/langgraph/mcp_config.py](./runtime_agent/langgraph/mcp_config.py)는 `us-east-1`에서 `agent_runtime_aws_tavily` ARN을 조회하고, streamable HTTP MCP 설정을 생성합니다.

```python
AWS_TAVILY_RUNTIME_NAME = "agent_runtime_aws_tavily"
AWS_TAVILY_RUNTIME_REGION = "us-east-1"

# get_agent_runtime_arn("aws-tavily") → us-east-1에서 고정 이름 조회

{
    "mcpServers": {
        "tavily-search": {
            "type": "streamable_http",
            "url": mcp_url,
            "auth_type": "aws_sigv4",
            "auth_region": "us-east-1",
            "auth_service": "bedrock-agentcore",
        }
    }
}
```

Runtime이 없으면 MCP 서버를 건너뛰고 로그에 skip 메시지를 남깁니다.

### SigV4 인증 (`langgraph_agent.py`)

[runtime_agent/langgraph/langgraph_agent.py](./runtime_agent/langgraph/langgraph_agent.py)의 `load_multiple_mcp_server_parameters()`는 `auth_type == "aws_sigv4"`인 MCP에 [agentcore_sigv4_auth.py](./runtime_agent/langgraph/agentcore_sigv4_auth.py)의 `AgentCoreSigV4Auth`를 적용합니다. LangGraph Agent Runtime의 IAM 역할로 Bedrock AgentCore invoke URL에 서명합니다.

```python
if config.get("auth_type") == "aws_sigv4":
    connection["auth"] = agentcore_sigv4_auth.AgentCoreSigV4Auth(
        region=config.get("auth_region", "us-east-1"),
        service=config.get("auth_service", "bedrock-agentcore"),
    )
```

### 제공 MCP 도구

Marketplace Tavily MCP 컨테이너가 노출하는 주요 도구입니다.

| 도구 | 설명 |
|------|------|
| `tavily_search` | 실시간 웹 검색 |
| `tavily_extract` | URL 본문 추출 |
| `tavily_crawl` | 시드 URL 기반 사이트 탐색·추출 |
| `tavily_map` | 접근 가능 URL 목록 수집 |

### 활용 방법

1. `runtime_agent/langgraph/installer.py`로 LangGraph Agent Runtime과 aws-tavily Runtime을 배포합니다.
2. Streamlit UI에서 Agent 모드를 선택하고 MCP 체크박스에서 **`aws-tavily`** 를 선택합니다.
3. 웹 검색이 필요한 질문을 입력하면 Agent가 `tavily_search` 등을 호출합니다.

> **참고:** `tavily`(로컬 stdio)와 `aws-tavily`(원격 AgentCore)는 동시에 선택할 수 있지만, 동일한 `tavily-search` 서버 이름을 사용하므로 **하나만 선택**하는 것을 권장합니다.

### Tavily Tool Interceptor


#### 적용 이유

LLM이 `tavily_search`를 호출할 때 `country` 인자에 **ISO 2자리 코드**(예: `KR`, `US`)나 **한글**(예: `한국`, `대한민국`)을 넣는 경우가 많습니다. Tavily Search API는 `country`에 **소문자 전체 국가명**(예: `south korea`, `united states`)을 기대하므로, 잘못된 값이 그대로 원격 MCP(Runtime)로 전달되면 검색 품질이 떨어지거나 오류가 납니다.

로컬 stdio 방식의 `tavily`(`mcp_server_tavily.py`)는 같은 프로세스 안에서 처리되지만, `aws-tavily`는 **Bedrock AgentCore의 별도 Runtime**으로 HTTP 요청이 나갑니다. 따라서 Agent 쪽에서 인자를 한 번 정규화한 뒤 보내는 **클라이언트 측 가드**가 필요합니다.

또한 시스템 프롬프트(`TAVILY_TOOL_PROMPT`)만으로는 모델이 항상 올바른 `country` 형식을 지키지 못할 수 있어, **도구 호출 직전에 코드로 보정**하는 이중 안전장치를 둡니다.

#### 동작 흐름

```mermaid
sequenceDiagram
  participant LG as LangGraph Agent
  participant INT as TavilyToolCallInterceptor
  participant MCP as MultiServerMCPClient
  participant RT as aws-tavily Runtime

  LG->>MCP: tavily_search(country="KR", ...)
  MCP->>INT: MCPToolCallRequest
  INT->>INT: country "KR" → "south korea"
  INT->>MCP: override(args)
  MCP->>RT: streamable HTTP + SigV4
  RT-->>LG: 검색 결과
```

`chat.py`의 `create_agent()`는 `auth_type == "aws_sigv4"`인 MCP(aws-tavily 등 AgentCore 원격 MCP)가 포함된 경우에만 interceptor를 등록합니다.

```python
interceptors = [TavilyToolCallInterceptor()] if has_agentcore else None
client = MultiServerMCPClient(server_params, tool_interceptors=interceptors)
```

#### 구현 내용

| 구성요소 | 역할 |
|----------|------|
| `TAVILY_COUNTRY_ALIASES` | `kr`, `KOR`, `한국`, `us`, `usa` 등 → Tavily가 받는 전체 국가명으로 매핑 |
| `normalize_tavily_country()` | 입력을 trim·소문자화한 뒤 alias 조회. 빈 값이면 `None` |
| `sanitize_tavily_tool_args()` | `tavily_`로 시작하는 도구만 처리. `country`가 있으면 정규화, 비어 있으면 파라미터 제거 |
| `TavilyToolCallInterceptor` | [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)의 `MCPToolCallRequest`를 가로채 인자 수정 후 실제 MCP handler 호출 |

핵심 로직:

```python
class TavilyToolCallInterceptor:
    async def __call__(self, request: MCPToolCallRequest, handler) -> MCPToolCallResult:
        if request.name.startswith("tavily_"):
            new_args = sanitize_tavily_tool_args(request.name, request.args)
            if new_args != request.args:
                request = request.override(args=new_args)
        return await handler(request)
```

정규화 예시:

| 모델이 보낸 `country` | interceptor 이후 |
|----------------------|-------------------|
| `KR` | `south korea` |
| `한국` | `south korea` |
| `US` | `united states` |
| `""` (빈 문자열) | 파라미터 제거 |
| `south korea` | 변경 없음 |

변환이 일어나면 `tavily-interceptor` 로거에 `normalized country 'KR' -> 'south korea'` 형태로 INFO 로그가 남습니다.

#### 관련 보완 (interceptor와 함께 적용)

Interceptor는 **인자 형식**만 고칩니다. 아래는 **모델 행동** 쪽 보완으로 함께 들어가 있습니다.

| 파일 | 내용 |
|------|------|
| [langgraph_agent.py](./runtime_agent/langgraph/langgraph_agent.py) | `TAVILY_TOOL_PROMPT` — aws-tavily가 곧 Tavily 연동임을 명시, 검색 시 즉시 `tavily_search` 호출 유도 |
| [skill.py](./runtime_agent/langgraph/skill.py) | Agent Workflow에 MCP 검색 우선 단계, Skill 가이드에 검색 시 도구 호출 규칙 |
| [chat.py](./runtime_agent/langgraph/chat.py) | AgentCore MCP cold start 시 `get_tools()` 최대 3회 재시도 |

### 참고

- 독립 배포·Streamlit 예제: [aws-tavily](https://github.com/kyopark2014/aws-tavily)
- [Tavily MCP Server (AWS Marketplace)](https://aws.amazon.com/marketplace/pp/prodview-twjga5bwmoszq)
- [Tavily API 문서](https://docs.tavily.com/)

## 배포하기

아래와 같이 EC2를 이용해 배포 환경을 구성합니다.

1. AWS Console의 EC2에 접속해서 [Launch instance]를 선택합니다.
2. EC2 생성시 Architecture로 Arm을 선택하고 나머지는 기본값으로 생성합니다.
3. [EC2 Instance Connect]로 접속해서 아래와 같이 python, pip, git, boto3를 설치합니다.

```text
sudo yum install python3 python3-pip git 
pip install boto3 --upgrade
```

4. 아래 명령어로 docker를 설치합니다.

```bash
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user
newgrp docker
docker info
```

5. Workshop의 경우에 아래 형태로 된 Credential을 복사하여 EC2 터미널에 입력합니다.

<img width="700" alt="credential" src="https://github.com/user-attachments/assets/261a24c4-8a02-46cb-892a-02fb4eec4551" />


6. 아래와 같이 git source를 가져옵니다.

```bash
git clone https://github.com/kyopark2014/power-runtime
cd power-runtime
```

7. 아래와 같이 [installer.py](./installer.py)를 이용해 설치를 시작합니다.

```bash
python3 installer.py
```


8. 설치가 완료되면 CloudFront로 접속하여 동작을 확인합니다. Agent를 선택한 후에 적절한 MCP tool을 선택하여 원하는 작업을 수행합니다.

9. 인프라가 더이상 필요없을 때에는 루트 [uninstaller.py](./uninstaller.py)를 이용해 제거합니다.

```bash
python3 uninstaller.py
```

### Knowledge Base 문서 동기화 하기 

Knowledge Base에서 문서를 활용하기 위해서는 S3에 문서 등록 및 동기화기 필요합니다. [S3 Console](https://us-west-2.console.aws.amazon.com/s3/home?region=us-west-2)에 접속하여 `storage-for-power-runtime-{account_id}-us-west-2` 형식의 버킷(예: `storage-for-power-runtime-xxxxxxxxxxxx-us-west-2`)을 선택하고, 아래와 같이 docs폴더를 생성한 후에 파일을 업로드 합니다. 

<img width="400" alt="image" src="https://github.com/user-attachments/assets/482f635e-a38d-4525-b9a3-fb1c2a9089c8" />

이후 [Knowledge Bases Console](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2#/knowledge-bases)에 접속하여, `power-runtime`이라는 Knowledge Base를 선택합니다. 이후 아래와 같이 [Sync]를 선택합니다.

<img width="1533" height="287" alt="noname" src="https://github.com/user-attachments/assets/2edd3b6b-dbce-4784-b640-139fa84cc223" />

### Local에서 실행하기

AWS 환경을 잘 활용하기 위해서는 [AWS CLI를 설치](https://docs.aws.amazon.com/ko_kr/cli/v1/userguide/cli-chap-install.html)하여야 합니다. EC2에서 배포하는 경우에는 별도로 설치가 필요하지 않습니다. Local에 설치시는 아래 명령어를 참조합니다.

```text
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" 
unzip awscliv2.zip
sudo ./aws/install
```

AWS credential을 아래와 같이 AWS CLI를 이용해 등록합니다.

```text
aws configure
```

설치하다가 발생하는 각종 문제는 [Kiro-cli](https://aws.amazon.com/ko/blogs/korea/kiro-general-availability/)를 이용해 빠르게 수정합니다. 아래와 같이 설치할 수 있지만, Windows에서는 [Kiro 설치](https://kiro.dev/downloads/)에서 다운로드 설치합니다. 실행시는 셀에서 "kiro-cli"라고 입력합니다. 

```python
curl -fsSL https://cli.kiro.dev/install | bash
```

venv로 환경을 구성하면 편리하게 패키지를 관리합니다. 아래와 같이 환경을 설정합니다.

```text
python -m venv .venv
source .venv/bin/activate
```

이후 다운로드 받은 github 폴더로 이동한 후에 아래와 같이 필요한 패키지를 추가로 설치 합니다.

```text
pip install -r requirements.txt
```

이후 아래와 같은 명령어로 streamlit을 실행합니다. 

```text
streamlit run application/app.py
```



### 비동기 실행

에이전트가 즉시 응답하고 백그라운드에서 계속 처리할 수 있습니다. 클라이언트는 동기/비동기 구분 없이 동일한 API 사용가능하고, 세션을 재사용하여 컨텍스트 유지합니다.

```python
import threading
import time
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@tool
def start_background_task(duration: int = 5) -> str:
    """백그라운드에서 지정된 시간 동안 실행되는 태스크 시작"""

    # 비동기 태스크 등록
    task_id = app.add_async_task("background_processing", {"duration": duration})

    # 별도 스레드에서 백그라운드 작업 실행
    def background_work():
        time.sleep(duration)  # 실제 작업 수행
        app.complete_async_task(task_id)  

    threading.Thread(target=background_work, daemon=True).start()

    return f"백그라운드 태스크 시작됨 (ID: {task_id}), {duration}초 후 완료 예정"

agent = Agent(tools=[start_background_task])

@app.entrypoint
def main(payload):
    user_message = payload.get("prompt", "3초짜리 태스크를 시작해줘")
    return {"message": agent(user_message).message}

if __name__ == "__main__":
    app.run()
```

## 실행 결과

"https://github.com/kyopark2014/strands-runtime/blob/main/README.md 을 정리해줘."와 같이 입력하면 웹의 정보를 편리하게 활용할 수 있습니다.

<img width="728" height="729" alt="image" src="https://github.com/user-attachments/assets/c3a18138-ba1c-4956-90b4-d55a0737da33" />

이때의 결과는 아래와 같습니다.

<img width="663" height="780" alt="image" src="https://github.com/user-attachments/assets/6b4ed348-c923-46d7-838b-da8f54e123f8" />


"aws document로 agent evalutation 에 대해 조사해줘."로 하면 필요한 정보를 조회하여 정리합니다.

<img width="720" height="706" alt="image" src="https://github.com/user-attachments/assets/fb5eb40e-720e-420f-ad3b-8aafceab236e" />



## Reference 

[Invoke streaming agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)

[Get started with the Amazon Bedrock AgentCore Runtime starter toolkit](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-getting-started-toolkit.html)

[Amazon Bedrock AgentCore - Developer Guide](https://docs.aws.amazon.com/pdfs/bedrock-agentcore/latest/devguide/bedrock-agentcore-dg.pdf)

[BedrockAgentCoreControlPlaneFrontingLayer](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore-control.html)

[get_agent_runtime](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore-control/client/get_agent_runtime.html)

[Amazon Bedrock AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)

[Amazon Bedrock AgentCore](https://buttoned-gull-5fa.notion.site/Amazon-Bedrock-AgentCore-23708996fdd380c2a6e1ffaa2e08c000)

[Amazon Bedrock AgentCore RuntCode Interpreter](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials/05-AgentCore-tools/01-Agent-Core-code-interpreter)

[Add observability to your Amazon Bedrock AgentCore resources](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)

[Hosting Strands Agents with Amazon Bedrock models in Amazon Bedrock AgentCore Runtime](https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/01-tutorials%2F06-AgentCore-observability%2F01-Agentcore-runtime-hosted%2Fruntime_with_strands_and_bedrock_models.ipynb)

[Agentic AI 펀드 매니저](https://github.com/ksgsslee/investment_advisor_strands)

[AWS re:Invent 2025 - Architecting scalable and secure agentic AI with Bedrock AgentCore (AIM431)](https://www.youtube.com/watch?v=wqmeZOT6mmc)


[Deploy Production-Ready Agents in 22 Minutes with AgentCore Runtime](https://www.youtube.com/watch?v=Q-tYIAuv9WI)

[AgentCore Workshop](https://atomoh.gitbook.io/aiops)

