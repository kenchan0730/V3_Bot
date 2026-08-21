import streamlit as st

st.title("🏠 首頁")
st.write("歡迎使用 V4.5 交易系統儀表板。")

st.markdown("""
### 快速導覽

- **儀表板** — 機器人狀態、帳戶盈虧、持倉、組合風險、即時信號與稽核軌跡。
- **關於** — 系統架構與版本資訊。

### 常用指令

```bash
python main.py                # 依 config.yaml 執行（預設僅信號）
python main.py --dry-run      # 強制不下單
python main.py --once         # 只掃描一次
streamlit run app.py          # 啟動本儀表板
pytest --cov=core             # 執行測試
```

詳細運維程序請參閱 `RUNBOOK.md`。
""")
