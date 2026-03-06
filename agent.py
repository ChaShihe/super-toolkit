import os
import re
import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langgraph.prebuilt import create_react_agent
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
import time
import random
import urllib.parse
import hashlib
import json
from urllib.parse import urlencode
import streamlit as st
import base64
import qrcode
from io import BytesIO

load_dotenv()

# 优先从 Streamlit Secrets 读取，失败则从 .env 读取（本地开发用）
def get_secret(key):
    """兼容本地 .env 和云端 secrets 的密钥读取函数"""
    try:
        # 尝试从 Streamlit secrets 读取
        return st.secrets[key]
    except:
        # 失败则从环境变量读取（本地 .env）
        return os.getenv(key)

# ========== 工具函数（与之前完全相同） ==========
def get_weather(city: str) -> str:
    # ... (你的高德天气代码) ...
    api_key = get_secret("AMAP_API_KEY")
    if not api_key:
        return "错误：未找到高德地图API密钥，请在.env文件中设置AMAP_API_KEY"
    url = "https://restapi.amap.com/v3/weather/weatherInfo"
    params = {
        "key": api_key,
        "city": city,
        "extensions": "base",
        "output": "JSON"
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if data.get("status") == "1" and data.get("lives"):
            live = data["lives"][0]
            return (f"{live['province']}{live['city']} 天气：{live['weather']}，"
                    f"温度：{live['temperature']}℃，{live['winddirection']}风{live['windpower']}级，湿度：{live['humidity']}%")
        else:
            return f"天气查询失败：{data.get('info', '未知错误')}"
    except Exception as e:
        return f"天气查询出错：{str(e)}"

def create_event(event_desc: str) -> str:
    print(f"[模拟] 创建日程：{event_desc}")
    return f"已为您创建日程：{event_desc}"

def search_wiki(query: str) -> str:
    """
    搜索百度百科，返回词条摘要。如果失败，返回空字符串（让 Agent 用自己的知识回答）。
    """
    encoded_query = urllib.parse.quote(query)
    
    # 初始化随机 User-Agent
    ua = UserAgent()
    
    # 尝试的 URL 列表（PC 端和移动端）
    urls_to_try = [
        f"https://baike.baidu.com/item/{encoded_query}",          # 移动端
        f"https://baike.baidu.com/lemma?q={encoded_query}",       # PC 端备选
        f"https://baike.baidu.com/search?word={encoded_query}"    # 搜索页
    ]
    
    # 通用的请求头，模拟浏览器
    headers = {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://baike.baidu.com/",
        "Cache-Control": "max-age=0",
    }
    
    # 随机延时，避免请求过快
    time.sleep(random.uniform(1, 3))
    
    session = requests.Session()
    
    # 遍历 URL 尝试
    for url in urls_to_try:
        try:
            response = session.get(url, headers=headers, timeout=10)
            
            # 如果返回 403，可能是反爬，短暂休眠后尝试下一个 URL
            if response.status_code == 403:
                print(f"[百科] 访问 {url} 被拒绝 (403)，尝试下一个...")
                time.sleep(random.uniform(2, 4))
                continue
            
            if response.status_code != 200:
                continue
            
            # 解析页面
            soup = BeautifulSoup(response.text, 'lxml')
            
            # 获取标题（多种可能的选择器）
            title_elem = (soup.find('h1') or 
                         soup.find('dt', class_='lemmaTitle') or 
                         soup.find('span', class_='lemmaTitle'))
            title = title_elem.text.strip() if title_elem else query
            
            # 获取摘要（多种可能的选择器）
            summary_elem = (soup.find('div', class_='lemma-summary') or 
                           soup.find('div', class_='card-summary') or 
                           soup.find('div', class_='abstract') or
                           soup.find('meta', attrs={'name': 'description'}))
            
            if summary_elem:
                # 如果找到的是 meta 标签，取 content 属性
                if summary_elem.name == 'meta':
                    summary = summary_elem.get('content', '')
                else:
                    summary = summary_elem.get_text(strip=True)
                
                # 清理并截断
                summary = summary.replace('\n', '').replace('\r', '').replace('\xa0', ' ')
                if len(summary) > 300:
                    summary = summary[:300] + "……"
                return f"关于「{title}」：{summary}"
            else:
                # 如果没有摘要，至少返回词条存在的信息
                return f"已找到「{title}」的百科词条，但无法提取摘要。你可以访问 {url} 查看详情。"
                
        except Exception as e:
            print(f"[百科] 访问 {url} 出错: {e}")
            continue
    
    # 所有尝试都失败，返回空字符串，让 Agent 用自己的知识回答
    return ""

def convert_currency(query: str) -> str:
    """
    汇率转换工具 - 使用 ExchangeRate-API 官方密钥版
    支持输入如：100美元是多少人民币、50欧元换英镑
    """
    print(f"[汇率调试] 收到输入: {query}")
    try:
        # ========== 使用正则提取金额 ==========
        amount_match = re.search(r'(\d+(?:\.\d+)?)', query)
        if not amount_match:
            return "请告诉我具体的金额，例如：100美元是多少人民币"
        amount = float(amount_match.group(1))

        # ========== 货币名称映射 ==========
        currency_map = {
            "美元": "USD", "美金": "USD", "usd": "USD",
            "人民币": "CNY", "rmb": "CNY", "cny": "CNY",
            "欧元": "EUR", "欧": "EUR", "eur": "EUR",
            "英镑": "GBP", "gbp": "GBP",
            "日元": "JPY", "日圆": "JPY", "jpy": "JPY",
            "港币": "HKD", "hkd": "HKD",
            "韩元": "KRW", "krw": "KRW",
            "澳元": "AUD", "aud": "AUD",
            "加元": "CAD", "cad": "CAD",
            "法郎": "CHF", "chf": "CHF",
            "泰铢": "THB", "thb": "THB",
            "新加坡元": "SGD", "sgd": "SGD",
            "新西兰元": "NZD", "nzd": "NZD",
        }

        # ========== 提取来源货币 ==========
        from_currency = None
        # 优先匹配三位字母代码
        code_match = re.search(r'\b([A-Za-z]{3})\b', query.upper())
        if code_match:
            from_currency = code_match.group(1)
        else:
            # 匹配中文货币名称
            for ch_name, code in currency_map.items():
                if ch_name in query:
                    from_currency = code
                    break

        if not from_currency:
            return "我没识别出您要转换的货币类型，请指定如美元、人民币、欧元等"

        # ========== 提取目标货币 ==========
        to_currency = None
        # 查找“多少”、“换”、“兑换”等后面的内容
        target_match = re.search(r'(?:多少|换|兑换|转|成)\s*([^0-9]+)', query)
        if target_match:
            target_text = target_match.group(1).strip()
            # 尝试匹配三位字母代码
            if re.match(r'^[A-Za-z]{3}$', target_text):
                to_currency = target_text.upper()
            else:
                # 匹配中文
                for ch_name, code in currency_map.items():
                    if ch_name in target_text:
                        to_currency = code
                        break
        if not to_currency:
            to_currency = "CNY"  # 默认目标为人民币

        print(f"[汇率调试] 解析结果: 金额={amount}, 从={from_currency}, 到={to_currency}")

        # ========== API 调用（使用 API Key） ==========
        api_key = get_secret("EXCHANGE_RATE_API_KEY")
        if not api_key:
            return "错误：未找到汇率API密钥，请在.env文件中设置EXCHANGE_RATE_API_KEY"

        url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{from_currency.upper()}"
        print(f"[汇率调试] 请求URL: {url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(url, headers=headers, timeout=10)
        print(f"[汇率调试] HTTP状态码: {response.status_code}")

        data = response.json()
        print(f"[汇率调试] API返回: {data}")  # 注意：这里会打印完整返回，可看到 error-type 等

        if data.get("result") != "success":
            error_type = data.get("error-type", "未知错误")
            return f"汇率查询失败: {error_type}"

        rates = data.get("conversion_rates", {})
        target = to_currency.upper()
        if target not in rates:
            # 尝试大小写不敏感匹配
            for code in rates.keys():
                if code.upper() == target:
                    target = code
                    break
            else:
                return f"不支持目标货币: {to_currency}"

        rate = rates[target]
        converted = amount * rate
        update_time = data.get("time_last_update_utc", "最近更新")

        # 货币代码转中文显示（可选）
        reverse_map = {v: k for k, v in currency_map.items()}
        from_display = reverse_map.get(from_currency.upper(), from_currency.upper())
        to_display = reverse_map.get(target, target)

        return (f"{amount:.2f} {from_display} ≈ {converted:.2f} {to_display}\n"
                f"汇率: 1 {from_display} = {rate:.4f} {to_display}\n"
                f"数据来源: ExchangeRate-API {update_time}")

    except requests.exceptions.RequestException as e:
        return f"网络连接失败: {str(e)}，请稍后重试"
    except Exception as e:
        return f"汇率转换出错: {str(e)}"

def track_express(query: str) -> str:
    """
    快递查询工具 - 使用快递100 API
    支持输入如：查快递 单号123456、顺丰快递SF1234567890
    """
    print(f"[快递调试] 收到输入: {query}")
    try:
        # ========== 解析快递单号 ==========
        number_match = re.search(r'[A-Za-z0-9]{6,}', query)
        if not number_match:
            return "请提供快递单号，例如：查快递 12345678 或 顺丰SF1234567890"
        
        tracking_number = number_match.group(0).strip()
        
        # 快递公司映射（可选，用于用户指定公司）
        express_companies = {
            "顺丰": "shunfeng", "sf": "shunfeng",
            "申通": "shentong", "sto": "shentong",
            "圆通": "yuantong", "yto": "yuantong",
            "韵达": "yunda", "yd": "yunda",
            "中通": "zhongtong", "zto": "zhongtong",
            "京东": "jd", "jd": "jd",
            "邮政": "ems", "ems": "ems",
            "极兔": "jitu", "jtexpress": "jitu",
        }
        
        company_code = None
        for keyword, code in express_companies.items():
            if keyword in query.lower():
                company_code = code
                break
        
        print(f"[快递调试] 单号: {tracking_number}, 指定公司: {company_code or '自动识别'}")
        
        # ========== 读取API凭证 ==========
        key = get_secret("KUAIDI100_KEY")
        customer = get_secret("KUAIDI100_CUSTOMER")
        if not key or not customer:
            return "错误：未找到快递100API凭证，请在.env文件中设置KUAIDI100_KEY和KUAIDI100_CUSTOMER"
        
        # ========== 构建请求参数 ==========
        param = {
            "com": company_code or "",  # 为空则自动识别
            "num": tracking_number,
            "phone": "",  # 可选，某些快递需要手机号后四位
        }
        # 生成无空格的JSON字符串
        param_str = json.dumps(param, separators=(',', ':'))
        print(f"[快递调试] param_str: {param_str}")
        
        # ========== 生成签名 ==========
        # 规则：MD5(param_str + key + customer).upper()
        raw_str = param_str + key + customer
        print(f"[快递调试] 签名原始串: {raw_str}")
        sign = hashlib.md5(raw_str.encode()).hexdigest().upper()
        print(f"[快递调试] 生成的签名: {sign}")
        
        # ========== 构造POST数据 ==========
        post_data = {
            "customer": customer,
            "sign": sign,
            "param": param_str,
        }
        # 快递100要求 x-www-form-urlencoded 格式
        encoded_data = urlencode(post_data)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        url = "https://poll.kuaidi100.com/poll/query.do"
        print(f"[快递调试] 请求URL: {url}")
        print(f"[快递调试] POST数据: {post_data}")
        
        response = requests.post(url, data=encoded_data, headers=headers, timeout=10)
        print(f"[快递调试] HTTP状态码: {response.status_code}")
        
        result = response.json()
        print(f"[快递调试] API返回: {result}")
        
        # ========== 处理返回结果 ==========
        if result.get("result") is False:
            error_msg = result.get("message", "查询失败")
            return f"快递查询失败: {error_msg}"
        
        company = result.get("com", "")
        nu = result.get("nu", tracking_number)
        status = result.get("state", "0")
        status_map = {"0": "在途", "1": "已揽收", "2": "疑难", "3": "已签收", "4": "退签", "5": "派件中", "6": "退回"}
        status_text = status_map.get(str(status), "未知")
        
        data_list = result.get("data", [])
        if not data_list:
            return f"快递单号 {tracking_number} 暂无物流信息，当前状态: {status_text}"
        
        output = [f"📦 快递单号: {nu}"]
        output.append(f"📊 当前状态: {status_text}")
        output.append("")
        output.append("📅 物流轨迹:")
        for i, item in enumerate(data_list[:5]):
            time_str = item.get("time", "")
            context = item.get("context", "")
            output.append(f"{time_str} {context}")
        
        return "\n".join(output)
        
    except requests.exceptions.RequestException as e:
        return f"网络连接失败: {str(e)}，请稍后重试"
    except Exception as e:
        return f"快递查询出错: {str(e)}"

def get_joke(query: str) -> str:
    """随机返回一条笑话"""
    api_key = get_secret("TIAN_API_KEY")
    if not api_key:
        return "请先在 .env 中配置天行数据 API 密钥"
    url = f"http://api.tianapi.com/joke/index?key={api_key}&num=1"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data["code"] == 200:
            joke = data["newslist"][0]["content"]
            return f"😄 {joke}"
        else:
            return "笑话接口暂时无法使用，稍后再试吧"
    except:
        return "获取笑话失败，请稍后重试"

def generate_qrcode(text: str) -> str:
    """
    使用 qrcode 库在本地生成二维码，并显示在 Streamlit 中
    """
    print(f"[二维码调试] 收到输入: {text}")
    if not text or text.strip() == "":
        return "请输入要生成二维码的内容，例如：https://example.com 或 我的联系方式"
    
    try:
        # 生成二维码
        qr = qrcode.QRCode(
            version=1,
            box_size=10,
            border=5
        )
        qr.add_data(text.strip())
        qr.make(fit=True)
        
        # 创建图片
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 将图片转换为 base64 编码，以便在 Markdown 中显示
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        # 返回 base64 图片的 Markdown 格式
        return f"![二维码](data:image/png;base64,{img_base64})\n\n您的内容：{text}"
    except Exception as e:
        return f"二维码生成失败：{str(e)}"

# ========== 工具列表 ==========
tools = [
    Tool(name="weather_query", func=get_weather, description="输入城市名，查询实时天气，例如：北京天气"),
    Tool(name="create_event", func=create_event, description="输入日程描述，例如：明天下午3点开会"),
    Tool(name="wiki_search", func=search_wiki, description="输入关键词，查询百科知识，例如：人工智能"),
    Tool(
        name="currency_converter", 
        func=convert_currency, 
        description="汇率转换，输入金额和货币名称，例如：100美元是多少人民币、50欧元换英镑"
    ),
    Tool(
        name="express_tracking", 
        func=track_express, 
        description="快递查询，输入快递单号，可以指定快递公司名称，例如：查快递 12345678 或 顺丰SF1234567890"
    ),
    Tool(
        name="tell_joke", 
        func=get_joke, 
        description="获取随机笑话，输入‘讲个笑话’或‘笑话’"
    ),
    Tool(
        name="qrcode_generator", 
        func=generate_qrcode, 
        description="生成二维码，输入任意文本（如网址、联系方式、文字），返回对应的二维码图片。例如：生成二维码 https://example.com",
        return_direct=True
    ),
]

# ========== 初始化 DeepSeek 模型 ==========
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0,
    openai_api_key=get_secret("DEEPSEEK_API_KEY"),
    openai_api_base="https://api.deepseek.com/v1",
    max_tokens=1024,
)

# ========== 系统提示词 ==========
# LangGraph 的 create_react_agent 接受一个 system_prompt 参数
system_prompt = """你是一个有帮助的助手。你可以使用以下工具来回答用户的问题：
- 天气查询：输入城市名查询实时天气。
- 创建日程：输入日程描述来创建提醒。
- 维基百科：输入关键词查询百科知识。

请根据用户的请求，选择合适的工具来提供帮助。"""

# ========== 使用 LangGraph 创建 Agent ==========
# 注意：这里直接调用 langgraph.prebuilt 中的函数，无需 AgentExecutor [citation:1]
agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt=system_prompt  # LangGraph 使用 prompt 参数传入系统提示词 [citation:1]
)

agent_executor = agent

__all__ = ["agent_executor"]

# ========== 主交互循环 ==========
if __name__ == "__main__":
    print("超级个人工具包（LangGraph版）已启动，输入 exit 退出")
    while True:
        user_input = input("\n你：")
        if user_input.lower() in ["exit", "quit"]:
            break
        # LangGraph agent 可以直接 invoke，传入一个包含消息的字典
        # 它会自动管理多轮对话的状态 [citation:1]
        response = agent.invoke({"messages": [("human", user_input)]})
        # 输出最后的 AI 消息内容
        print(f"助手：{response['messages'][-1].content}")
    