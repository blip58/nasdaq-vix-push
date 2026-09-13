# 纳指 & VIX 监控推送小程序

监控纳斯达克指数与 VIX 恐慌指数,**只有当 VIX 大于阈值(默认 30)时才推送**,推送内容包含纳指距离 52 周最高点的回撤百分比。支持推送到微信(Server酱 / PushPlus / 企业微信)、钉钉、Telegram、Bark、邮箱。

## 消息效果

```
🚨 VIX 31.2 已突破 30,请注意风险
------------------------------------------
VIX 恐慌指数:31.20 🔺 +4.80(+18.20%)
触发条件:大于 30.0
市场情绪:🚨 极度恐慌

📉 纳指距离最高点回撤:
- 纳斯达克综合 25,800.10 🔻 -533.00(-2.02%),52周最高 27,190.21,回撤 -5.1%
- 纳斯达克100 28,900.00 🔻 -468.00(-1.59%),52周最高 30,762.20,回撤 -6.1%
```

**只在 VIX 大于 30 时才会收到消息**,低于 30 一律不打扰:突破 30 的那一刻立刻推一条,之后只要还在 30 以上每天最多再提醒一次(默认不早于北京时间 09:00),其余时间完全安静。

## 别人想用怎么办(3 步,不用懂技术)

1. 打开 <https://github.com/blip58/nasdaq-vix-push>,点右上角 **Use this template → Create a new repository**(用这个模板复制一份到你自己的账号)
2. 去 <https://sct.ftqq.com> 用**你自己的微信**扫码登录,复制那串 `SCT` 开头的 SendKey
3. 在你刚建的仓库里点 **Settings → Secrets and variables → Actions → New repository secret**,名字填 `SERVERCHAN_SENDKEY`,值粘贴你的 SendKey —— 完成,之后它就会自动监控并推送到你自己的微信

每个人用自己的仓库和自己的 SendKey,互不影响、额度也各算各的(都免费)。想改阈值就在 **Settings → Variables** 里加一个 `VIX_ALERT_ABOVE`(比如 `25`)。

## 快速开始

```bash
cd nasdaq-vix-push
pip install -r requirements.txt      # 只需要 requests + pyyaml

python main.py status                # 先看看能不能取到行情(不推送)
python main.py test --force --dry    # 预览告警消息长什么样(不发送)
```

## 配置推送渠道(必需,否则消息只打印在屏幕上)

```bash
copy config.example.yaml config.yaml
```

编辑 `config.yaml`,把你要用的渠道 `enabled: false` 改成 `true` 并填好 key。推荐用 **Server酱**(微信里就能收,申请地址 <https://sct.ftqq.com>):登录 → 微信扫码 → 复制 SendKey 填入。然后验证:

```bash
python main.py test        # 真实发送一条测试消息到所有已启用渠道
```

其他渠道的申请方式都写在 `config.example.yaml` 的注释里。多个渠道可同时启用。

## 让它自动跑起来

### 方式一:GitHub Actions 云端(推荐,免费,电脑不用开)

仓库里已带好 `.github/workflows/monitor.yml`:代码推到 GitHub **公开**仓库后,GitHub 的服务器每 10 分钟检查一次,VIX > 30 时把告警推到你微信,本机电脑完全不用开(公开仓库的 Actions 免费不限时长)。

1. 在 GitHub 新建一个**公开**空仓库,把本目录推上去;
2. 到 [sct.ftqq.com](https://sct.ftqq.com) 微信扫码登录,复制 SendKey;
3. 仓库页 Settings → Secrets and variables → Actions → New repository secret:Name 填 `SERVERCHAN_SENDKEY`,Secret 填 SendKey;
4. Actions 页手动 Run workflow 跑一次,微信收到消息即部署成功。

密钥只存在 GitHub Secrets,不进代码;去重状态 `state.json` 由工作流自动回写仓库,云端与本机互不干扰。其他渠道同理,对应的环境变量名见 `main.py` 里的 `ENV_SECRETS`。

### 方式二:Windows 任务计划(本机)

双击 `install_task.bat` —— 注册一个每 10 分钟运行一次的计划任务。因为只有 VIX > 30 才会真正推送,高频检查不会打扰你。卸载用 `remove_task.bat`。

### 方式三:常驻后台

双击 `start_loop.bat`,程序在一个最小化窗口里每 10 分钟检查一次(间隔可在 config.yaml 的 `monitor.check_interval_min` 改)。想让开机自动启动,把 `start_loop.bat` 的快捷方式放进启动文件夹(资源管理器地址栏输入 `shell:startup` 粘贴)。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `python main.py status` | 查看当前行情与回撤(不推送) |
| `python main.py run` | 单次检查,满足条件才推送(任务计划用的就是这个) |
| `python main.py run --dry` | 单次检查但只打印消息,不真正发送 |
| `python main.py loop` | 常驻监控 |
| `python main.py test` | 发测试消息验证渠道 |
| `python main.py test --force --dry` | 预览告警消息样式(不发送) |

## 常用配置项(改 config.yaml)

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `alert.above` | 30.0 | VIX 推送阈值,改成别的数即可,比如 25 |
| `alert.notify_recover` | false | 回落到阈值以下时是否也发一条通知(默认关) |
| `alert.repeat_daily` | true | 持续高于阈值时,每天最多再提醒一次 |
| `alert.repeat_after` | 09:00 | 每日提醒不早于该北京时间 |
| `daily_report.enabled` | false | 每天定点发一条完整行情速报(`times` 为北京时间) |
| `monitor.check_interval_min` | 10 | 检查间隔(分钟) |
| `sources` | sina→tencent→yahoo | 数据源优先级 |

## 数据源说明

按 `sources` 顺序自动容灾:**新浪 → 腾讯 → Yahoo**,先取到行情的源生效,单个标的失败会自动尝试下一个源。

- 新浪源国内直连,含 52 周最高点(回撤就是按它算的);
- VXN(纳指VIX)只有 Yahoo 提供,连不上 Yahoo 时该行显示"暂无数据",不影响 VIX 告警;
- 行情数据用于提醒仅供参考,非投资建议。

## 文件说明

```
nasdaq-vix-push/
├── main.py               主程序入口
├── fetcher.py            行情抓取(新浪/腾讯/Yahoo 容灾)
├── analyzer.py           阈值判定与消息排版
├── notifier.py           各推送渠道实现
├── config.example.yaml   配置模板(复制为 config.yaml 使用)
├── requirements.txt      依赖
├── run_once.bat          手动跑一次
├── start_loop.bat        常驻后台监控
├── install_task.bat      注册 Windows 计划任务(每 10 分钟)
├── remove_task.bat       移除计划任务
├── state.json            运行状态(去重用,自动生成)
└── push.log              运行日志(自动生成)
```

## 常见问题

- **收不到推送?** 先跑 `python main.py test` 看日志;Server酱免费版每天有额度限制;企业微信/钉钉机器人注意安全设置(钉钉建议选"加签"并填 secret)。
- **代理软件(Clash 等)时开时关?** 程序已做兜底:系统代理不可用时会自动改直连。
- **想改推送格式?** 编辑 `analyzer.py` 里的 `build_alert` / `build_report`。
- **改了阈值后收不到?** 去重状态在 `state.json`,删除该文件即可重新按新状态判断。
