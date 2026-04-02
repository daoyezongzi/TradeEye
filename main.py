import os
import requests
from config import config
from data_engine import get_clean_data
from strategies.strategy import check_signals
from notifier import send_report

def get_dify_analysis(stock_data, tech_result, stock_code):
    """调用 Dify 工作流，获取资深交易员视角的分析"""
    
    # 自动适配键名：如果没找到 'now'，就找 'price'
    now_price = stock_data.get('now') or stock_data.get('price', '无数据')
    turnover = stock_data.get('turnover') or stock_data.get('turnover_rate', '无数据')
    
    # 构造发给 Dify 的 Context
    input_text = (
        f"名称:{stock_data.get('name', '未知')}, 代码:{stock_code}, 现价:{now_price}, "
        f"MA20:{stock_data.get('ma20', '无数据')}, 量比:{tech_result.get('vol_ratio', '无数据')}, "
        f"换手率:{turnover}, 本地得分:{tech_result.get('score', 0)}, "
        f"技术逻辑:{tech_result.get('detail', '无')}, "
        f"今日高点:{stock_data.get('high', '无数据')}, 今日最低:{stock_data.get('low', '无数据')}, "
        f"昨日低点:{stock_data.get('last_low', '无数据')}"
    )
    
    headers = {
        "Authorization": f"Bearer {config.DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "inputs": {"stock_data": input_text}, # 确保这与你 Dify 里的变量名一致
        "response_mode": "blocking",
        "user": "TradeEye_Runner"
    }
    
    try:
        # 这里的 URL 建议也用 config.DIFY_API_KEY 拼接
        response = requests.post(f"{config.DIFY_API_KEY}/completion-messages", headers=headers, json=data)
        res_json = response.json()
        return res_json.get('answer', "AI 分析内容为空，请检查 Dify 工作流输出")
    except Exception as e:
        return f"Dify 调用异常: {str(e)}"

def main():
    all_reports = []
    # 模式判断：只有当环境变量存在且非调试模式时才真正推送
    is_debug = config.DEBUG_MODE
    print(f"🏁 TradeEye 启动 | 模式: {'调试 (本地打印)' if is_debug else '生产 (推送飞书)'}")
    
    for code in config.MY_STOCKS:
        # 1. 获取本地清洗后的实时数据
        data = get_clean_data(code)
        if not data: continue
        
        # 2. 获取本地策略计算的硬指标（量比、得分、逻辑趋势）
        tech_result = check_signals(data)
        
        # 3. 将本地数据喂给 Dify 资深交易员 Prompt
        print(f"正在为 {data['name']} 请求 AI 深度分析...")
        ai_analysis = get_dify_analysis(data, tech_result, code)
        
        # 4. 组装最终报告：保留 AI 的严苛风格
        all_reports.append(ai_analysis)
        print(f"✅ {data['name']} 分析完成")

    # 5. 汇总发送
    if all_reports:
        final_content = "\n\n" + "\n".join(all_reports)
        send_report(final_content)
    else:
        print("⚠️ 今日无有效数据")

if __name__ == "__main__":
    main()