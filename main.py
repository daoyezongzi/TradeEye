import os
import requests
import datetime
from config import config
from data_engine import get_clean_data
from strategies.strategy import check_signals
from notifier import send_report

def get_dify_analysis(stock_data, tech_result, stock_code):
    """接入 Dify 工作流 (Workflow) 获取资深交易员视角的深度复盘"""
    
    # 1. 组装输入数据：将本地计算的硬核指标（得分、逻辑）全部喂给 AI
    # 这里必须包含现价、MA20、量比等，以满足你 Prompt 中“数据内化”的要求
    input_text = (
        f"名称:{stock_data.get('name')}, 代码:{stock_code}, 现价:{stock_data.get('now') or stock_data.get('price')}, "
        f"MA20:{stock_data.get('ma20')}, 量比:{tech_result.get('vol_ratio')}, 换手率:{stock_data.get('turnover')}, "
        f"本地得分:{tech_result.get('score')}, 技术逻辑:{tech_result.get('detail')}, "
        f"今日高点:{stock_data.get('high')}, 今日最低:{stock_data.get('low')}, 昨日低点:{stock_data.get('last_low')}"
    )
    
    # 2. 直接使用 Dify 官方工作流标准 API 地址
    # 无需在 config 中配置 DIFY_BASE_URL
    url = "https://api.dify.ai/v1/workflows/run"
    
    headers = {
        "Authorization": f"Bearer {config.DIFY_API_KEY}", # 严格使用你的 API 变量名
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": {"stock_data": input_text}, # ⚠️ 确保 Dify 工作流开始节点的变量名是 stock_data
        "response_mode": "blocking",
        "user": "TradeEye_Runner"
    }
    
    try:
        # 发起请求
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status() 
        
        res_data = response.json()
        
        # 3. 提取工作流输出（通常在 data -> outputs -> text）
        # 如果你的结束节点变量名不是 text，请同步修改下方 get('text')
        analysis_result = res_data.get('data', {}).get('outputs', {}).get('text')
        
        return analysis_result or "⚠️ 工作流运行成功但未返回有效文本"
        
    except Exception as e:
        return f"❌ Dify 工作流调用失败: {str(e)}"

def main():
    all_reports = []
    is_debug = config.DEBUG_MODE
    print(f"🏁 TradeEye 启动 | 模式: {'调试 (本地打印)' if is_debug else '生产 (推送飞书)'}")
    
    for code in config.MY_STOCKS:
        # 1. 获取本地清洗后的实时行情
        data = get_clean_data(code)
        if not data: continue
        
        # 2. 执行本地策略：计算量比、得分、主力洗盘等硬核逻辑
        tech_result = check_signals(data)
        
        # 3. 将本地数据发送给 Dify 工作流进行深度复盘
        print(f"正在为 {data.get('name')} 请求 AI 深度分析...")
        ai_analysis = get_dify_analysis(data, tech_result, code)
        
        # 4. 汇总报告
        all_reports.append(ai_analysis)
        print(f"✅ {data.get('name')} 分析完成")

    # 5. 最终汇总发送
    if all_reports:
        today = datetime.date.today().strftime('%Y-%m-%d')
        final_content = f"📊 {today} 个股复盘汇总报告：\n\n" + "\n\n".join(all_reports)
        
        # 调用通知模块发送（send_report 内部会处理是 print 还是发 Webhook）
        send_report(final_content)
    else:
        print("⚠️ 今日无有效股票数据")

if __name__ == "__main__":
    main()