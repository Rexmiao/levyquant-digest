# LevyQuant 云端日报：公开代码与加密状态

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

准备好实际 Space 地址后，在本仓库 Variables 新增 `DIGEST_PUBLIC_BASE_URL=https://<owner>-<space>.hf.space`。确认 HF 与本仓库使用相同状态密钥和公开地址、且确认邮件工作流已部署，再将两端的 `SUBSCRIPTIONS_ENABLED` 设置为 `true`。未启用时，现有普通名单与固定内部名单的每日发送行为保持不变。

启用后，普通名单与已确认的公开订阅合并，退订的外部地址被排除，固定内部名单始终保留。公开注册只先排队确认邮件；点击邮件里的确认按钮后才加入公开订阅。确认邮件在 GitHub 上执行，另有每小时队列恢复。单次提交成功不等于实际收到邮件。

### 加密状态与异常恢复

发送状态分支只保存 **AES-GCM 密文**，状态解密密钥来自 `STATE_ENCRYPTION_KEY`，不提交进该分支。收件人、发送记录及需要持久化的状态不得以明文发布。

若密钥缺失、错误或状态完整性验证失败，投递应停止，保留原有密文供恢复，不能把解密失败当作首次运行或空白历史继续发送。不要随意删除、重建状态分支或更换密钥；换钥需要使用旧密钥解密后进行受控迁移，不能只替换 Secret。

如果执行报告投递结果不确定，先在邮箱中核对发件记录，再处理状态；不要连续重跑尝试补发。SMTP 接受不等于一定进入对方收件箱，固定 Message-ID 也不是 Gmail 的自动去重保证。

## 运行边界

- **时间**：07:00 是计划触发目标，采集、生成与投递还需要时间。GitHub 高负载时可能延迟或丢弃定时任务，整点尤其繁忙，没有准点到达保证。工作流须在默认分支；公开仓库 60 天没有仓库活动时，定时工作流可能自动停用，应检查 Actions 中的启用状态。[调度说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- **内容**：英文正文为主，保留中文原文标题，采用完整分栏，重点为宏观、美股与量化研究，综合新闻只收重大事项。当前来源主要为 Fed、BLS、SEC、arXiv 和少数公司公告；少数公司的官方新闻不能代表全市场。尚无完整实时行情、一致预期、付费新闻或完整经济日历，缺失时标明或省略，不让模型补造。
- **部署状态**：代码已发布、Secrets 已保存、模型可调用、云端 SMTP 可用和每日计划已启用是不同阶段。以仓库当前代码、运行结果及实际邮件确认完成情况，不能仅凭备用部署包存在或本机测试成功判断云端已上线。
