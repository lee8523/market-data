# market-data 共享行情模块

统一的行情获取模块，供 snowb / shahaz 及后续项目通过 **git submodule** 引用。
一套代码，统一维护数据源与 fallback 策略。

## 特性
- **实时价**：新浪 / 腾讯 / 东方财富 三源 fallback（带指数退避重试）
- **历史价**：新浪 / 东方财富 K线 双源 fallback（期初价、观察日收盘）
- **标的类型自动识别**：指数 / ETF / 期货 / 黄金，新增标的不改代码
  - 含字母：`AU`→黄金，其他字母→期货
  - 6位数字：`000/00`开头→指数，`5/6`开头→沪ETF，`1`开头→深ETF
  - 特殊标的可在 `SPECIAL_TYPES` 显式指定
- **批量接口**：`fetch_prices(codes)` 自动去重、逐标的多源 fallback

## 接入方式
```bash
git submodule add https://github.com/lee8523/market-data.git vendor/market-data
```
GitHub Actions 工作流 checkout 需加 `submodules: true`。

## 用法
```python
from market_data import fetch_price, fetch_prices, fetch_initial_price

price, date = fetch_price("000852")                    # 实时价
prices = fetch_prices(["000852", "588000", "AU9999"])  # 批量
price, date = fetch_initial_price("000852", "2026-08-07")  # 历史收盘
```

## 依赖
- `requests`
