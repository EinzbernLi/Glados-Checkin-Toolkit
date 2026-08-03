# GLaDOS Check-in Toolkit

[![CI](https://github.com/EinzbernLi/Glados-Checkin-Toolkit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/EinzbernLi/Glados-Checkin-Toolkit/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

基于 GitHub Actions 的 GLaDOS / Railgun 多账号自动签到工具。每份 Cookie 与目标域名显式绑定，支持积分兑换、失败重试和 PushDeer、PushPlus、Telegram 聚合通知；无需自建服务器。

- 多账号、多域名、Cookie 防串用与可选积分兑换
- 默认定时运行，也支持手动 `dry-run` 和 `live`
- Cookie 域名校验、日志脱敏与有限重试
- 独立 CI；代码 push 不会触发真实签到

> 定时任务默认在每天 UTC 04:00、10:00 运行，对应香港/北京时间 12:00、18:00。通知中的运行时间始终转换并标注为北京时间。GitHub Actions 的计划任务可能延迟，并不保证准点启动。

## 快速开始

### 1. Fork 仓库

点击 GitHub 页面右上角的 **Fork**，把项目复制到自己的账户。

### 2. 获取 Cookie

1. 登录需要签到的 GLaDOS、Railgun 或兼容服务并打开签到页面。
2. 按 **F12** 打开开发者工具，进入 **Network（网络）**。
3. 刷新页面，选择签到相关请求。
4. 在 **Request Headers（请求标头）** 中复制完整的 <code>Cookie</code> 值。

<details>
<summary>查看操作图示</summary>

![Fork 仓库](imgs/1.png)

![查找请求](imgs/2.png)

</details>

不同域名通常使用不同 Cookie。请分别复制，并确保后续保存到对应的 Secret。Cookie 属于敏感凭证，不要把真实值写入代码、Issue、日志、README 或测试。

### 3. 配置 GitHub Secret

进入自己 Fork 后的仓库：

**Settings → Secrets and variables → Actions → New repository secret**

按实际使用的服务至少添加下面一项：

| Secret | 是否必需 | 内容 |
|---|---:|---|
| <code>GLADOS_COOKIES</code> | 条件必需 | 仅用于 <code>glados.cloud</code> 的完整 Cookie；多个账号使用 <code>&amp;</code> 连接 |
| <code>RAILGUN_COOKIES</code> | 条件必需 | 仅用于 <code>railgun.info</code> 的完整 Cookie；多个账号使用 <code>&amp;</code> 连接 |
| <code>CUSTOM_DOMAIN_COOKIES</code> | 条件必需 | 其他兼容域名的 JSON 映射，格式见“自定义域名” |
| <code>GLADOS_EXCHANGE_PLAN</code> | 否 | GLaDOS 的兑换计划：<code>plan100</code>、<code>plan200</code> 或 <code>plan500</code>，默认 <code>plan500</code> |
| <code>RAILGUN_EXCHANGE_PLAN</code> | 否 | Railgun 的兑换计划；未配置时继承 GLaDOS 的计划 |

同一服务的多账号示例：

~~~text
cookie-account-1&cookie-account-2
~~~

这三个 Cookie Secret 至少配置一个。程序不会把 `GLADOS_COOKIES` 自动尝试到 Railgun，也不会把 `RAILGUN_COOKIES` 发送到 GLaDOS。

#### 积分兑换策略

兑换计划与 Cookie 目标分别绑定，不同服务可以采用不同策略。在同一个 **Repository secrets** 页面按需添加：

- `GLADOS_EXCHANGE_PLAN`：只配置 GLaDOS，默认 `plan500`。
- `RAILGUN_EXCHANGE_PLAN`：只配置 Railgun；未配置 Railgun 专属值时继承 `GLADOS_EXCHANGE_PLAN`。

两个 Secret 的值都只能是下面三种之一：

| 配置值 | 所需积分 | 兑换时长 |
|---|---:|---:|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 |

例如，GLaDOS 使用 `plan100`、Railgun 使用 `plan500` 时，分别创建上述两个 Secret 并填写对应值。程序会在签到后逐目标查询积分；只有该目标积分查询成功、达到自己的策略门槛且自己的兑换开关已启用时，才会调用兑换接口。积分不足时不会兑换。

如需完全关闭自动兑换，请进入：

**Settings → Secrets and variables → Actions → Variables → New repository variable**

为 GLaDOS 添加变量 `GLADOS_ENABLE_EXCHANGE=false`；为 Railgun 添加 `RAILGUN_ENABLE_EXCHANGE=false`。需要重新启用时，将对应变量改为 `true` 或删除：GLaDOS 默认启用，未配置 Railgun 专属值时 Railgun 继承 GLaDOS 的开关。

因此，计划和开关都能分别覆盖：只设置 `RAILGUN_EXCHANGE_PLAN` 不会改变 GLaDOS，只设置 `RAILGUN_ENABLE_EXCHANGE=false` 也只会关闭 Railgun 的兑换。为了兼容旧部署，如果两个 Railgun 专属配置都未设置，Railgun 会继续使用原有 GLaDOS 设置。

### 4. 先检查配置，再执行签到

1. 打开仓库的 **Actions** 页面并启用 workflows。
2. 选择 **GLaDOS scheduled check-in**。
3. 点击 **Run workflow**，保持默认的 <code>dry-run</code> 并运行。
4. 确认日志显示配置验证通过。
5. 再选择 <code>live</code>，手动执行一次真实签到。

<code>dry-run</code> 只验证配置并输出脱敏摘要，不会请求签到、兑换或通知服务。普通代码 push 也不会触发真实签到。

完成上述步骤后，计划任务会按默认 cron 自动执行 <code>live</code> 签到。

## 通知配置

通知完全可选。可以同时启用多个渠道；其中一个渠道失败不会阻止其他渠道继续发送，但本次任务会返回非零状态。

| Secret | 用途 |
|---|---|
| <code>PUSHDEER_SENDKEY</code> | PushDeer SendKey |
| <code>PUSHPLUS_TOKEN</code> | PushPlus token |
| <code>TG_BOT_TOKEN</code> | Telegram Bot Token |
| <code>TG_CHAT_ID</code> | Telegram Chat ID，必须与 Bot Token 同时设置 |

#### Telegram 配置步骤

1. 在 Telegram 中搜索官方 **@BotFather**，发送 `/newbot`，按提示设置机器人名称和用户名（用户名必须以 `bot` 结尾）。完成后 BotFather 会返回一串 token；将它作为 `TG_BOT_TOKEN` 保存到 GitHub Actions 的 **Repository secret**。
2. 用刚创建的机器人打开私聊并发送 `/start`。如果要推送到群组，请先把机器人加入群组并在群内发送一条消息；如果要推送到频道，请将机器人加入频道并授予发消息权限，然后在频道发布一条消息。
3. 在本地浏览器中打开下面的地址，把 `<BOT_TOKEN>` 替换成刚获得的 token（不要把完整地址发到 Issue、聊天群或日志中）：

   ```text
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```

   在返回的 JSON 中找到最近一条 `message.chat.id`、`channel_post.chat.id` 或对应的 `chat.id`，这就是 `TG_CHAT_ID`。私聊通常是正数；群组或频道可能是负数，请保留完整数值。
4. 在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中分别添加 `TG_BOT_TOKEN` 和 `TG_CHAT_ID`。两者必须同时设置；token 只放在 Secret 中，不要写入 README、代码、Issue 或 Actions 日志。

如果 `result` 为空，先向机器人发送一条新消息，再重新请求 `getUpdates`。配置完成后可手动运行一次 `dry-run` 检查配置，再运行 `live` 验证通知。

完全不配置通知时，签到仍可正常运行。

### 通知内容与聚合方式

同一次运行的所有 GLaDOS、Railgun 和自定义域名结果会先汇总，再向每个已启用的通知渠道发送：

- PushPlus：一张 HTML 卡片，包含全部签到目标。
- PushDeer：一张 Markdown 卡片，包含全部签到目标。
- Telegram：正常情况下为一条消息；只有超过平台安全长度时才按完整目标区块拆分。

只启用一个域名时，通知标题使用对应服务名或域名，例如 `GLaDOS 签到结果`、`Railgun 签到结果` 或 `check.example.com 签到结果`；同一域名配置多个账号仍使用单服务标题。只有同时启用两个及以上域名时，标题才使用“签到汇总完成”或“签到汇总异常”。正文按“签到目标 1、签到目标 2……”展示域名、签到状态、剩余天数、积分、本次新增积分、该目标实际使用的兑换计划与开关、兑换结果和错误摘要。底部运行时间统一显示为 `YYYY-MM-DD HH:MM（北京时间）`。通知内容不会包含 Cookie 或通知 token。

## 可选配置

以下项目在 **Settings → Secrets and variables → Actions → Variables** 中配置，未填写时使用默认值。

| Variable | 默认值 | 作用 |
|---|---|---|
| <code>GLADOS_ALLOW_CUSTOM_DOMAINS</code> | <code>false</code> | 是否允许自定义域名 |
| <code>GLADOS_ENABLE_EXCHANGE</code> | <code>true</code> | 是否为 GLaDOS 自动兑换积分 |
| <code>RAILGUN_ENABLE_EXCHANGE</code> | 继承 GLaDOS | 是否为 Railgun 自动兑换积分 |
| <code>GLADOS_RETRY_MAX</code> | <code>2</code> | 网络重试次数，允许 0–5 |
| <code>GLADOS_RETRY_BACKOFF</code> | <code>0.5</code> | 指数退避基数秒数，允许 0–10 |

另外两个仅用于本地运行的可选变量：

| Variable | 默认值 | 作用 |
|---|---|---|
| <code>GLADOS_CONNECT_TIMEOUT</code> | <code>5</code> | 连接超时秒数，允许 1–30 |
| <code>GLADOS_READ_TIMEOUT</code> | <code>15</code> | 读取超时秒数，允许 1–60 |

<code>GLADOS_VERBOSE</code> 为兼容旧版本保留，可作为 Repository Secret 设置为 <code>true</code> 或 <code>false</code>。

### 自定义域名限制

其他域名必须与本项目使用的 Cookie 认证和 API 路径兼容。配置步骤：

1. 在 **Repository variables** 添加 `GLADOS_ALLOW_CUSTOM_DOMAINS=true`。
2. 在 **Repository secrets** 添加 `CUSTOM_DOMAIN_COOKIES`。
3. Secret 值使用 JSON 对象，键是纯域名，值是该域名的 Cookie 列表。例如：

~~~json
{"check.example.com":["cookie-account-1","cookie-account-2"]}
~~~

可在同一个对象中添加多个域名；每个 Cookie 只会发送到它所在键对应的域名。`glados.cloud` 和 `railgun.info` 不得在这里重复配置，应使用各自的专属 Secret。

旧列表格式会继承 GLaDOS 的兑换计划和开关。需要让某个自定义域名使用独立策略时，把该域名的值改成配置对象：

~~~json
{"check.example.com":{"cookies":["cookie-account-1","cookie-account-2"],"exchange_plan":"plan200","enable_exchange":false}}
~~~

`cookies` 必须是非空列表；`exchange_plan` 可选且只能使用上表三种计划；`enable_exchange` 可选且必须是 JSON 布尔值 `true` 或 `false`（不能写成字符串）。省略的策略字段继承 GLaDOS 设置。

自定义域名不得包含协议、路径、端口、userinfo 或 IP 地址；所有请求始终使用 HTTPS。这里配置的是签到 Cookie，不是 PushPlus、Telegram 等通知服务的 token。

旧版 `GLADOS_DOMAINS` 仅保留单域兼容：它只能把旧 `GLADOS_COOKIES` 指向一个域名。多个域名无法确定每份 Cookie 的归属，程序会在网络请求前拒绝运行；新配置请勿继续使用该变量。

## 本地运行

建议使用 Python 3.12：

~~~powershell
python -m pip install -r requirements.txt
$env:GLADOS_COOKIES = "your-cookie"
python checkin.py
~~~

同时运行 Railgun：

~~~powershell
$env:GLADOS_COOKIES = "your-glados-cookie"
$env:RAILGUN_COOKIES = "your-railgun-cookie"
python checkin.py
~~~

只检查配置：

~~~powershell
$env:GLADOS_COOKIES = "fake-cookie-a&fake-cookie-b"
$env:PUSHPLUS_TOKEN = "fake-token"
python checkin.py --dry-run
~~~

退出码：

- <code>0</code>：签到与已配置通知全部成功，或账号今日已经签到。
- <code>1</code>：至少一个签到或通知任务失败。
- <code>2</code>：配置错误，尚未发起网络请求。

## 安全设计

- Cookie 只发送到与其显式绑定且经过校验的 HTTPS 签到域名。
- 通知服务不会收到 Cookie。
- 日志、异常摘要和 <code>--dry-run</code> 不输出 Cookie、token、SendKey 或 Chat ID。
- CI 不读取 Secrets，也不执行真实签到、兑换或通知。
- GitHub Actions 使用只读仓库权限，并将官方 Actions 固定到完整 commit SHA。
- 连接错误、超时、429 和部分 5xx 状态会有限重试；认证错误和普通 4xx 不重试。

## 开发与测试

~~~powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q src tests checkin.py
~~~

测试使用虚假凭证和注入的 HTTP 边界，不访问真实签到、兑换或通知服务。

项目结构：

~~~text
checkin.py                         兼容旧用法的命令行入口
src/                               配置、API、签到、通知与渲染模块
tests/                             单元测试与 workflow 约束测试
.github/workflows/ci.yml           无 Secrets 的持续集成
.github/workflows/gladosCheck.yml  定时与手动签到
~~~

## 常见问题

### 定时任务为什么没有准点运行？

GitHub 不保证 scheduled workflow 准点执行，高峰期可能延迟。先检查 Actions 是否已在 Fork 中启用，以及仓库是否长期没有活动。

### “今日已签到”算失败吗？

不算。这是正常结果，程序返回成功。

### 积分不足会尝试兑换吗？

不会。只有积分查询成功、兑换已启用并达到所选计划门槛时才调用兑换接口。

### 多个域名会收到多条通知吗？

不会按域名单独推送。一次运行的所有结果会聚合到每个通知渠道的一张卡片中；只有 Telegram 内容超过长度上限时才会拆分。

### 为什么通知时间与 Actions 日志时间不同？

Actions 日志和 cron 使用 UTC，而通知中的运行时间会转换为 `Asia/Shanghai` 并明确标注“北京时间”。

### 如何停止自动签到？

在仓库 **Actions** 页面禁用 **GLaDOS scheduled check-in** workflow，或删除自己的 Fork。删除 Secret 并不能阻止 workflow 启动，只会让配置检查失败。

## 许可证与来源

本项目按 [GNU GPL-3.0](LICENSE) 发布，源自
[Devilstore/Glados-Railgun-checkin](https://github.com/Devilstore/Glados-Railgun-checkin)，并曾由
[EinzbernLi/Glados-Railgun-checkin](https://github.com/EinzbernLi/Glados-Railgun-checkin) 维护演进。
完整来源链与第三方说明见 [NOTICE](NOTICE)。

本工具不保证第三方服务长期可用。请遵守相关服务条款，并自行承担使用自动化脚本的风险。
