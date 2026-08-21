# core/news_sentiment.py
import finnhub
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class NewsSentiment:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.api_key = self.config.get("finnhub_key", "")
        self.threshold = self.config.get("sentiment_threshold", -0.2)
        self.days = self.config.get("days_to_analyze", 3)
        
        self.client = finnhub.Client(api_key=self.api_key) if self.api_key else None
        
        # 简单的关键词情绪词典
        self.positive_words = ["beat", "surpass", "growth", "upgrade", "buy", "strong", "record", "high", "rise", "gain"]
        self.negative_words = ["miss", "downgrade", "sell", "weak", "low", "fall", "drop", "loss", "decline", "cut"]

    def get_sentiment(self, symbol):
        """获取股票新闻情绪评分（-1 到 +1）"""
        if not self.enabled or not self.client:
            return {"score": 0, "sentiment": "neutral", "total": 0, "details": []}

        try:
            # 获取最近 N 天新闻
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=self.days)).strftime("%Y-%m-%d")
            
            news = self.client.company_news(symbol, _from=start_date, to=end_date)
            
            if not news:
                return {"score": 0, "sentiment": "neutral", "total": 0, "details": []}

            # 分析每条新闻
            sentiments = []
            total_score = 0
            
            for item in news[:20]:  # 最多分析 20 条
                headline = item.get("headline", "").lower()
                score = self._analyze_headline(headline)
                sentiments.append({
                    "headline": headline[:80] + "..." if len(headline) > 80 else headline,
                    "score": score
                })
                total_score += score

            avg_score = total_score / len(sentiments) if sentiments else 0
            
            # 判断整体情绪
            if avg_score > 0.2:
                sentiment = "positive"
            elif avg_score < -0.2:
                sentiment = "negative"
            else:
                sentiment = "neutral"

            return {
                "score": round(avg_score, 3),
                "sentiment": sentiment,
                "total": len(sentiments),
                "details": sentiments[:5]  # 只返回前 5 条
            }

        except Exception as e:
            logger.error(f"新闻获取失败 {symbol}: {e}")
            return {"score": 0, "sentiment": "neutral", "total": 0, "details": []}

    def _analyze_headline(self, headline):
        """分析单条新闻标题的情绪分数"""
        score = 0
        for word in self.positive_words:
            if word in headline:
                score += 0.2
        for word in self.negative_words:
            if word in headline:
                score -= 0.2
        return max(-1, min(1, score))

    def is_sentiment_ok(self, symbol):
        """检查情绪是否可接受（非负面）"""
        result = self.get_sentiment(symbol)
        if result["sentiment"] == "negative":
            return False, f"📰 新闻情绪负面 (评分: {result['score']})"
        return True, f"📰 新闻情绪 {result['sentiment']} (评分: {result['score']})"