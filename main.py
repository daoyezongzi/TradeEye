import requests
import os
import time

# 1. 变量配置
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_URL = "https://api.dify.ai/v1/workflows/run"

# 2. 你的自选股清单 (在这里修改代码)
# 沪市加 sh，深市加 sz
# 你的自选股清单 (修正版 2026-04-01)
MY_STOCKS = [
    "sh601880",  # 辽港股份 (大连港)
    "sh600157",  # 永泰能源
    "sh603010",  # 万盛股份
    "sz002372",  # 伟星新材 (确认是深市 002372)
    "sh600905",  # 三峡能源
]

def start_push():
    print(f"🚀 开始执行推送任务，共 {len(MY_STOCKS)} 只股票")
    
    for code in MY_STOCKS:
        payload = {
            "inputs": {"stock_code": code},
            "response_mode": "blocking",
            "user": "github_actions_v2"
        }
        headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        
        try:
            # 调用 Dify 工作流
            response = requests.post(DIFY_URL, json=payload, headers=headers)
            
            if response.status_code == 200:
                print(f"✅ 股票 {code} 推送指令已发出")
            else:
                print(f"❌ 股票 {code} 推送失败，错误码: {response.status_code}")
                
        except Exception as e:
            print(f"⚠️ 网络请求异常: {e}")
        
        # --- 重要：等待 3 秒 ---
        # 防止瞬间发送多条消息触发飞书机器人的频率限制 (Rate Limit)
        # 同时也给 Dify 的 LLM 留出生成时间
        time.sleep(3)

    print("🎊 所有自选股推送完成！")

if __name__ == "__main__":
    start_push()
