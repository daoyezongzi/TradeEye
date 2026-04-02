from config import config
from data_engine import get_clean_data
from strategies.strategy import check_signals
from notifier import send_report

def main():
    all_reports = []
    print(f"🏁 TradeEye 启动 | 模式: {'调试 (本地打印)' if config.DEBUG_MODE else '生产 (推送飞书)'}")
    
    for code in config.MY_STOCKS:
        data = get_clean_data(code)
        if not data: continue
        
        # 获取策略评分结果
        result = check_signals(data)
        
        # 组装更有“研究味”的报告
        report_line = (
            f"📌 {data['name']}({code})\n"
            f"   状态: {result['status']} (得分: {result['score']})\n"
            f"   逻辑: {result['detail']}\n"
            f"   量比: {result['vol_ratio']}\n"
            f"   ---"
        )
        all_reports.append(report_line)
        print(f"✅ {data['name']} 处理完成")

    # 4. 汇总发送
    if all_reports:
        send_report("\n".join(all_reports))
    else:
        print("⚠️ 今日无有效数据")

if __name__ == "__main__":
    main()

