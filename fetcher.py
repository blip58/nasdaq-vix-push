"""行情抓取:新浪 -> 腾讯 -> Yahoo 三级容灾,输出统一的行情 dict。

统一 quote 结构:
    symbol      代码,如 ^IXIC
    name        名称(优先来自数据源)
    price       最新价
    change      涨跌额(可能为 None)
    change_pct  涨跌幅 %(可能为 None)
    high52/low52  52 周最高/最低(用于计算回撤,VIX 类可能为 None)
    time_str    行情时间(数据源自带,尽量为北京时间)
    source      来源: sina / tencent / yahoo
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import requests

log = logging.getLogger("vix")

BEIJING = timezone(timedelta(hours=8))
TIMEOUT = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def http_get(url, **kwargs):
    """GET:优先走系统代理;若系统代理挂了(如 Clash 未启动,连接 127.0.0.1 被拒)则直连重试。"""
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.ProxyError:
        log.debug("系统代理不可用,改为直连: %s", url)
        with requests.Session() as s:
            s.trust_env = False
            return s.get(url, **kwargs)


def http_post(url, **kwargs):
    """POST:同 http_get 的代理兜底逻辑。"""
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        return requests.post(url, **kwargs)
    except requests.exceptions.ProxyError:
        log.debug("系统代理不可用,改为直连: %s", url)
        with requests.Session() as s:
            s.trust_env = False
            return s.post(url, **kwargs)

# 各数据源对同一指数的代码映射
SINA_CODES = {"^IXIC": "gb_ixic", "^NDX": "gb_ndx", "^VIX": "znb_VIX", "^VXN": "znb_VXN"}
TC_CODES = {"^IXIC": "usIXIC", "^NDX": "usNDX", "^VIX": "usVIX", "^VXN": "usVXN"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _quote(symbol, name, price, source, prev_close=None, change=None,
           change_pct=None, high52=None, low52=None, time_str=""):
    """归一化行情,并尽量互相推导 涨跌额/涨跌幅/昨收。"""
    price = float(price)
    if change is None and prev_close:
        change = price - float(prev_close)
    if change_pct is None and change is not None and price - change != 0:
        change_pct = change / (price - change) * 100
    if change is None and change_pct is not None:
        change = price - price / (1 + change_pct / 100)
    return {
        "symbol": symbol, "name": name, "price": price, "source": source,
        "change": change, "change_pct": change_pct,
        "high52": _f(high52), "low52": _f(low52),
        "time_str": time_str,
    }


# ---------------------------------------------------------------- 新浪
def fetch_sina(symbols):
    codes = {SINA_CODES[s]: s for s in symbols if s in SINA_CODES}
    if not codes:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    r = http_get(url, headers={**HEADERS, "Referer": "https://finance.sina.com.cn/"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "gbk"

    out = {}
    for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', r.text):
        code, payload = m.group(1), m.group(2)
        sym = codes.get(code)
        if not sym or not payload:
            continue
        f = payload.split(",")
        try:
            if code.startswith("gb_"):
                # gb_ 格式: 0名称 1价格 2涨跌幅 3时间 4涨跌额 ... 8:52周最高 9:52周最低
                out[sym] = _quote(sym, f[0], f[1], "sina", change=_f(f[4]),
                                  change_pct=_f(f[2]), high52=_f(f[8]), low52=_f(f[9]),
                                  time_str=f[3])
            else:
                # znb_ 格式: 0名称 1价格 2涨跌额 3涨跌幅 ... 6日期 7时间
                out[sym] = _quote(sym, f[0], f[1], "sina", change=_f(f[2]),
                                  change_pct=_f(f[3]), time_str=f"{f[6]} {f[7]}")
        except (ValueError, IndexError) as e:
            log.warning("新浪 %s 解析失败: %s", sym, e)
    return out


# ---------------------------------------------------------------- 腾讯
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def fetch_tencent(symbols):
    codes = {TC_CODES[s]: s for s in symbols if s in TC_CODES}
    if not codes:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    r = http_get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "gbk"

    out = {}
    for m in re.finditer(r'v_(\w+)="([^"]*)"', r.text):
        code, payload = m.group(1), m.group(2)
        sym = codes.get(code)
        if not sym or not payload:
            continue
        f = payload.split("~")
        if len(f) < 6 or not f[3]:
            continue  # 腾讯对不存在的代码(如 usVIX)直接不返回
        try:
            # 时间字段之后依次为: 涨跌额、涨跌幅、最高、最低
            t = next((i for i, x in enumerate(f) if _TIME_RE.match(x)), None)
            out[sym] = _quote(sym, f[1], f[3], "tencent", prev_close=_f(f[4]),
                              change=_f(f[t + 1]) if t else None,
                              change_pct=_f(f[t + 2]) if t else None,
                              time_str=f[t] if t else "")
        except (ValueError, IndexError) as e:
            log.warning("腾讯 %s 解析失败: %s", sym, e)
    return out


# ---------------------------------------------------------------- Yahoo
def _curl_json(url):
    """requests 的 TLS 指纹会被 Yahoo 拦(403),退回系统 curl(Windows 自带)。"""
    import json as _json
    import subprocess

    import shutil
    exe = shutil.which("curl")
    if not exe:
        raise RuntimeError("curl 不可用")
    cmd = [exe, "-s", "-m", str(TIMEOUT), "-A", HEADERS["User-Agent"], url]
    out = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 5).stdout
    return _json.loads(out.decode("utf-8", "replace"))


def _parse_yahoo_meta(meta, sym):
    price = meta.get("regularMarketPrice")
    if price is None:
        raise ValueError("no price in meta")
    ts = meta.get("regularMarketTime")
    time_str = (datetime.fromtimestamp(ts, BEIJING).strftime("%Y-%m-%d %H:%M") if ts else "")
    return _quote(sym, meta.get("longName") or meta.get("shortName") or sym, price, "yahoo",
                  change=meta.get("regularMarketChange"),
                  change_pct=meta.get("regularMarketChangePercent"),
                  high52=meta.get("fiftyTwoWeekHigh"), low52=meta.get("fiftyTwoWeekLow"),
                  time_str=time_str)


def fetch_yahoo(symbols):
    out = {}
    for sym in symbols:
        for host in ("query1", "query2"):
            url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                   f"{quote_plus(sym)}?range=5d&interval=1d")
            try:
                r = http_get(url)
                meta = r.json()["chart"]["result"][0]["meta"]
                out[sym] = _parse_yahoo_meta(meta, sym)
                break
            except Exception as e:
                log.debug("yahoo(%s) %s 失败: %s", host, sym, e)
                # requests 失败(被 403/429 拦、或系统代理挂了)都改用系统 curl 再试本 host
                try:
                    meta = _curl_json(url)["chart"]["result"][0]["meta"]
                    out[sym] = _parse_yahoo_meta(meta, sym)
                    break
                except Exception as e2:
                    log.debug("yahoo-curl(%s) %s 失败: %s", host, sym, e2)
    return out


SOURCES = {"sina": fetch_sina, "tencent": fetch_tencent, "yahoo": fetch_yahoo}


def fetch_all(symbols, order=("sina", "tencent", "yahoo")):
    """按 source 顺序逐个补齐,先取到的标的不会被后面的源覆盖。"""
    quotes = {}
    for src in order:
        fn = SOURCES.get(src)
        todo = [s for s in symbols if s not in quotes]
        if not fn or not todo:
            continue
        try:
            got = fn(todo)
        except Exception as e:
            log.warning("数据源 %s 失败: %s", src, e)
            got = {}
        quotes.update(got)
        if len(quotes) == len(symbols):
            break
    return quotes
