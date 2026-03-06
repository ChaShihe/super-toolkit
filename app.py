import streamlit as st
from agent import agent_executor
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

st.title("我的超级个人工具包")

# 初始化会话历史
if "messages" not in st.session_state:
    st.session_state.messages = []

# 显示历史消息
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 处理用户输入
if prompt := st.chat_input("你有什么需要？"):
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用 Agent（带错误处理）
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            try:
                # 调用 LangGraph agent
                response = agent_executor.invoke({"messages": [("human", prompt)]})
                answer = response["messages"][-1].content
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            
            except APIConnectionError as e:
                error_msg = "⚠️ 网络连接出现问题，可能是服务器暂时无法访问。请稍后重试。"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except AuthenticationError as e:
                error_msg = "🔑 API 密钥认证失败，请联系管理员检查配置。"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except RateLimitError as e:
                error_msg = "⏳ 请求过于频繁，已达到 API 速率限制。请稍后再试。"
                st.warning(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except APIError as e:
                error_msg = f"🤖 API 返回错误：{e.message if hasattr(e, 'message') else str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except Exception as e:
                # 捕获所有其他未知异常
                error_msg = f"😵 发生未知错误：{str(e)[:100]}..."  # 截断显示，避免暴露敏感信息
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})