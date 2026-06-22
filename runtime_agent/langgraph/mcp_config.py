import logging
import sys
import utils
import os
import boto3

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-config")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

config = utils.load_config()
logger.info(f"config: {config}")

region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp"
workingDir = os.path.dirname(os.path.abspath(__file__))
# 상위 디렉토리의 contents 폴더 경로 추가
parent_dir = os.path.dirname(workingDir)
contents_dir = os.path.join(parent_dir, "contents")
logger.info(f"workingDir: {workingDir}")
logger.info(f"contents_dir: {contents_dir}")

mcp_user_config = {}

AWS_TAVILY_RUNTIME_NAME = "agent_runtime_aws_tavily"
AWS_TAVILY_RUNTIME_REGION = "us-east-1"

def get_agent_runtime_arn(mcp_type: str):
    if mcp_type == "aws-tavily":
        agent_runtime_name = AWS_TAVILY_RUNTIME_NAME
        lookup_region = AWS_TAVILY_RUNTIME_REGION
    else:
        agent_runtime_name = f"{projectName.lower().replace('-', '_')}_{mcp_type.replace('-', '_')}"
        lookup_region = region
    logger.info(f"agent_runtime_name: {agent_runtime_name}")
    client = boto3.client("bedrock-agentcore-control", region_name=lookup_region)
    response = client.list_agent_runtimes(maxResults=100)
    logger.info(f"response: {response}")

    for agent_runtime in response.get("agentRuntimes", []):
        if agent_runtime.get("agentRuntimeName") == agent_runtime_name:
            arn = agent_runtime["agentRuntimeArn"]
            logger.info(f"agent_runtime_name: {agent_runtime_name}, agentRuntimeArn: {arn}")
            return arn
    return None

def get_agentcore_gateway_mcp_url(gateway_name: str, gateway_region: str) -> str | None:
    client = boto3.client("bedrock-agentcore-control", region_name=gateway_region)
    try:
        response = client.list_gateways()
        for item in response.get("items", []):
            if item.get("name") != gateway_name:
                continue

            gateway_id = item["gatewayId"]
            gateway = client.get_gateway(gatewayIdentifier=gateway_id)
            return gateway["gatewayUrl"].rstrip("/")
    except Exception as e:
        logger.error(f"Error resolving AgentCore gateway URL for {gateway_name}: {e}")

    return None

def load_config(mcp_type):
    if mcp_type == "knowledge base":
        mcp_type = "kb-retriever"
    elif mcp_type == "aws documentation":
        mcp_type = "aws_documentation"    
    elif mcp_type == "trade info":
        mcp_type = "trade_info"
    elif mcp_type == "weather":
        mcp_type = "korea_weather"
    elif mcp_type == "image generation":
        mcp_type = "image_generation"
    
    if mcp_type == "aws_documentation":
        return {
            "mcpServers": {
                "awslabs.aws-documentation-mcp-server": {
                    "command": "uvx",
                    "args": ["awslabs.aws-documentation-mcp-server@latest"],
                    "env": {
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }

    elif mcp_type == "korea_weather":
        return {
            "mcpServers": {
                "korea-weather": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_korea_weather.py"]
                }
            }
        }
        
    elif mcp_type == "kb-retriever":
        return {
            "mcpServers": {
                "kb-retriever": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_retrieve.py"],
                    "env": {
                        "PYTHONPATH": workingDir,
                    },
                }
            }
        }
    
    elif mcp_type == "trade_info":
        return {
            "mcpServers": {
                "trade-info": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_trade_info.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "web_fetch":
        return {
            "mcpServers": {
                "web_fetch": {
                    "command": "npx",
                    "args": ["-y", "mcp-server-fetch-typescript"]
                }
            }
        }
    
    elif mcp_type == "image_generation":
        return {
            "mcpServers": {
                "imageGeneration": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_image_generation.py"
                    ]
                }
            }
        }

    elif mcp_type == "tavily":
        return {
            "mcpServers": {
                "tavily-search": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_tavily.py"
                    ]
                }
            }
        }

    elif mcp_type == "aws-tavily":
        agent_arn = get_agent_runtime_arn(mcp_type)
        logger.info(f"mcp_type: {mcp_type}, agent_arn: {agent_arn}")
        if not agent_arn:
            logger.info(
                "AgentCore aws-tavily MCP skipped: "
                f"runtime {AWS_TAVILY_RUNTIME_NAME} not found in {AWS_TAVILY_RUNTIME_REGION}."
            )
            return {}
        encoded_arn = agent_arn.replace(":", "%3A").replace("/", "%2F")
        mcp_url = (
            f"https://bedrock-agentcore.{AWS_TAVILY_RUNTIME_REGION}.amazonaws.com/runtimes/"
            f"{encoded_arn}/invocations?qualifier=DEFAULT"
        )
        return {
            "mcpServers": {
                "tavily-search": {
                    "type": "streamable_http",
                    "url": mcp_url,
                    "auth_type": "aws_sigv4",
                    "auth_region": AWS_TAVILY_RUNTIME_REGION,
                    "auth_service": "bedrock-agentcore",
                }
            }
        }

    elif mcp_type == "사용자 설정":
        return mcp_user_config

def load_selected_config(mcp_servers: dict):
    logger.info(f"mcp_servers: {mcp_servers}")
    
    loaded_config = {}
    for server in mcp_servers:
        config = load_config(server)
        if config:
            loaded_config.update(config["mcpServers"])
    return {
        "mcpServers": loaded_config
    }
