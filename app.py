import streamlit as st
from agent import agent_executor  # 从 agent.py 导入 agent_executor

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

    # 调用 LangGraph agent（使用 invoke）
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            # LangGraph agent 的 invoke 方法
            response = agent_executor.invoke({"messages": [("human", prompt)]})
            # 获取最后一条消息的内容
            answer = response["messages"][-1].content
            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})