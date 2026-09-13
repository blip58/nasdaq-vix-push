#!/usr/bin/env python3
"""纳指 & VIX 监控推送小程序。

默认行为:仅当 VIX 大于阈值(默认 30)时才推送,消息中包含纳指距离 52 周最高点的回撤百分比;
VIX 回落到阈值以下时发一条恢复通知。可选开启每日定时播报。

用法:
    python main.py run    [--dry]           单次检查,满足条件才推送
    python main.py loop                     常驻监控,每 N 分钟检查一次
    python main.py status                   只查看当前行情,不推送
    python main.py test   [--force] [--dry] 发测试消息验证推送渠道
                                            --force 按"告警"样式演示消息内容
"""
import argparse
import copy
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

import analyzer
import fetcher
import notifier

log = logging.getLogger("vix")

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.yaml"
STATE_FILE = BASE / "state.json"
BEIJING = timezone(timedelta(hours=8))

# 云端运行(GitHub Actions)时用环境变量注入密钥,密钥不进仓库;设了就自动启用对应渠道
ENV_SECRETS = {
    "VIX_SERVERCHAN_SENDKEY": ("push", "serverchan", "sendkey"),
    "VIX_PUSHPLUS_TOKEN": ("push", "pushplus", "token"),
    "VIX_WECOM_WEBHOOK": ("push", "wecom_bot", "webhook"),
    "VIX_DINGTALK_WEBHOOK": ("push", "dingtalk_bot", "webhook"),
    "VIX_DINGTALK_SECRET": ("push", "dingtalk_bot", "secret"),
    "VIX_TG_BOT_TOKEN": ("push", "telegram", "bot_token"),
    "VIX_TG_CHAT_ID": ("push", "telegram", "chat_id"),
    "VIX_BARK_KEY": ("push", "bark", "device_key"),
    "VIX_EMAIL_USER": ("push", "email", "user"),
    "VIX_EMAIL_PASS": ("push", "email", "password"),
}
_ENABLE_TRIGGERS = {"sendkey", "token", "webhook", "bot_token", "device_key", "password"}

