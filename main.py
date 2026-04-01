import requests
import os
import time

# 1. 变量配置
# 从 GitHub Secrets 中读取 DIFY_API_KEY
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "").strip()
# 确保使用 Dify 官方云端 API 地址
DIFY_URL = "https://api.dify.ai/v1/workflows/run"

# 2. 你的自选股清单 (2026-04-01 修正版)
MY_STOCKS = [
    "sh601880",  # 辽港股份
    "sh600157",  # 永泰能源
    "sh603010",  # 万盛股份
    "sz002372",  # 伟星新材
    "sh600905",  # 三峡能源
]

def start_push():
    if not DIFY_API_KEY:
        print("❌ 错误: 未能在环境变量中找到 DIFY_API_KEY，请检查 GitHub Secrets 配置。")
        return

    print(f"🚀 开始执行推送任务，共 {len(MY_STOCKS)} 只股票")
    
    for code in MY_STOCKS:
        # 构造请求体，inputs 里的 key 必须与 Dify "开始" 节点定义的变量名一致
        payload = {
            "inputs": {"stock_code": code},
            "response_mode": "blocking",
            "user": "github_actions_bot"
        }
        
        # 核心鉴权 Header
        headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        
        try:
            # 发起 POST 请求
            response = requests.post(DIFY_URL, json=payload, headers=headers, timeout=60)
            
            if response.status_code == 200:
                print(f"✅ 股票 {code} 推送成功！")
            elif response.status_code == 401:
                print(f"❌ 股票 {code} 认证失败 (401)：请检查 GitHub Secrets 中的 API Key 是否正确。")
            elif response.status_code == 404:
                print(f"❌ 股票 {code} 路径错误 (404)：请检查 DIFY_URL 是否正确。")
            else:
                print(f"❌ 股票 {code} 推送失败，返回码: {response.status_code}")
                print(f"📝 错误详情: {response.text}")
                
        except Exception as e:
            print(f"⚠️ 网络请求异常 ({code}): {e}")
        
        # 间隔 5 秒，防止触发 API 频率限制或飞书机器人限流
        time.sleep(5)

    print("🎊 所有自选股推送完成！")

if __name__ == "__main__":
    start_push()
