"""行情分析、告警判定辅助与消息排版(告警 / 恢复 / 每日播报)。"""

# VIX 数值 -> 市场情绪(取第一个满足 v < 上限 的档位)
VIX_MOODS = [
    (13, "😴 极度平静"),
    (18, "😌 平静"),
    (24, "🤔 波动升温"),
    (30, "😰 恐慌加剧"),
    (float("inf"), "🚨 极度恐慌"),
]


def mood(v):
    for limit, text in VIX_MOODS:
        if v < limit:
            return text
    return VIX_MOODS[-1][1]


def fmt(v, nd=2, sign=False):
    if v is None:
        return "—"
    return f"{v:+.{nd}f}" if sign else f"{v:,.{nd}f}"


def arrow(v):
    if v is None:
        return ""
    return "🔺" if v > 0 else ("🔻" if v < 0 else "➖")


def drawdown(q):
    """距 52 周最高点的回撤百分比(<=0)。无 52 周高点数据时返回 None。"""
    if not q.get("high52"):
        return None
    return (q["price"] - q["high52"]) / q["high52"] * 100


def _symbol_line(q, name):
    chg, pct = q["change"], q["change_pct"]
    dd = drawdown(q)
    dd_txt = f"回撤 {dd:+.1f}%" if dd is not None else "回撤 —"
    h52 = f"52周最高 {fmt(q['high52'])}," if q.get("high52") else ""
    return (f"- **{name}** {fmt(q['price'])} {arrow(chg)} "
            f"{fmt(chg, sign=True)}({fmt(pct, sign=True)}%),{h52}{dd_txt}")


def drawdown_lines(quotes, cfg, symbols=None):
    """纳指距最高点回撤的展示行。默认取配置里的 drawdown_symbols。"""
    names = dict(cfg["symbols"])
    symbols = symbols or cfg.get("drawdown_symbols", ["^IXIC", "^NDX"])
    lines = []
    for sym in symbols:
        q = quotes.get(sym)
        if q:
            lines.append(_symbol_line(q, names.get(sym) or q["name"]))
    return lines or ["- 暂无数据"]


def build_alert(vix, threshold, quotes, cfg, now):
    """VIX 突破阈值时的告警消息。"""
    p, chg, pct = vix["price"], vix["change"], vix["change_pct"]
    title = f"🚨 VIX {p:.1f} 已突破 {threshold:g},请注意风险"
    lines = [
        f"**VIX 恐慌指数:{fmt(p)}** {arrow(chg)} {fmt(chg, sign=True)}({fmt(pct, sign=True)}%)",
        f"**触发条件:** 大于 {fmt(threshold)}",
        f"**市场情绪:** {mood(p)}",
        "",
        "**📉 纳指距离最高点回撤:**",
        *drawdown_lines(quotes, cfg),
        "",
        f"🕐 {now.strftime('%Y-%m-%d %H:%M')} 北京时间 | 数据源:{vix['source']}",
    ]
    md = "\n".join(lines)
    return title, md, plain(md)


def build_recover(vix, threshold, quotes, cfg, now):
    """VIX 回落到阈值以下时的恢复通知。"""
    p = vix["price"]
    title = f"✅ VIX {p:.1f} 已回落至 {threshold:g} 以下"
    lines = [
        f"**VIX 恐慌指数:{fmt(p)}**(阈值 {fmt(threshold)})",
        f"**市场情绪:** {mood(p)}",
        "",
        "**📉 纳指距离最高点回撤:**",
        *drawdown_lines(quotes, cfg),
        "",
        f"🕐 {now.strftime('%Y-%m-%d %H:%M')} 北京时间",
    ]
    md = "\n".join(lines)
    return title, md, plain(md)


def build_report(quotes, cfg, now):
    """全部标的的行情播报(可选的每日定时消息)。"""
    names = dict(cfg["symbols"])
    title = f"📊 纳指 & VIX 行情速报 {now.strftime('%m-%d %H:%M')}"
    lines = []
    vix_q = None
    for sym in names:
        q = quotes.get(sym)
        if not q:
            lines.append(f"- **{names[sym]}**:暂无数据")
            continue
        if sym == cfg["alert"]["symbol"]:
            vix_q = q
            lines.append(f"- **{names[sym]}** {fmt(q['price'])} {arrow(q['change'])} "
                         f"{fmt(q['change'], sign=True)}({fmt(q['change_pct'], sign=True)}%),{mood(q['price'])}")
        else:
            lines.append(_symbol_line(q, names[sym]))
    lines.append("")
    lines.append(f"🕐 {now.strftime('%Y-%m-%d %H:%M')} 北京时间")
    md = "\n".join(lines)
    return title, md, plain(md)


def plain(md):
    """去掉 markdown 粗体标记,供纯文本渠道(邮件/TG/Bark)使用。"""
    out = []
    for line in md.splitlines():
        out.append(line.replace("**", ""))
    return "\n".join(out)
