# Candle Lab — K 线 / 阴阳烛学习与统计

独立模块，**不会直接下单**。打开 bot 或手动运行 CLI 时，自动从历史 K 线学习形态胜率，并 **只读** 影响 bot 的 candle 信心权重。

## 对交易机械人的实际帮助

| 功能 | 帮助 |
|------|------|
| **自动胜率统计** | 知道「锤头在 AVAH 上 10 根 K 后胜率 58%」vs「黄昏星只有 32%」 |
| **弱形态过滤** | 胜率 < 40% 的形态不再触发 STRONG_BUY（config 开关） |
| **强形态加权** | 胜率 > 55% 时略微提高 `candle.strength` → 更高 confluence |
| **.symbol 级别** | 同一形态在不同股票上分开统计（AVAH vs SOFI） |
| **Quiz / 报告** | 帮你练眼力，weak spot 报告告诉你常认错的形态 |

## 不用供图

数据来自 **yfinance 历史 OHLCV**（与 bot 相同来源），不是截图。

## 命令

```bash
# 自动学习（watchlist 全部股票，约 1–2 分钟）
python -m candle_lab learn

# 查看胜率报告
python -m candle_lab report

# 导出 K 线图 PNG
python -m candle_lab chart --symbol AVAH

# 形态小测验
python -m candle_lab quiz --symbol AVAH
python -m candle_lab quiz --auto   # 非交互测试
```

## Bot 整合（只读）

`config.yaml`:

```yaml
candle:
  use_learned_stats: true      # 启用学习统计调整
  min_learned_win_rate: 0.40   # 低于此胜率的形态被 neutralize
  auto_learn_on_startup: true  # bot 启动时后台学习
```

学习结果保存在 `data/candle_learning/auto_stats.json`（已在 data/.gitignore）。

## 安全原则

- **不改** `CandlePatterns` 识别规则
- **不接入** `EntryPipeline` / `handle_buy` 下单路径
- 只调整 `trading_signals` 使用的 `candle.strength`
