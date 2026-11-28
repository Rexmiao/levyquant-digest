# LévyQuant 云端日报：公开代码与加密状态

[English](https://github.com/Rexmiao/levyquant-digest/blob/main/README.md) | **简体中文**

使用 GitHub 托管运行器、Gemini API 免费层和 Gmail SMTP。运行时本机可以关机。个人公开仓库为 **Rexmiao/levyquant-digest**；真实发件邮箱、收件名单、密码和状态密钥均通过 GitHub Secrets 设置，不放进公开代码。

## 1. 核对部署目标

代码通过已有 GitHub 连接部署到个人名下的 **Public** 仓库 [Rexmiao/levyquant-digest](https://github.com/Rexmiao/levyquant-digest)。部署后确认默认分支存在 `.github/workflows/daily-digest.yml`。本流程不要求重新进行 GitHub CLI 登录、创建 PAT 或授予组织访问权限。

如需要手动上传备用包，使用按公开方案重新生成并核查过的 `outputs/levyquant-cloud-deploy.zip`，将包内文件放到仓库根目录。不要上传整个本机项目、n8n 数据库、OAuth token、私人邮件、日志、本机订阅文件或明文发送记录。

**公开仓库的工作流日志、Summary、文件及提交历史可被他人查看。** Summary 只展示非敏感运行元数据，不展示全文草稿、实际邮箱、收件名单或密钥。日志中也不应打印这些内容；正文经过 HTML 转义仍然是公开内容，不能当成加密保护。[GitHub 日志访问说明](https://docs.github.com/en/rest/actions/workflow-runs)

## 2. 确认免费设置

在 [Google AI Studio Projects](https://aistudio.google.com/projects) 找到准备使用的 API key 所属项目，查看 **Billing Tier**，确认仍为 **Free**，且未启用或绑定付费结算。只使用已确认的免费项目 key，不为本日报启用付费 billing。

代码固定模型、限制调用并不切换付费备用模型，**但不能凭 API key 自动确认 Google 项目的收费状态**。必须由你在 AI Studio 核实，之后才能设置 `GEMINI_FREE_TIER_CONFIRMED=true`。免费层受模型、地区及配额限制，额度用完时允许任务停止，不自动升级。[Google 结算说明](https://aistudio.google.com/docs/billing)、[模型定价](https://aistudio.google.com/docs/pricing)

公开仓库使用标准 GitHub 托管运行器的计算用量免费；较大型运行器和其他收费项目另有规则。在 [GitHub 个人 Billing](https://github.com/settings/billing) → **Budgets and alerts** 为 Actions 设置 **$0 的额外支出预算**，并启用 **Stop usage when budget limit is reached**。仅设置提醒不会停止超额使用；仓库变量也不控制 GitHub 或 Google 的账单。[Actions 用量规则](https://docs.github.com/en/actions/concepts/billing-and-usage)、[预算设置](https://docs.github.com/en/billing/how-tos/set-up-budgets)

## 3. 填写六个 Secrets、两个 Variables

打开仓库 **Settings → Secrets and variables → Actions**。在 **Secrets** 页分别点 **New repository secret**，由你填写：

| Name | Value |
| --- | --- |
| `GEMINI_API_KEY` | 第 2 步已确认免费项目的 Gemini API key |
| `SMTP_USERNAME` | 已确认的 Gmail 发件邮箱；不要把实际地址写进公开配置 |
| `SMTP_APP_PASSWORD` | 该发件邮箱的 Google 应用专用密码 |
| `DIGEST_RECIPIENTS` | 当前普通订阅名单的 JSON 数组，或逗号分隔地址；以后替换外部名单时修改这一项 |
| `DIGEST_INTERNAL_RECIPIENTS` | 固定内部收件名单的 JSON 数组，或逗号分隔地址；始终保留，独立于普通订阅名单 |
| `STATE_ENCRYPTION_KEY` | 独立生成的 32 字节随机密钥，以 URL-safe Base64 编码 |

两份名单分别保存在对应 Secret 中，实际地址不写进公开配置。格式示例仅使用占位地址：

```json
["you@example.com","another@example.com"]
```

两项都支持这种 JSON 数组，也支持 `you@example.com,another@example.com`。正式 `send` 会合并两组，忽略大小写去重，再逐人投递；合并后的唯一地址总数最多 100。

固定内部名单是正式发送的必需配置。`DIGEST_INTERNAL_RECIPIENTS` 缺失、为空或无效时，整轮发送会在任何网络操作前停止，避免漏掉内部收件人；普通 `DIGEST_RECIPIENTS` 也必须有效且非空。以后更换外部订阅名单只修改 `DIGEST_RECIPIENTS`，保留内部 Secret，因此内部收件人不会随外部名单替换而消失。不要把实际名单复制进公开代码、Issue、日志或 Summary。

`preview`、`preview-email`、`smtp-test` 不依赖这两份订阅名单。后两种自测投递仍只发送到 `SMTP_USERNAME` 对应邮箱，不会自动把内部或外部名单带入测试。

状态密钥须与 API key、邮箱密码分开生成。可在你自己的终端运行以下命令，输出只复制到 `STATE_ENCRYPTION_KEY` 并妥善私下保存，不发到聊天或提交进仓库：

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

切到 **Variables** 页，新增：

| Name | 初始 Value |
| --- | --- |
| `DIGEST_ENABLED` | `false` |
| `GEMINI_FREE_TIER_CONFIRMED` | 仅在第 2 步已实际确认后填 `true`，否则保持 `false` |

密码和 key 只由你填写到 GitHub Secrets，不发到聊天。云端不会读取本机 n8n 中保存的密码。[GitHub Secrets 操作说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## 4. 验证预览与连接，再启用每日发送

在 **Actions → LevyQuant Daily Digest → Run workflow** 选择默认分支，设置 `run_mode`：

1. **`preview`**：生成当日草稿，不发邮件。公开 Summary 只显示非敏感结果与统计，不显示全文；不要把公开日志当作草稿阅读入口。
2. **`smtp-test`**：仅向 `SMTP_USERNAME` 对应的发件邮箱发送一封连接测试邮件。检查收件箱和垃圾邮件，确认云端 SMTP 可用；本机连接成功不能代替云端验证。
3. **可选 `preview-email`**：仅当当前部署版本的下拉菜单已提供该模式时使用。由你手动选择后，向 `SMTP_USERNAME` 对应邮箱发送当日草稿，供私下检查完整分栏、来源与语言；不向订阅名单发送。没有这个选项时，不要假定该功能已经上线，可先通过本地预览检查正文。
4. 云端检查完成后，将仓库 Variable **`DIGEST_ENABLED` 改为 `true`**。每日计划目标为 **America/New_York 当地时间 07:00**，自动跟随夏令时，按内部与普通订阅 Secret 合并后的名单逐人发送。

手动 `send` 模式会真实向内部与普通订阅合并名单发送当日稿件，同样受启用开关、密钥与发送记录检查约束。暂停日报时将 `DIGEST_ENABLED` 改回 `false`。日常无需每天手动点 Run workflow。

## Hugging Face 公开订阅入口

可部署包与配置见 `runtime/huggingface/README.md`。HF 提供公开预览、邮箱确认订阅、退订和受服务端鉴权保护的 `/admin`；Gmail SMTP 和纽约 07:00 的日程继续由 GitHub 执行。

准备好实际 Space 地址后，在本仓库 Variables 新增 `DIGEST_PUBLIC_BASE_URL=https://<owner>-<space>.hf.space`。确认 HF 与本仓库使用相同状态密钥和公开地址、且确认邮件工作流已部署，再将两端的 `SUBSCRIPTIONS_ENABLED` 设置为 `true`。这个开关控制公开注册和订阅确认邮件，已有退订及后台停用记录仍须在每日发送时过滤。

启用后，普通名单与已确认的公开订阅合并，退订的外部地址被排除，固定内部名单始终保留。公开注册只先排队确认邮件；点击邮件里的确认按钮后才加入公开订阅。确认邮件在 GitHub 上执行，另有每小时队列恢复。单次提交成功不等于实际收到邮件。

### 退订与投递看板

非固定内部收件人的正式日报保留页尾退订链接，并增加 `List-Unsubscribe` 与 `List-Unsubscribe-Post: List-Unsubscribe=One-Click` 邮件头及专用退订 POST 接口。打开网页的 GET 请求不修改订阅状态，以免邮件扫描器误触发。Gmail 等邮箱是否显示顶部退订按钮由服务商决定；当前没有实证确认 Gmail 自动生成的 DKIM 签名覆盖这两个 `List-*` 邮件头，不能因此声称已完成 RFC 8058 签名验证或保证按钮显示。

普通邮箱退订或被后台停用后，即使仍在原 `DIGEST_RECIPIENTS` 中、即使关闭公开注册开关，也会被过滤；每位收件人发送前再次核查资格。已经提交给 SMTP 的邮件无法撤回，核查与提交之间的极短竞态也不能保证撤回。固定内部名单独立保留，不附公开退订入口，不受公开退订或后台停用移除；只有所有者明确更改内部配置才能取消。

私人后台投递看板区分 `send`、`preview`、`preview-email` 和 `smtp-test`。只有正式日报展示实际收件人提交统计，包括 accepted、rejected、uncertain、reserved、pending、因退订跳过、内部数量及本轮已存在的 accepted。accepted 仅表示 SMTP 接受，不证明进入收件箱。旧日报缺少完整人数快照时，未知总数、内部数及未处理人数显示为未知，不根据已有哈希记录猜测；旧 GitHub 运行没有模式标识时也不称为已发邮件。

CLI 将最近 50 次安全运行元数据写入现有加密状态的 `reports/delivery-activity.json`，通过 CAS 合并运行记录，不包含邮箱、正文、URL、验证码或密钥。HF 私人预览不写这份 CLI 活动记录，后台结合最近 7 天真实日报状态与 GitHub 运行展示；报告写入失败不会触发重复投递。此功能复用现有凭据与 CPU Basic，无需新 Secret、权限、硬件或旧状态迁移。

### 管理员邮箱验证码登录

部署邮箱登录功能后，管理员在 `/admin` 输入已加入管理员允许名单的邮箱，再填写邮件中的 6 位验证码。验证码自请求起 10 分钟有效，只能使用一次；不要转发或分享。普通公开订阅不会授予管理员权限，管理员地址不写入公开配置或日志。允许名单由原有 `SPACE_ADMIN_TOKEN` 恢复凭据的专用管理接口维护，普通登录会话不能修改它。

验证码邮件与订阅确认邮件共用固定的 `subscription-mail.yml` 和现有 SMTP Secrets。`SUBSCRIPTIONS_ENABLED` 只控制订阅确认队列；允许名单内的管理员验证码独立处理，不需要新 Secret、额外权限或硬件。HF 不持有邮箱密码，也不通过 SMTP 直接发信。GitHub 排队可能延迟；已过期的验证码不补发，应在页面重新请求。

邮箱验证码或恢复凭据验证成功后建立 1 小时管理员会话。浏览器通过安全、仅 HTTP 可读的 Cookie 恢复登录状态，刷新页面沿用原会话的有效期。退出会撤销服务端会话并清除 Cookie。恢复凭据仅用于验证。验证码、请求和会话的持久记录复用现有加密状态；worker 在预留成功后才投递，结果不确定或进程中断时不自动重发。

请在单独的浏览器标签页中直接打开 Space 自己地址下的 `/admin`。会话 Cookie 为 `SameSite=Strict`，后台嵌在其他页面（例如 huggingface.co 的 Space 页面）中时，浏览器刷新后不会保留登录状态；此时后台会显示提示和“在新标签页打开后台”的按钮。为保持安全性，不为嵌入场景放宽 Cookie 策略。

如需在绑定到 Space 的自定义域名（例如 `https://daily.levyquant.ai`）上登录后台，请在 Space 变量中新增 `DIGEST_ADMIN_ORIGINS`，值为该地址的精确来源：以 `https://` 开头、主机名小写、不带结尾斜杠或端口；最多五个，用逗号分隔。规范地址 `DIGEST_PUBLIC_BASE_URL` 仍然受信任，任一条目格式错误时不信任任何额外来源。会话按地址分别保存，在一个地址登录不会同时登录另一个地址。邮件中的链接仍使用 `DIGEST_PUBLIC_BASE_URL`。

### 统一管理 Moomoo 检索关键词

部署含来源设置功能的版本后，在 HF 私人后台 `/admin` 修改并保存 Moomoo 关键词。设置写入现有 `delivery-state` 分支的 `settings/moomoo.json`，通过原有 `STATE_ENCRYPTION_KEY` 加密；HF 临时磁盘和浏览器存储不保存这份持久设置。GitHub 每日日报与 HF 新生成的预览读取同一份设置，`config/friend-sources.json` 仅提供首次未保存设置时的默认关键词。

保存关键词不会自动生成预览或发送邮件。已经生成并冻结的当天正式版本保持原正文及发送记录；更新用于之后的新采集与新预览，不改写或重发当天已发送版本。Moomoo 仍只提供标题、来源时间和链接，不能据此扩写未取得的正文。此配置复用现有 GitHub token 与加密状态，不需要新增 Secret、权限或硬件；HF 保持 CPU Basic。

### 加密状态与异常恢复

发送状态分支只保存 **AES-GCM 密文**，状态解密密钥来自 `STATE_ENCRYPTION_KEY`，不提交进该分支。收件人、发送记录及需要持久化的状态不得以明文发布。

若密钥缺失、错误或状态完整性验证失败，投递应停止，保留原有密文供恢复，不能把解密失败当作首次运行或空白历史继续发送。不要随意删除、重建状态分支或更换密钥；换钥需要使用旧密钥解密后进行受控迁移，不能只替换 Secret。

如果执行报告投递结果不确定，先在邮箱中核对发件记录，再处理状态；不要连续重跑尝试补发。SMTP 接受不等于一定进入对方收件箱，固定 Message-ID 也不是 Gmail 的自动去重保证。

## 运行边界

- **时间**：每天按纽约当地时间 07:00 启动主任务，07:20 和 08:10 执行备用检查。已完成的日报跳过发信。当天缺稿时，备用任务生成并发送；部分投递失败时使用当天的冻结稿，只补发可以安全重试的邮件。已接受或结果不确定的邮件不会重发。三个触发点均使用 GitHub Actions，因此同一平台的故障可能同时影响它们。工作流须在默认分支，公开仓库 60 天没有活动时定时工作流可能自动停用。[调度说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- **内容**：新双语稿在同一封邮件中先提供英文全文，再提供逐项对应的简体中文全文，采用完整分栏，重点为宏观、美股与量化研究，综合新闻只收重大事项。默认 `config/friend-sources.json` 包含21个来源：Fed、BLS、SEC、arXiv、NVIDIA 等官方来源，CNBC、WSJ、SCMP、Digitimes、雷峰网、爱范儿的公开订阅源，以及朋友邮件中的5个播客。另有 Moomoo 官方 News Search，默认检索 NVIDIA、Microsoft 与 Federal Reserve，按时间选取最多6条候选；仅保留标题、明确的来源时间和原始链接。媒体只用feed提供的标题/节选，播客只用节目介绍，不下载音频；这不是完整市场覆盖。Reuters授权内容、Finnhub日历、实时行情、一致预期及经过授权的X/雪球/微信公众号尚未接入，缺失内容省略，不让模型补造。
- **部署状态**：代码已发布、Secrets 已保存、模型可调用、云端 SMTP 可用和每日计划已启用是不同阶段。以仓库当前代码、运行结果及实际邮件确认完成情况，不能仅凭备用部署包存在或本机测试成功判断云端已上线。

## 新版邮件文案

新生成日报使用 `LévyQuant Morning Briefing — November 26, 2026` 形式的英文标题。确认信说明邮箱来自订阅页面、日报主题、约纽约时间早上7点发送，并保留48小时期限与网页二次确认。新日报页尾按公开确认订阅、原有授权名单或内部留档分别说明收到原因；普通收件人使用清楚的 `Unsubscribe from LévyQuant` 链接，固定内部名单不添加退订入口。

Coverage notice 只保留简短的范围说明、本期实际引用材料的阅读限制和实际发生的采集/截短/编辑剔除提示。上面的未接入服务清单仍是完整部署边界；精简页尾不放松任何来源、数字或日期核验。新版只用于新生成的日报及之后发送的确认信；旧冻结日报的主题、正文及已接受投递记录保持原样，不因文案升级重发。改文案不能保证进入收件箱。

## 双语邮件格式

新日报在同一封邮件中先提供英文全文，再提供完整对应的简体中文译文。两部分按相同顺序呈现条目、来源链接和已核验的数字与日期。网页语言设置独立于这个排版顺序。

翻译使用已确认免费层的现有模型，每份新稿最多尝试两次翻译。双语稿需要通过翻译校验才能发送。带明确时区的时刻按 `America/New_York` 展示日期及 EST/EDT 标识，只有日期的资料按原精度展示。

同日重试继续使用该期已经冻结的正文和投递记录。

## 公开往期简报

主页的「往期简报 / Archive」通往 `/archive`，可选择月份、在该月份全文搜索、按日期打开，并分享 `/archive?date=YYYY-MM-DD`。界面沿用中英文切换，每页列出10期，正文保留原稿语言。

新日报被邮件服务器接受后会自动收录；管理员主动公开发布的稿件也会收录。归档按日期保留首次公开版本，因此同日后来发布的修订或正式邮件可能与该版本不同。私人预览不会自动公开。公开接口仅返回未个性化的标题、日期和正文；投递记录、订阅信息和收件人专属链接继续留在加密后台状态中。

历史回填由已认证管理员调用 `POST /api/admin/archive/backfill`，每批最多31个日期，返回游标供下一批使用。它验证已有正式稿与真实接受记录，并可纳入已公开的最新一期；无需重新生成或发送邮件，也不会改写原来的冻结稿。归档快照和日期索引沿用现有加密存储与CAS，写入失败可重试补索引。当前没有自动删除归档的规则。
