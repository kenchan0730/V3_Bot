#!/usr/bin/env python3
import sys
print("="*60)
print("🔧 V4.0 系統診斷工具")
print("="*60)
print(f"\n✅ Python 版本: {sys.version}")

packages = ["ib_insync", "pandas", "numpy", "yfinance", "yaml", "requests", "pytz", "pytest", "finnhub"]
print("\n📦 套件檢查:")
for pkg in packages:
    try:
        __import__(pkg)
        print(f"   ✅ {pkg}")
    except ImportError:
        print(f"   ❌ {pkg}")

print("\n✅ 診斷完成")