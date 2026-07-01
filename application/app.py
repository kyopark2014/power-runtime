import streamlit as st 
import chat
import json
import logging
import os
import sys
import agentcore_client
import utils
from notification_queue import NotificationQueue

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("streamlit")

config = utils.load_config()

_application_dir = os.path.dirname(os.path.abspath(__file__))


def load_capability_list(filename: str) -> list:
    path = os.path.join(_application_dir, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except FileNotFoundError:
        logger.warning(f"Capability list not found: {path}")
        return []


os.environ["DEV"] = "true"  # Skip user confirmation of get_user_input

# title
st.set_page_config(page_title='AgentCore', page_icon=None, layout="centered", initial_sidebar_state="auto", menu_items=None)


@st.dialog("User ID 입력")
def request_user_id() -> None:
    st.markdown("시작하려면 User ID를 입력하세요.")
    user_id = st.text_input("User ID", key="user_id_input", placeholder="예: user01")
    if st.button("시작", type="primary", use_container_width=True):
        if user_id.strip():
            st.session_state.user_id = user_id.strip()
            chat.user_id = user_id.strip()
            st.rerun()
        else:
            st.error("User ID를 입력해주세요.")


if not st.session_state.get("user_id"):
    request_user_id()
    st.stop()

chat.user_id = st.session_state.user_id

mode_descriptions = {
    "Agent": [
        "MCP/SKILL를 활용한 Agent를 이용합니다. 왼쪽 메뉴에서 필요한 MCP를 선택하세요."
    ],
    "Agent (Chat)": [
        "MCP/SKILL를 활용한 Agent를 이용합니다. 채팅 히스토리를 이용해 interative한 대화를 즐길 수 있습니다."
    ]
}

with st.sidebar:
    st.title("🔮 Menu")
    
    st.markdown(
        "Amazon의 AgentCore을 이용해 Agent를 구현합니다." 
        "상세한 코드는 [Github](https://github.com/kyopark2014/power-runtime)을 참조하세요."
    )

    st.subheader("🐱 대화 형태")
    
    # radio selection
    mode = st.radio(
        label="원하는 대화 형태를 선택하세요. ",options=["Agent", "Agent (Chat)"], index=1
    )   
    st.info(mode_descriptions[mode][0])
    
    # mcp selection    
    if mode=='Agent' or mode=='Agent (Chat)':
        st.subheader("⚙️ Skill Config")

        skill_selections = {}
        skill_options = load_capability_list("skills.list")
        default_skill_selections = config.get("default_skills") or []
        if not default_skill_selections and "skill-creator" in skill_options:
            default_skill_selections = ["skill-creator"]
        default_skill_selections = [name for name in default_skill_selections if name in skill_options]
        logger.info(f"default_skill_selections: {default_skill_selections}")
        with st.expander("Skill 옵션 선택", expanded=True):
            logger.info(f"skill_options: {skill_options}")
            for name in skill_options:
                default_value = name in default_skill_selections
                skill_selections[name] = st.checkbox(
                    name,
                    key=f"skill_{name}",
                    value=default_value,
                    disabled=False,
                )

        selected_skills = [name for name, is_selected in skill_selections.items() if is_selected]
        logger.info(f"selected_skills: {selected_skills}")

        if selected_skills != config.get("default_skills"):
            config["default_skills"] = selected_skills
            with open(utils.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)

        # MCP Config JSON input
        st.subheader("⚙️ MCP Config")

        # Change radio to checkbox
        mcp_options = load_capability_list("mcp.list")
        mcp_selections = {}
        default_selections = config.get("default_mcp_servers") or ["web_fetch", "aws-tavily"]
        default_selections = [name for name in default_selections if name in mcp_options]
        # tavily(stdio)와 aws-tavily는 동일 tavily-search 서버명을 쓰므로 동시 선택 방지
        if "tavily" in default_selections and "aws-tavily" in default_selections:
            default_selections = [n for n in default_selections if n != "tavily"]

        with st.expander("MCP 옵션 선택", expanded=True):
            for option in mcp_options:
                default_value = option in default_selections
                mcp_selections[option] = st.checkbox(
                    option, key=f"mcp_{option}", value=default_value
                )
        
        # if not any(mcp_selections.values()):
        #     mcp_selections["basic"] = True

        mcp_servers = [server for server, is_selected in mcp_selections.items() if is_selected]
        if "tavily" in mcp_servers and "aws-tavily" in mcp_servers:
            mcp_servers = [s for s in mcp_servers if s != "tavily"]
            logger.info("Both tavily and aws-tavily selected; using aws-tavily only.")
    else:
        mcp_servers = []
        selected_skills = []

    # model selection box
    modelName = st.selectbox(
        '🖊️ 사용 모델을 선택하세요',
        (
            "Claude 5.0 Sonnet",
            "Claude 4.6 Sonnet",
            "Claude Fable 5",
            "Claude 4.8 Opus",
            "Claude 4.7 Opus",
            "Claude 4.6 Opus",
            "Claude 4.5 Opus",
            "Claude 4.5 Sonnet",
            "Claude 4.5 Haiku",
            "OpenAI GPT 5.4",
            "OpenAI GPT 5.5",
            "OpenAI OSS 120B",
            "OpenAI OSS 20B",
        ), index=0
    )
    chat.update(modelName)

    st.success(f"Connected to {modelName}", icon="💚")
    clear_button = st.button("대화 초기화", key="clear")
    # logger.info(f"clear_button: {clear_button}")


st.title('🔮 '+ mode)

if clear_button or "messages" not in st.session_state:
    st.session_state.messages = []        
    uploaded_file = None
    
    st.session_state.greetings = False
    st.rerun()  

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greetings = False

# Display chat messages from history on app rerun
def display_chat_messages() -> None:
    """Print message history
    @returns None
    """
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if "images" in message:                
                for url in message["images"]:
                    logger.info(f"url: {url}")

                    file_name = url[url.rfind('/')+1:]
                    st.image(url, caption=file_name, use_container_width=True)
            st.markdown(message["content"])

display_chat_messages()

# Greet user
if not st.session_state.greetings:
    with st.chat_message("assistant"):
        intro = "아마존 베드락을 이용하여 주셔서 감사합니다. 편안한 대화를 즐기실수 있으며, 파일을 업로드하면 요약을 할 수 있습니다."
        st.markdown(intro)
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": intro})
        st.session_state.greetings = True

if clear_button or "messages" not in st.session_state:
    st.session_state.messages = []        
    uploaded_file = None
    
    st.session_state.greetings = False
    chat.initiate()
    st.rerun()    

# Always show the chat input
if prompt := st.chat_input("메시지를 입력하세요."):
    with st.chat_message("user"):  # display user message in chat message container
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})  # add user message to chat history
    prompt = prompt.replace('"', "").replace("'", "")
    logger.info(f"prompt: {prompt}")

    with st.chat_message("assistant"):
        if mode == 'Agent' or mode == 'Agent (Chat)':            
            sessionState = ""
            if mode == 'Agent':
                history_mode = "Disable"
            else:
                history_mode = "Enable"

            with st.status("thinking...", expanded=True, state="running") as status:
                logger.info(f"mcp_servers: {mcp_servers}")

                notification_queue = NotificationQueue(container=status)
                skill_list = selected_skills if selected_skills else []
                logger.info(f"skill_list: {skill_list}")

                response, image_url = agentcore_client.run_agent(
                    prompt, chat.user_id, history_mode, mcp_servers, modelName, notification_queue,
                    skill_list=skill_list,
                )

            st.session_state.messages.append({
                "role": "assistant", 
                "content": response,
                "images": image_url if image_url else []
            })

            for url in image_url:
                    logger.info(f"url: {url}")
                    file_name = url[url.rfind('/')+1:]
                    st.image(url, caption=file_name, use_container_width=True)

        