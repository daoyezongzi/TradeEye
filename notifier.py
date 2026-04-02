import requests
from config import config

def send_report(content):
    if config.DEBUG_MODE:
        print("\n" + "🚀" * 10 + " [DEBUG 模式模拟推送] " + "🚀" * 10)
        print(content)
        print("=" * 50 + "\n")
        return
        
    # 生产模式正式推送
    payload = {
        "msg_type": "text",
        "content": {"text": f"📊 个股盘后复盘报告：\n\n{content}"}
    }
    try:
        requests.post(config.FEISHU_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")