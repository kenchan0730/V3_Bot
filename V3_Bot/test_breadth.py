from core.market_breadth import MarketBreadth

breadth = MarketBreadth.get_breadth_score()
if breadth:
    print(f"📊 市場寬度: {breadth['score']}/100")
    print(f"📅 數據日期: {breadth['date']}")
    print(f"🏷️  健康區域: {breadth['zone']}")
    print("\n📈 各組件分數:")
    for key, val in breadth['components'].items():
        print(f"   {key}: {val}")
else:
    print("❌ 無法獲取數據")