DEFAULT_CONFIG = {
    # 告警:只有 VIX 大于 above 才推送
    "alert": {
        "symbol": "^VIX",      # 触发告警的标的
        "above": 30.0,         # 只有大于该值才推送
        "notify_recover": False,  # 是否在回落到阈值以下时也发一条通知(默认关闭:只有大于阈值才推送)
        "repeat_daily": True,     # 持续高于阈值时,每天最多再提醒一次(不会重复轰炸)
        "repeat_after": "09:00",  # 每日提醒不早于该北京时间(避免半夜推送)
    },
    # 每日定时播报(默认关闭,按需开启)
    "daily_report": {"enabled": False, "times": ["05:30"]},
    # 常驻监控的检查间隔(分钟)
    "monitor": {"check_interval_min": 10},
    # 监控的标的与展示名
    "symbols": [["^IXIC", "纳斯达克综合"], ["^NDX", "纳斯达克100"],
                ["^VIX", "VIX恐慌指数"], ["^VXN", "纳指VIX"]],
    # 告警消息里展示"距最高点回撤"的标的
    "drawdown_symbols": ["^IXIC", "^NDX"],
    # 数据源优先级:新浪(国内直连) -> 腾讯 -> Yahoo
    "sources": ["sina", "tencent", "yahoo"],
    "push": {
        "serverchan": {"enabled": False, "sendkey": "SCTxxxx 替换成你的 SendKey"},
        "pushplus": {"enabled": False, "token": ""},
        "wecom_bot": {"enabled": False, "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"},
        "dingtalk_bot": {"enabled": False, "webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx", "secret": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "bark": {"enabled": False, "server": "https://api.day.app", "device_key": ""},
        "email": {"enabled": False, "smtp_host": "smtp.qq.com", "smtp_port": 465,
                  "user": "", "password": "这里填授权码不是登录密码", "to": []},
    },
}


def merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_env(cfg):
    """环境变量里有密钥就覆盖配置并自动启用对应渠道(优先级高于 config.yaml)。"""
    for env, path in ENV_SECRETS.items():
        value = os.environ.get(env)
        if not value:
            continue
        d = cfg
        for key in path[:-1]:
            d = d.setdefault(key, {})
        d[path[-1]] = value
        if path[-1] in _ENABLE_TRIGGERS:
            d["enabled"] = True
    # 阈值可用环境变量/仓库变量覆盖,不改代码就能调整(如 GitHub 仓库 Variables 里的 VIX_ALERT_ABOVE)
    above = os.environ.get("VIX_ALERT_ABOVE")
    if above:
        try:
            cfg["alert"]["above"] = float(above)
        except ValueError:
            log.warning("VIX_ALERT_ABOVE 不是数字,已忽略: %s", above)
    return cfg


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = merge(DEFAULT_CONFIG, yaml.safe_load(f) or {})
    else:
        log.info("未找到 config.yaml,使用内置默认配置(仅 VIX > 30 时推送)")
        cfg = copy.deepcopy(DEFAULT_CONFIG)
    return apply_env(cfg)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def now_bj():
    return datetime.now(BEIJING)


def deliver(cfg, title, md, text, dry=False):
    channels = notifier.enabled_channels(cfg["push"])
    if dry or not channels:
        print("\n" + "=" * 46)
        print(("【模拟推送】" if dry else "【未配置推送渠道,仅打印】") + title)
        print("=" * 46)
        print(md)
        print("=" * 46 + "\n")
        if not dry and not channels:
            log.warning("没有启用任何推送渠道,请在 config.yaml 的 push 段配置(可先复制 config.example.yaml)")
        return
    results = notifier.send_all(cfg["push"], title, md, text)
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        log.warning("部分渠道推送失败: %s", ", ".join(failed))


def check_once(cfg, dry=False):
    """抓行情 -> 判断 VIX 是否大于阈值 -> 触发推送(带去重)。返回本轮是否推送。"""
    symbols = [s for s, _ in cfg["symbols"]]
    quotes = fetcher.fetch_all(symbols, tuple(cfg["sources"]))
    missing = [s for s in symbols if s not in quotes]
    if missing:
        log.warning("未取到行情: %s", ", ".join(missing))
    if not quotes:
        log.error("所有数据源均失败,本轮跳过")
        return False

    state = load_state()
    alert_state = state.setdefault("alert", {"was_above": False, "last_date": "", "count": 0})
    now = now_bj()
    today = now.strftime("%Y-%m-%d")
    pushed = False

    sym = cfg["alert"]["symbol"]
    threshold = float(cfg["alert"]["above"])
    vix = quotes.get(sym)
    if vix is None:
        # 告警标的无数据时不做任何判断,避免误报/误恢复
        log.warning("告警标的 %s 无数据,本轮不判断阈值", sym)
    else:
        above = vix["price"] > threshold
        if above:
            first_time = not alert_state.get("was_above")
            # 持续高于阈值时每天最多提醒一次,且不早于 repeat_after(默认 09:00 北京时间)
            repeat_after = str(cfg["alert"].get("repeat_after") or "00:00")
            repeat = (cfg["alert"].get("repeat_daily")
                      and alert_state.get("last_date") != today
                      and now.strftime("%H:%M") >= repeat_after)
            if first_time or repeat:
                log.info("VIX %.2f > %.0f,触发告警推送", vix["price"], threshold)
                title, md, text = analyzer.build_alert(vix, threshold, quotes, cfg, now)
                deliver(cfg, title, md, text, dry)
                alert_state["count"] = int(alert_state.get("count") or 0) + 1
                pushed = True
            else:
                log.info("VIX %.2f 持续高于 %.0f,今日已提醒过,跳过", vix["price"], threshold)
            alert_state["was_above"] = True
            alert_state["last_date"] = today
        else:
            if alert_state.get("was_above") and cfg["alert"].get("notify_recover"):
                log.info("VIX %.2f 已回落至 %.0f 以下,发送恢复通知", vix["price"], threshold)
                title, md, text = analyzer.build_recover(vix, threshold, quotes, cfg, now)
                deliver(cfg, title, md, text, dry)
                pushed = True
            alert_state["was_above"] = False

    # 可选:每日定时播报(超过当天配置时间后的第一轮检查触发,避免因睡过头漏发)
    dr = cfg["daily_report"]
    if dr.get("enabled"):
        hm = now.strftime("%H:%M")
        due = any(t <= hm for t in dr.get("times", []))
        if due and state.get("last_report_date") != today:
            title, md, text = analyzer.build_report(quotes, cfg, now)
            deliver(cfg, title, md, text, dry)
            state["last_report_date"] = today
            log.info("已发送每日行情播报")

    # 心跳:每天至少让 state.json 变化一次,云端据此提交一次,避免 GitHub 因 60 天
    # 无仓库活动而自动停掉定时任务(该值每天只变一次,不会把提交历史刷爆)
    state["last_run_date"] = today

    save_state(state)
    return pushed


# ---------------------------------------------------------------- 命令
def cmd_run(cfg, args):
    check_once(cfg, dry=args.dry)


def cmd_loop(cfg, args):
    interval = max(1, int(cfg["monitor"]["check_interval_min"]))
    log.info("常驻监控已启动:每 %d 分钟检查一次,Ctrl+C 退出", interval)
    while True:
        try:
            check_once(cfg)
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("本轮检查异常,继续下一轮")
        time.sleep(interval * 60)


def cmd_status(cfg, args):
    symbols = [s for s, _ in cfg["symbols"]]
    names = dict(cfg["symbols"])
    quotes = fetcher.fetch_all(symbols, tuple(cfg["sources"]))
    if not quotes:
        log.error("所有数据源均失败")
        return
    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            print(f"{names.get(sym, sym):<12} 暂无数据")
            continue
        dd = analyzer.drawdown(q)
        dd_txt = f"距52周最高回撤 {dd:+.1f}%" if dd is not None else ""
        print(f"{names.get(sym, sym):<12} {analyzer.fmt(q['price']):>12} "
              f"{analyzer.arrow(q['change'])} {analyzer.fmt(q['change'], sign=True)} "
              f"({analyzer.fmt(q['change_pct'], sign=True)}%)  "
              f"[{q['source']}] {dd_txt}")
    print(f"\n北京时间 {now_bj().strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_test(cfg, args):
    quotes = fetcher.fetch_all([s for s, _ in cfg["symbols"]], tuple(cfg["sources"]))
    if not quotes:
        log.error("行情抓取失败,请先运行 python main.py status 排查网络")
        return
    now = now_bj()
    vix = quotes.get(cfg["alert"]["symbol"])
    if args.force and vix:
        # 演示:按告警样式排版(内容为当前真实行情,不管是否真的超过阈值)
        title, md, text = analyzer.build_alert(vix, float(cfg["alert"]["above"]), quotes, cfg, now)
        title = "[演示] " + title
    else:
        title, md, text = analyzer.build_report(quotes, cfg, now)
    deliver(cfg, title, md, text, dry=args.dry)


def setup_logging():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    file_handler = logging.FileHandler(BASE / "push.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="纳指 & VIX 监控推送")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="单次检查并按条件推送")
    p.add_argument("--dry", action="store_true", help="只打印消息,不真正推送")
    p.set_defaults(fn=cmd_run)

    sub.add_parser("loop", help="常驻监控").set_defaults(fn=cmd_loop)

    sub.add_parser("status", help="查看当前行情(不推送)").set_defaults(fn=cmd_status)

    p = sub.add_parser("test", help="发送测试消息验证推送渠道")
    p.add_argument("--force", action="store_true", help="按告警样式演示消息")
    p.add_argument("--dry", action="store_true", help="只打印,不真正发送")
    p.set_defaults(fn=cmd_test)

    args = parser.parse_args()
    cfg = load_config()
    try:
        args.fn(cfg, args)
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
