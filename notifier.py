"""多渠道推送:Server酱(微信)/ PushPlus / 企业微信机器人 / 钉钉机器人 / Telegram / Bark / 邮箱。

每个渠道函数返回 (ok: bool, detail: str);send_all 会把结果汇总并写日志。
"""
import base64
import hashlib
import hmac
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from urllib.parse import quote_plus

import requests
from fetcher import http_get, http_post

log = logging.getLogger("vix")
TIMEOUT = 15

# 各渠道在配置里的开关键名
CHANNELS = ["serverchan", "pushplus", "wecom_bot", "dingtalk_bot", "telegram", "bark", "email"]


def enabled_channels(push_cfg):
    return [c for c in CHANNELS if push_cfg.get(c, {}).get("enabled")]


def send_all(push_cfg, title, md, text):
    """向所有启用渠道推送,返回 [(渠道, 是否成功, 说明)]。"""
    results = []
    for name in enabled_channels(push_cfg):
        fn = globals().get(f"_send_{name}")
        try:
            ok, detail = fn(push_cfg[name], title, md, text)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))
        log.info("推送[%s] %s %s", name, "成功" if ok else "失败", detail if not ok else "")
    return results


# ---------------------------------------------------------------- Server酱(微信公众号)
def _send_serverchan(cfg, title, md, text):
    r = http_post(f"https://sctapi.ftqq.com/{cfg['sendkey']}.send",
                      data={"title": title, "desp": md}, timeout=TIMEOUT)
    data = r.json()
    return (data.get("code") == 0, f"code={data.get('code')} {data.get('message', '')}")


# ---------------------------------------------------------------- PushPlus(微信公众号)
def _send_pushplus(cfg, title, md, text):
    r = http_post("https://www.pushplus.plus/send",
                      json={"token": cfg["token"], "title": title,
                            "content": md, "template": "markdown"}, timeout=TIMEOUT)
    data = r.json()
    return (data.get("code") == 200, f"code={data.get('code')} {data.get('msg', '')}")


# ---------------------------------------------------------------- 企业微信群机器人
def _send_wecom_bot(cfg, title, md, text):
    r = http_post(cfg["webhook"],
                      json={"msgtype": "markdown", "markdown": {"content": md[:4090]}},
                      timeout=TIMEOUT)
    data = r.json()
    return (data.get("errcode") == 0, f"errcode={data.get('errcode')} {data.get('errmsg', '')}")


# ---------------------------------------------------------------- 钉钉群机器人
def _ding_sign(secret, ts_ms):
    string_to_sign = f"{ts_ms}\n{secret}"
    code = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    return quote_plus(base64.b64encode(code))


def _send_dingtalk_bot(cfg, title, md, text):
    url = cfg["webhook"]
    if cfg.get("secret"):
        import time
        ts = str(round(time.time() * 1000))
        url += f"&timestamp={ts}&sign={_ding_sign(cfg['secret'], ts)}"
    r = http_post(url, json={"msgtype": "markdown",
                                 "markdown": {"title": title, "text": md[:18000]}},
                      timeout=TIMEOUT)
    data = r.json()
    return (data.get("errcode") == 0, f"errcode={data.get('errcode')} {data.get('errmsg', '')}")


# ---------------------------------------------------------------- Telegram
def _send_telegram(cfg, title, md, text):
    r = http_post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                      json={"chat_id": cfg["chat_id"], "text": f"{title}\n\n{text}"},
                      timeout=TIMEOUT)
    data = r.json()
    return (data.get("ok"), f"ok={data.get('ok')} {data.get('description', '')}")


# ---------------------------------------------------------------- Bark(iOS)
def _send_bark(cfg, title, md, text):
    server = (cfg.get("server") or "https://api.day.app").rstrip("/")
    r = http_post(f"{server}/{cfg['device_key']}",
                      json={"title": title, "body": text, "group": "VIX"}, timeout=TIMEOUT)
    return (r.status_code == 200, f"http {r.status_code}")


# ---------------------------------------------------------------- 邮箱(SMTP)
def _send_email(cfg, title, md, text):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = cfg["user"]
    msg["To"] = ",".join(cfg["to"])

    port = int(cfg.get("smtp_port") or 465)
    if port == 465:
        smtp = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=TIMEOUT)
    else:
        smtp = smtplib.SMTP(cfg["smtp_host"], port, timeout=TIMEOUT)
        smtp.starttls()
    try:
        smtp.login(cfg["user"], cfg["password"])
        smtp.sendmail(cfg["user"], cfg["to"], msg.as_string())
    finally:
        smtp.quit()
    return True, f"已发送给 {len(cfg['to'])} 个收件人"
