import requests
import os
import time

# 从 GitHub 的安全设置里读取 API Key
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_URL = "https://api.dify.ai/v1/workflows/run"

# 直接在这里写你的自选股，以后想改，直接在网页上改这个文件
MY_STOCKS = ["sh600519", "sz000001", "sh601318"]

def run():
    if not DIFY_API_KEY:
        print("错误：未找到 DIFY_API_KEY，请检查 Secret 设置")
        return

    for code in MY_STOCKS:
        payload = {
            "inputs": {"stock_code": code},
            "response_mode": "blocking",
            "user": "github_actions"
        }
        headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        
        try:
            r = requests.post(DIFY_URL, json=payload, headers=headers)
            print(f"发送 {code} 结果: {r.status_code}")
        except Exception as e:
            print(f"发送 {code} 报错: {e}")
        
        time.sleep(2) # 间隔防止飞书限流

if __name__ == "__main__":
    run()
