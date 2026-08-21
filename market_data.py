#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享行情模块 market_data
====================
- 实时价：新浪 / 腾讯 / 东方财富 多源 fallback
- 历史价：新浪 / 东方财富 K线 双源 fallback
- 标的类型自动识别（指数 / ETF / 期货 / 黄金），新增标的不改代码

用法：
    from market_data import fetch_price, fetch_prices, fetch_initial_price

    price, date = fetch_price("000852")                 # 实时价
    prices = fetch_prices(["000852", "588000", "AU9999"])  # 批量
    price, date = fetch_initial_price("000852", "2026-08-07")  # 历史收盘

各项目通过 git submodule 引用本模块，统一维护数据源与 fallback 策略。
"""
import re
import time
from datetime import datetime

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 可覆盖的类型映射：特殊标的显式指定类型（index/etf/futures/gold）
SPECIAL_TYPES = {}


# ── 工具 ──────────────────────────────────────────────────

def safe_get(url, headers=None, timeout=15, retries=3):
    """带指数退避重试的 HTTP GET"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        if i < retries - 1:
            time.sleep(2 ** i)
    raise RuntimeError(last_err)


def classify_code(code):
    """自动识别标的类型：index / etf / futures / gold"""
    code = str(code).strip().upper()
    if code in SPECIAL_TYPES:
        return SPECIAL_TYPES[code]
    if code.startswith("AU"):
        return "gold"
    if re.fullmatch(r"[A-Z]+\d+", code):
        return "futures"
    if re.fullmatch(r"\d{6}", code):
        if code.startswith(("000", "00")):
            return "index"
        if code.startswith(("5", "6")):
            return "etf"  # 沪市
        if code.startswith("1"):
            return "etf"  # 深市
        return "index"
    return "index"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ── 实时价 ────────────────────────────────────────────────

def _sina_prefix(code, cat):
    """新浪/腾讯代码前缀：指数一律沪市(sh)，ETF按沪深"""
    if cat == "index":
        return "sh"
    return "sh" if code.startswith(("5", "6")) else "sz"


def _fetch_sina(code, cat):
    if cat == "futures":
        url = f"https://hq.sinajs.cn/list=nf_{code}"
    else:
        url = f"https://hq.sinajs.cn/list=s_{_sina_prefix(code, cat)}{code}"
    r = safe_get(url, headers={"Referer": "https://finance.sina.com.cn"})
    m = re.search(r'"([^"]+)"', r.text)
    if not m:
        return None, None
    parts = m.group(1).split(",")
    if cat == "futures":
        # 新浪期货：parts[8] 最新价，回退 parts[3] 昨收
        for idx in (8, 3):
            try:
                v = float(parts[idx])
                if v > 0:
                    return v, _today()
            except (ValueError, IndexError):
                pass
        return None, None
    try:
        v = float(parts[1])
        if v > 0:
            return v, _today()
    except (ValueError, IndexError):
        pass
    return None, None


def _fetch_tencent(code, cat):
    if cat == "gold":
        url = "https://qt.gtimg.cn/q=sgeAU9999"
    else:
        url = f"https://qt.gtimg.cn/q=s_{_sina_prefix(code, cat)}{code}"
    r = safe_get(url)
    m = re.search(r'"([^"]+)"', r.text)
    if not m or "none_match" in m.group(1):
        return None, None
    parts = m.group(1).split("~")
    try:
        v = float(parts[3])
        if v > 0:
            return v, _today()
    except (ValueError, IndexError):
        pass
    return None, None


def _fetch_eastmoney(code, cat):
    if cat == "gold":
        secids = ["118.AU9999", "113.AU9999"]
    elif cat == "futures":
        secids = [f"113.{code}"]
    elif cat == "index":
        secids = [f"1.{code}"]  # 沪市指数
    else:
        prefix = "1" if code.startswith(("5", "6")) else "0"
        secids = [f"{prefix}.{code}"]
    for secid in secids:
        try:
            r = safe_get(
                f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f58,f57",
                headers={"Referer": "https://quote.eastmoney.com"})
            d = r.json().get("data")
            if not d:
                continue
            v = d.get("f43")
            if v and v > 0:
                v = v / 100 if v > 10000 else v
                return v, _today()
        except Exception:
            continue
    return None, None


def fetch_price(code):
    """获取实时价，多源 fallback，返回 (price, date)"""
    cat = classify_code(code)
    fetchers = [
        ("新浪", lambda: _fetch_sina(code, cat)),
        ("腾讯", lambda: _fetch_tencent(code, cat)),
        ("东方财富", lambda: _fetch_eastmoney(code, cat)),
    ]
    for name, fn in fetchers:
        try:
            price, date_str = fn()
            if price and price > 0:
                return price, date_str
        except Exception:
            continue
    return None, None


def fetch_prices(codes):
    """批量获取实时价：自动识别类型、去重，返回 {code: {price, date}}"""
    result = {}
    for code in dict.fromkeys(codes):
        price, date_str = fetch_price(code)
        if price and price > 0:
            result[code] = {"price": price, "date": date_str}
    return result


# ── 历史价（期初价 / 观察日收盘） ─────────────────────────

def fetch_initial_price(code, target_date):
    """获取历史收盘价，双源 fallback，返回 (price, actual_date)"""
    cat = classify_code(code)
    target = str(target_date)[:10]

    # 新浪 K线
    try:
        if cat == "futures":
            url = ("https://stock2.finance.sina.com.cn/futures/api/json_v2.php/"
                   "IndexService.getInnerFuturesDailyKLine?symbol=" + code)
        else:
            url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   "CN_MarketData.getKLineData?symbol=" + _sina_prefix(code, cat) + code +
                   "&scale=240&ma=no&datalen=60")
        data = safe_get(url, headers={"Referer": "https://finance.sina.com.cn"}).json()
        for item in reversed(data):
            day = item.get("day") or item.get("date")
            close = float(item.get("close", 0))
            if day and day <= target and close > 0:
                return close, day
    except Exception:
        pass

    # 东方财富 K线
    if cat == "gold":
        secids = ["118.AU9999", "113.AU9999"]
    elif cat == "futures":
        secids = [f"113.{code}"]
    elif cat == "index":
        secids = [f"1.{code}"]  # 沪市指数
    else:
        prefix = "1" if code.startswith(("5", "6")) else "0"
        secids = [f"{prefix}.{code}"]
    for secid in secids:
        try:
            url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
                   "secid=" + secid +
                   "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
                   "&klt=101&fqt=0&end=20500101&lmt=60")
            klines = safe_get(url, headers={"Referer": "https://quote.eastmoney.com"}).json().get("data", {}).get("klines", [])
            for line in reversed(klines):
                parts = line.split(",")
                if len(parts) >= 3:
                    day = parts[0]
                    close = float(parts[2])
                    if day <= target and close > 0:
                        return close, day
        except Exception:
            continue
    return None, None


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] or ["000852"]
    print("实时价:", fetch_prices(codes))
