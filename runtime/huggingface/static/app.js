(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const LANGUAGE_KEY = 'levyquant.uiLanguage';
  const TEXT = {
    en: {
      msgServiceUnavailable: 'The service is temporarily unavailable. Please try again.',
      msgStaleSession: 'This administrator session has ended.',
      msgInvalidAdmin: 'The administrator credential is incorrect.',
      msgRateLimited: 'Too many requests. Please try again shortly.',
      msgTemporaryUnavailable: 'The service is temporarily unavailable. Please check the dashboard.',
      msgOperationFailed: 'The request could not be completed. Please try again.',
      flowTitleConfirm: 'Confirm your email.',
      flowTitleUnsubscribe: 'Leave the list.',
      flowDescriptionConfirm: 'One last step: confirm that you want to receive the LevyQuant morning briefing.',
      flowDescriptionUnsubscribe: 'Click below to stop receiving the briefing at this address.',
      flowButtonConfirm: 'Confirm subscription',
      flowButtonUnsubscribe: 'Unsubscribe',
      flowInvalidLink: 'This link is incomplete. Please use the link from your email.',
      flowConfirmed: 'You are subscribed. Your next briefing will arrive in the morning.',
      flowUnsubscribed: 'You have been unsubscribed.',
      flowExpired: 'This link is invalid or has expired. You can request a new confirmation on the home page.',
      flowFailed: 'We could not complete this request. Please try again shortly.',
      publicEditionFallback: 'Morning briefing',
      publicPreviewNotice: 'The published edition, with links to the original sources.',
      publicPreviewPreparing: 'The first public edition is being prepared. The actual briefing will appear here once it is published.',
      publicPreviewEmptyHeading: 'Take a look before you subscribe.',
      comingSoon: 'Coming soon',
      signupOpen: 'Get the morning briefing →',
      signupClosed: 'Subscriptions opening soon',
      signupSubmitting: 'Submitting…',
      signupCheckEmail: 'Check your inbox and Spam/Junk folder for the LevyQuant confirmation email. Open the email link and select "Confirm subscription" on the page to finish. If you are already subscribed, no action is needed.',
      signupFailed: 'We could not accept this request. Please check your address or try again later.',
      subscriberCount: '{count} confirmed',
      noSubscriptions: 'No public subscription records yet.',
      unsubscribeAction: 'Unsubscribe',
      runsUnavailable: 'Run history is temporarily unavailable. Please refresh later.',
      noRuns: 'No workflow runs to show yet.',
      runLabel: 'Run #{id}',
      adminMissing: 'Configuration needed: {names}',
      adminConnected: 'Connected. Manage subscriptions, previews and delivery tasks here.',
      subscribersUnavailable: 'Subscriber list temporarily unavailable',
      stateReadFailed: 'Subscription status could not be read. Please try again later.',
      previewReady: 'Your private preview is ready. Review it before publishing.',
      previewFailed: 'Preview generation failed. Please check the news sources and model configuration.',
      previewPending: 'The preview is still running. Please refresh later.',
      validatingAdmin: 'Verifying…',
      previewGenerating: 'Collecting and preparing the briefing. This may take a few minutes…',
      previewPublished: 'Published. Visitors can now read this preview.',
      sendQueued: 'Delivery task submitted. Refresh the run history to check the actual delivery result.',
      statePending: 'Pending confirmation', stateConfirmed: 'Confirmed', stateSeeded: 'Existing list',
      stateSuppressed: 'Stopped by owner', stateUnsubscribed: 'Unsubscribed', stateUnknown: 'Unknown',
      stateQueued: 'Queued', stateInProgress: 'In progress', stateCompleted: 'Completed',
      stateSuccess: 'Succeeded', stateFailure: 'Failed', stateCancelled: 'Cancelled',
      stateSkipped: 'Skipped', stateTimedOut: 'Timed out', stateWaiting: 'Waiting',
      stateRequested: 'Requested', stateActionRequired: 'Action required'
    },
    zh: {
      msgServiceUnavailable: '服务暂时不可用，请稍后再试。',
      msgStaleSession: '当前管理会话已结束。',
      msgInvalidAdmin: '管理员凭据不正确。',
      msgRateLimited: '操作较频繁，请稍后再试。',
      msgTemporaryUnavailable: '服务暂不可用，请查看后台状态。',
      msgOperationFailed: '操作未完成，请稍后重试。',
      flowTitleConfirm: '确认你的邮箱。',
      flowTitleUnsubscribe: '取消订阅。',
      flowDescriptionConfirm: '最后一步：确认你希望收到 LevyQuant 每日晨间简报。',
      flowDescriptionUnsubscribe: '点击下方按钮，停止向这个邮箱发送简报。',
      flowButtonConfirm: '确认订阅',
      flowButtonUnsubscribe: '取消订阅',
      flowInvalidLink: '链接不完整，请使用邮件中的确认链接。',
      flowConfirmed: '订阅成功，你将在早晨收到下一期简报。',
      flowUnsubscribed: '已取消订阅。',
      flowExpired: '链接无效或已过期，你可以回到首页重新申请确认邮件。',
      flowFailed: '暂时无法完成操作，请稍后再试。',
      publicEditionFallback: '晨间简报',
      publicPreviewNotice: '已发布的本期简报，附原始来源链接。',
      publicPreviewPreparing: '首期公开简报正在准备中，发布后将在这里展示实际内容。',
      publicPreviewEmptyHeading: '先读一篇，再决定订阅。',
      comingSoon: '即将发布',
      signupOpen: '订阅每日晨间简报 →',
      signupClosed: '订阅即将开放',
      signupSubmitting: '正在提交…',
      signupCheckEmail: '请检查收件箱及 Spam/Junk（垃圾邮件）文件夹，找到 LevyQuant 订阅确认邮件。打开邮件中的链接，并在页面点击“确认订阅”完成确认。已订阅的邮箱无需重复操作。',
      signupFailed: '暂时无法提交，请检查邮箱地址或稍后重试。',
      subscriberCount: '{count} 位已确认',
      noSubscriptions: '尚无公开订阅记录。',
      unsubscribeAction: '取消订阅',
      runsUnavailable: '运行记录暂时无法读取，请稍后刷新。',
      noRuns: '暂无可显示的运行记录。',
      runLabel: '运行 #{id}',
      adminMissing: '待配置：{names}',
      adminConnected: '后台已连接，可管理订阅、预览和发送任务。',
      subscribersUnavailable: '订阅名单暂时无法读取',
      stateReadFailed: '订阅状态读取失败，请稍后重试。',
      previewReady: '私人预览已生成，审阅后即可发布到公开页面。',
      previewFailed: '预览生成失败，请检查新闻来源和模型配置。',
      previewPending: '预览尚未完成，请稍后刷新。',
      validatingAdmin: '正在验证…',
      previewGenerating: '正在采集和整理简报，可能需要几分钟…',
      previewPublished: '已发布，访客现在可以看到这份预览。',
      sendQueued: '发送任务已提交，请稍后刷新运行记录，核实实际投递结果。',
      statePending: '待确认', stateConfirmed: '已确认', stateSeeded: '原有名单',
      stateSuppressed: '已由管理员停止', stateUnsubscribed: '已退订', stateUnknown: '未知',
      stateQueued: '排队中', stateInProgress: '运行中', stateCompleted: '已完成',
      stateSuccess: '成功', stateFailure: '失败', stateCancelled: '已取消',
      stateSkipped: '已跳过', stateTimedOut: '超时', stateWaiting: '等待中',
      stateRequested: '已申请', stateActionRequired: '需要操作'
    }
  };
  Object.assign(TEXT.en, {
  "publicDescription": "A daily briefing on macro, U.S. equities and quantitative research.",
  "publicPageTitle": "LevyQuant — The morning briefing",
  "brandHomeLabel": "LevyQuant home",
  "homeSubscribeLink": "Home & Subscribe",
  "languageSwitcher": "Interface language",
  "switchToChinese": "Switch to Chinese",
  "switchToEnglish": "Switch to English",
  "heroEyebrow": "THE MORNING BRIEFING",
  "heroTitleLine1": "Macro. Markets.",
  "heroTitleLine2": "Research that matters.",
  "heroCopy": "Macro, U.S. equities and quantitative research, brought together in one considered daily read.",
  "heroFrequency": "Every morning",
  "heroSchedule": "Around 7 AM · New York",
  "heroPrice": "Free to read",
  "latestEditionEyebrow": "THE LATEST EDITION",
  "contentLanguageNotice": "Edition language: English.",
  "contentBilingualNotice": "English edition followed by Simplified Chinese.",
  "previewPaperLabel": "LEVYQUANT / MORNING EDITION",
  "previewMacro": "Macro & policy",
  "previewEquities": "U.S. companies & sectors",
  "previewResearch": "Quantitative research",
  "publicPreviewTitle": "Latest LevyQuant briefing",
  "signupEyebrow": "A BETTER MORNING ROUTINE",
  "signupTitleLine1": "Stay informed.",
  "signupTitleLine2": "Keep your inbox useful.",
  "signupCopy": "Read the preview, then decide. We send one daily briefing, with links to the original sources.",
  "emailLabel": "Your email address",
  "emailPlaceholder": "you@example.com",
  "websiteLabel": "Website",
  "signupConfirmationNote": "By subscribing, you agree to receive the morning briefing by email. Confirm your email to join; you can unsubscribe at any time from any issue.",
  "privacyTitle": "How your email is used",
  "privacyCopy": "We use your address to send the briefing and subscription confirmation messages. Your address and the subscriber list are not displayed publicly. You can leave using the link in any issue.",
  "insideBriefingLabel": "Inside the briefing",
  "insideMacroTitle": "Macro & markets",
  "insideMacroCopy": "Policy and economic developments that matter for the trading day.",
  "insideEquitiesTitle": "U.S. equities",
  "insideEquitiesCopy": "Company disclosures, sector developments and the events worth following.",
  "insideResearchTitle": "Quant research",
  "insideResearchCopy": "New papers and methods, with a clear path back to the original research.",
  "subscriptionEyebrow": "YOUR SUBSCRIPTION",
  "backToBriefing": "Back to the briefing",
  "footerHabit": "A daily reading habit.",
  "footerContext": "Public sources. Original links. Clear context.",
  "footerAdminLogin": "Admin",
  "adminPageTitle": "LevyQuant — Private console",
  "adminNavLabel": "Private console",
  "adminLoginEyebrow": "OWNER ACCESS",
  "adminLoginTitle": "Manage your briefing.",
  "adminLoginCopy": "Enter the SPACE_ADMIN_TOKEN configured in Hugging Face Secrets. Your credential stays in this page's memory only.",
  "adminTokenLabel": "Administrator access token",
  "adminTokenPlaceholder": "Your administrator token",
  "adminLoginButton": "Open private console",
  "adminDashboardEyebrow": "THE CONTROL ROOM",
  "adminDashboardTitle": "Daily briefing",
  "adminSchedule": "Every day at 7 AM New York time. Fixed internal recipients stay on a separate list.",
  "adminLogout": "Sign out",
  "adminGenerate": "Generate private preview",
  "adminPublish": "Publish to public page",
  "adminSend": "Send this edition",
  "adminRefresh": "Refresh status",
  "adminSubscribersEyebrow": "SUBSCRIBERS",
  "adminSubscribersTitle": "Subscriber list",
  "adminSubscribersCopy": "Public subscribers must confirm their email. Fixed internal recipients remain in a separate GitHub list.",
  "adminEmailColumn": "Email",
  "adminStatusColumn": "Status",
  "adminActionColumn": "Manage",
  "adminActivityEyebrow": "DELIVERY ACTIVITY",
  "adminActivityTitle": "Delivery runs",
  "adminActivityCopy": "A queued or successful run does not prove inbox arrival. Check delivery results and actual receipt.",
  "adminDraftEyebrow": "PRIVATE DRAFT",
  "adminDraftTitle": "Preview awaiting publication",
  "adminDraftCopy": "Visitors can see this draft only after you choose Publish to public page.",
  "privatePreviewTitle": "Private LevyQuant preview",
  "adminPublicLink": "Open the public briefing"
});
  Object.assign(TEXT.zh, {
  "publicDescription": "每日汇总宏观、美股与量化研究的重点动态。",
  "publicPageTitle": "LevyQuant｜宏观、美股与量化研究",
  "brandHomeLabel": "LevyQuant 首页",
  "homeSubscribeLink": "首页与订阅",
  "languageSwitcher": "界面语言",
  "switchToChinese": "切换到中文",
  "switchToEnglish": "切换到英文",
  "heroEyebrow": "每日晨间简报",
  "heroTitleLine1": "宏观、美股与量化研究，",
  "heroTitleLine2": "每日精读。",
  "heroCopy": "每日精选宏观、美股与量化研究动态，附原始来源链接，帮助你了解重要进展。",
  "heroFrequency": "每日晨间",
  "heroSchedule": "纽约时间约早上 7 点",
  "heroPrice": "免费阅读",
  "latestEditionEyebrow": "最新一期",
  "contentLanguageNotice": "本期正文：英文。",
  "contentBilingualNotice": "本期正文先英文，后简体中文。",
  "previewPaperLabel": "LEVYQUANT / 晨间简报",
  "previewMacro": "宏观与政策",
  "previewEquities": "美股公司与行业",
  "previewResearch": "量化研究",
  "publicPreviewTitle": "最新 LevyQuant 简报",
  "signupEyebrow": "让早晨更有收获",
  "signupTitleLine1": "掌握重要动态。",
  "signupTitleLine2": "让每封邮件都有价值。",
  "signupCopy": "先阅读预览，再决定是否订阅。每天一份简报，附原始来源链接。",
  "emailLabel": "你的邮箱地址",
  "emailPlaceholder": "you@example.com",
  "websiteLabel": "网站",
  "signupConfirmationNote": "订阅即表示你同意通过邮件接收每日晨间简报。确认邮箱后完成订阅，可随时通过任一期简报中的链接退订。",
  "privacyTitle": "我们如何使用你的邮箱",
  "privacyCopy": "你的邮箱仅用于发送简报及订阅确认邮件，邮箱和订阅名单不会公开。可通过任一期简报中的链接退订。",
  "insideBriefingLabel": "简报内容",
  "insideMacroTitle": "宏观与市场",
  "insideMacroCopy": "关注政策、经济数据与影响交易日的重要变化。",
  "insideEquitiesTitle": "美股动态",
  "insideEquitiesCopy": "公司公告、行业进展与值得跟进的市场事件。",
  "insideResearchTitle": "量化研究",
  "insideResearchCopy": "精选新论文与研究方法，附原始研究链接。",
  "subscriptionEyebrow": "订阅管理",
  "backToBriefing": "返回简报首页",
  "footerHabit": "每天，读懂重要动态。",
  "footerContext": "公开来源 · 原文链接 · 清晰背景",
  "footerAdminLogin": "管理员登录",
  "adminPageTitle": "LevyQuant｜私人管理后台",
  "adminNavLabel": "私人管理后台",
  "adminLoginEyebrow": "管理员入口",
  "adminLoginTitle": "管理你的简报。",
  "adminLoginCopy": "输入你在 Hugging Face Secrets 中设置的 SPACE_ADMIN_TOKEN。凭据仅保留在当前页面内存中。",
  "adminTokenLabel": "管理员访问凭据",
  "adminTokenPlaceholder": "输入管理员访问凭据",
  "adminLoginButton": "进入管理后台",
  "adminDashboardEyebrow": "管理控制台",
  "adminDashboardTitle": "日报管理",
  "adminSchedule": "每天按纽约时间 07:00 计划运行。固定内部收件人名单单独保留。",
  "adminLogout": "退出登录",
  "adminGenerate": "生成私人预览",
  "adminPublish": "发布到公开页面",
  "adminSend": "发送本期日报",
  "adminRefresh": "刷新状态",
  "adminSubscribersEyebrow": "订阅读者",
  "adminSubscribersTitle": "订阅名单",
  "adminSubscribersCopy": "公开订阅须完成邮箱确认。固定内部收件人由 GitHub 中的独立名单保留。",
  "adminEmailColumn": "邮箱",
  "adminStatusColumn": "状态",
  "adminActionColumn": "管理",
  "adminActivityEyebrow": "投递记录",
  "adminActivityTitle": "发送任务",
  "adminActivityCopy": "任务已排队或执行成功，并不等于邮件已进入收件箱。请结合投递结果与实际收件核实。",
  "adminDraftEyebrow": "私人草稿",
  "adminDraftTitle": "待发布预览",
  "adminDraftCopy": "点击“发布到公开页面”后，访客才能看到这份草稿。",
  "privatePreviewTitle": "私人日报预览",
  "adminPublicLink": "打开公开订阅页"
});
  Object.assign(TEXT.en, {
    moomooSourcesEyebrow: 'NEWS SOURCES',
    moomooSettingsTitle: 'Moomoo search keywords',
    moomooSettingsCopy: "Choose the companies or topics to look for in Moomoo's public news search.",
    moomooApplyNotice: 'Saved keywords apply to the next website preview and new daily editions. Editions already sent stay unchanged. Saving does not send email.',
    moomooQueriesLabel: 'Search keywords',
    moomooQueriesHelp: 'One keyword or phrase per line. Use 1–4 lines, up to 200 characters each.',
    moomooQueriesPlaceholder: 'Federal Reserve\nApple\nNVIDIA',
    moomooSave: 'Save keywords',
    moomooReload: 'Reload saved keywords',
    moomooReloadNotice: 'Reloading replaces unsaved edits with the saved keywords.',
    moomooLoading: 'Loading saved keywords…',
    moomooLoaded: 'Saved keywords loaded.',
    moomooDirty: 'Unsaved changes.',
    moomooSaving: 'Saving keywords…',
    moomooSaved: 'Keywords saved. They will be used for the next preview and new editions.',
    moomooConflict: 'Another session changed these keywords. Refresh status to keep this draft and load the latest version, or reload saved keywords to replace it.',
    moomooUnavailable: 'Keywords could not be loaded or the save could not be verified. Your draft is kept. Reload saved keywords or refresh status before saving.',
    moomooInvalid: 'Enter 1–4 nonempty lines, up to 200 characters per line, without control characters.'
  });
  Object.assign(TEXT.zh, {
    moomooSourcesEyebrow: '新闻来源',
    moomooSettingsTitle: 'Moomoo 搜索关键词',
    moomooSettingsCopy: '设置要在 Moomoo 公开新闻中搜索的公司或主题。',
    moomooApplyNotice: '保存后用于下一次网页预览与每日新稿；已发送版本保持不变。保存不会发送邮件。',
    moomooQueriesLabel: '搜索关键词',
    moomooQueriesHelp: '每行一个关键词或短语，共 1–4 行，每行最多 200 个字符。',
    moomooQueriesPlaceholder: '美联储\nApple\nNVIDIA',
    moomooSave: '保存关键词',
    moomooReload: '重新加载已保存关键词',
    moomooReloadNotice: '重新加载会用已保存的关键词替换未保存草稿。',
    moomooLoading: '正在加载已保存关键词…',
    moomooLoaded: '已加载保存的关键词。',
    moomooDirty: '有尚未保存的修改。',
    moomooSaving: '正在保存关键词…',
    moomooSaved: '关键词已保存，将用于下一次预览与每日新稿。',
    moomooConflict: '另一管理会话已修改关键词。点击“刷新状态”可保留草稿并读取最新版本；或重新加载已保存关键词以替换草稿。',
    moomooUnavailable: '无法加载关键词或核验保存结果。草稿已保留，请重新加载已保存关键词或刷新状态后再保存。',
    moomooInvalid: '请输入 1–4 行非空关键词，每行最多 200 个字符，且不含控制字符。'
  });
  Object.assign(TEXT.en, {
    adminEmailLoginCopy: 'Sign in with an email verification code. This browser stays signed in for up to one hour, including after refresh, until you sign out.',
    adminLoginEmailLabel: 'Administrator email',
    adminRequestCode: 'Send verification code',
    adminRequestingCode: 'Requesting code…',
    adminLoginCodeLabel: 'Six-digit verification code',
    adminVerifyCode: 'Verify and sign in',
    adminVerifyingCode: 'Verifying code…',
    adminResendCode: 'Resend code',
    adminResendCountdown: 'Send again in {seconds}s',
    adminCodeRequested: 'If this email has administrator access, a verification code will be sent. Check your inbox and spam folder. Delivery may take about a minute.',
    adminEmailLoginUnavailable: 'Email sign-in is temporarily unavailable. Try again later or use a recovery credential.',
    adminCodeInvalid: 'The code is incorrect or has expired. Try again, or request a new code.',
    adminSessionExpired: 'Your session has expired. Request a new email code to sign in again.',
    adminSigningOut: 'Signing out…',
    adminRestoringSession: 'Checking your saved sign-in…',
    adminSessionRestoreUnavailable: 'Your saved sign-in could not be checked. Try again.',
    adminSessionRetry: 'Try again',
    adminStatusLoading: 'Loading console status…',
    adminStatusUnavailable: 'Console status is temporarily unavailable.',
    adminSubscribersLoading: 'Loading subscriptions…',
    adminSignOutUnavailable: 'Sign-out could not be confirmed. Please try signing out again before leaving this browser.',
    adminSignedOut: 'You have signed out.',
    adminRecoverySummary: 'Use a recovery credential',
    adminFramedNotice: 'This console is embedded in another page, where your browser will not keep the sign-in after a refresh. Open it in its own tab to stay signed in.',
    adminFramedOpen: 'Open the console in a new tab'
  });
  Object.assign(TEXT.zh, {
    adminEmailLoginCopy: '使用邮箱验证码登录。登录状态最长保留一小时，刷新页面无需重新验证；退出后会清除会话。',
    adminLoginEmailLabel: '管理员邮箱',
    adminRequestCode: '发送验证码',
    adminRequestingCode: '正在申请验证码…',
    adminLoginCodeLabel: '六位数字验证码',
    adminVerifyCode: '验证并登录',
    adminVerifyingCode: '正在验证…',
    adminResendCode: '重新发送验证码',
    adminResendCountdown: '{seconds} 秒后可重新发送',
    adminCodeRequested: '如果该邮箱具有管理权限，验证码将发送到邮箱。请留意收件箱及垃圾邮件，送达可能需要约一分钟。',
    adminEmailLoginUnavailable: '邮箱登录暂时不可用，请稍后重试或使用恢复凭证。',
    adminCodeInvalid: '验证码不正确或已过期，请重试或重新申请验证码。',
    adminSessionExpired: '管理会话已过期，请重新获取邮箱验证码登录。',
    adminSigningOut: '正在退出登录…',
    adminRestoringSession: '正在检查已保存的登录状态…',
    adminSessionRestoreUnavailable: '暂时无法确认登录状态，请重试。',
    adminSessionRetry: '重试',
    adminStatusLoading: '正在加载后台状态…',
    adminStatusUnavailable: '后台状态暂时无法加载。',
    adminSubscribersLoading: '正在加载订阅列表…',
    adminSignOutUnavailable: '暂时无法确认已退出。离开当前浏览器前，请再次尝试退出登录。',
    adminSignedOut: '已退出登录。',
    adminRecoverySummary: '使用恢复凭证',
    adminFramedNotice: '当前后台嵌在其他页面中，浏览器在这种情况下刷新后不会保留登录状态。请在单独的标签页中打开后台，即可保持登录。',
    adminFramedOpen: '在新标签页打开后台'
  });
  Object.assign(TEXT.en, {
    deliveryEyebrow: 'FORMAL DAILY EDITIONS', deliveryTitle: 'Last 7 days: actual delivery records',
    deliveryCopy: 'SMTP acceptance means the mail server accepted a submission, not that it reached an inbox. Previously accepted submissions are included in the accepted total.',
    deliveryInternalBadge: 'Fixed internal list',
    deliveryInternalPolicy: 'Fixed internal recipients are retained separately, including when public subscribers unsubscribe.',
    deliveryTableLabel: 'Formal daily delivery records', deliveryDate: 'Date', deliveryStatus: 'Delivery status',
    deliveryPlanned: 'Planned', deliveryAccepted: 'SMTP accepted', deliveryRejected: 'Rejected',
    deliveryUncertain: 'Uncertain', deliveryReserved: 'Reserved, unconfirmed', deliveryPending: 'Pending attempt',
    deliverySkipped: 'Skipped: unsubscribed', deliveryInternal: 'Fixed internal', deliveryAlreadyAccepted: 'Previously accepted',
    deliveryUnknownCopy: '— means unknown. Historical counts may be incomplete; workflow success is never used to invent delivery counts.',
    deliveryRunsEyebrow: 'WORKFLOW DETAILS', deliveryRunsTitle: 'Workflow runs by mode',
    deliveryRunsCopy: 'Preview, preview email and SMTP tests are separate from formal daily delivery. A successful workflow describes the process result only.',
    deliveryRunsTableLabel: 'Workflow run details', deliveryRun: 'Run', deliveryMode: 'Mode',
    deliveryWorkflowResult: 'Workflow result', deliveryBusinessResult: 'Recorded task result',
    deliveryCounts: 'Recorded counts', deliveryDiagnostic: 'Diagnostic', deliveryLoading: 'Loading delivery records…',
    deliveryUnavailable: 'Delivery records are temporarily unavailable. Refresh status to try again; other dashboard controls remain available.',
    deliveryNoEditions: 'No formal daily editions were recorded in this seven-day window.',
    deliveryNoRuns: 'No workflow runs were recorded in this report.',
    deliveryRunsUnavailable: 'Live workflow history is unavailable. Saved run records may be incomplete.',
    deliveryLegacyCounts: 'Historical counts incomplete', deliveryUnknown: 'Unknown',
    deliveryModeSend: 'Formal send', deliveryModePreview: 'Preview only',
    deliveryModePreviewEmail: 'Preview email to sender', deliveryModeSmtpTest: 'SMTP self-test',
    deliveryModeUnknown: 'Historical mode unknown', deliveryWorkflowSuccess: 'Workflow succeeded; not proof of delivery',
    deliveryWorkflowFailed: 'Workflow failed', deliveryWorkflowUnknown: 'Workflow result unknown',
    deliveryResultRunning: 'Processing', deliveryResultCompleted: 'Task processed',
    deliveryResultFailed: 'Task failed', deliveryNeedsAttention: 'Needs review',
    deliveryAllAccepted: 'SMTP acceptance recorded', deliveryPrepared: 'Prepared; submission pending',
    deliveryNoRecipients: 'No planned recipients', deliveryUncertainStatus: 'Submission outcome uncertain',
    deliveryEditionCompleted: 'Submission attempts completed', deliveryWorkflowNeutral: 'Workflow ended: neutral',
    deliveryWorkflowStale: 'Workflow result stale', deliveryWorkflowStartupFailed: 'Workflow could not start'
  });
  Object.assign(TEXT.zh, {
    deliveryEyebrow: '正式日报投递', deliveryTitle: '最近 7 天：实际投递记录',
    deliveryCopy: 'SMTP 接受表示邮件服务器已接受提交，不代表已进入收件箱。“此前已接受”已包含在接受总数内，不重复相加。',
    deliveryInternalBadge: '固定内部名单',
    deliveryInternalPolicy: '固定内部收件人独立保留，不随公开订阅者退订而移除。',
    deliveryTableLabel: '正式日报投递记录', deliveryDate: '日期', deliveryStatus: '投递状态',
    deliveryPlanned: '计划人数', deliveryAccepted: 'SMTP 接受', deliveryRejected: '明确失败',
    deliveryUncertain: '结果不确定', deliveryReserved: '预约未确认', deliveryPending: '等待尝试',
    deliverySkipped: '退订跳过', deliveryInternal: '固定内部', deliveryAlreadyAccepted: '此前已接受',
    deliveryUnknownCopy: '— 表示未知。历史计数可能不完整，不会根据工作流成功推算投递人数。',
    deliveryRunsEyebrow: '工作流明细', deliveryRunsTitle: '按运行模式查看工作流',
    deliveryRunsCopy: '仅预览、预览邮件和 SMTP 自测与正式日报投递分别列示。工作流成功只表示流程结果。',
    deliveryRunsTableLabel: '工作流运行明细', deliveryRun: '运行', deliveryMode: '模式',
    deliveryWorkflowResult: '流程结果', deliveryBusinessResult: '已记录任务结果',
    deliveryCounts: '已记录计数', deliveryDiagnostic: '诊断', deliveryLoading: '正在加载投递记录…',
    deliveryUnavailable: '投递看板暂时不可用，请刷新状态重试；其他后台功能仍可使用。',
    deliveryNoEditions: '最近七天尚无已记录的正式日报。', deliveryNoRuns: '此报表尚无工作流运行记录。',
    deliveryRunsUnavailable: '暂时无法读取实时工作流历史，以下已保存运行记录可能不完整。',
    deliveryLegacyCounts: '历史计数不完整', deliveryUnknown: '未知',
    deliveryModeSend: '正式发送', deliveryModePreview: '仅预览', deliveryModePreviewEmail: '预览邮件（仅发件人）',
    deliveryModeSmtpTest: 'SMTP 自测', deliveryModeUnknown: '历史模式未知',
    deliveryWorkflowSuccess: '流程成功（不代表送达）', deliveryWorkflowFailed: '流程失败',
    deliveryWorkflowUnknown: '流程结果未知', deliveryResultRunning: '处理中',
    deliveryResultCompleted: '任务已处理', deliveryResultFailed: '任务失败', deliveryNeedsAttention: '需要核验',
    deliveryAllAccepted: '已记录 SMTP 接受', deliveryPrepared: '已准备，等待提交',
    deliveryNoRecipients: '无计划收件人', deliveryUncertainStatus: '提交结果不确定',
    deliveryEditionCompleted: '投递尝试已结束', deliveryWorkflowNeutral: '流程结束（中性结果）',
    deliveryWorkflowStale: '流程结果已过期', deliveryWorkflowStartupFailed: '流程未能启动'
  });
  Object.assign(TEXT.en, {
    archiveLink: 'Archive', archivePageTitle: 'LevyQuant — Published editions',
    archiveDescription: 'Browse published LevyQuant briefings by month and search the full text of a selected month.',
    archiveEyebrow: 'THE PUBLIC ARCHIVE', archiveHeading: 'Published editions',
    archiveCopy: 'Browse published LevyQuant briefings by month, or search the full text of a selected month.',
    archiveVersionNote: 'Each date keeps its first published edition.',
    archiveFiltersLabel: 'Find a published edition', archiveMonthLabel: 'Month',
    archiveQueryLabel: "Search this month's full text", archiveQueryPlaceholder: 'Company, topic or keyword',
    archiveSearch: 'Search month', archiveSearchScope: 'Full-text search covers only the selected month. Leave the keyword blank to browse that month.',
    archiveDateLabel: 'Or open an exact date', archiveOpenDate: 'Open date', archiveRetry: 'Reload archive',
    archiveResultsEyebrow: 'PUBLISHED EDITIONS', archiveResultsHeading: 'Browse the archive',
    archivePagesLabel: 'Archive result pages', archivePrevious: 'Previous', archiveNext: 'Next',
    archiveReaderEyebrow: 'PUBLISHED BRIEFING', archiveShareLink: 'Link to this edition',
    archivePreviewTitle: 'Published LevyQuant briefing', archiveLoadingMonths: 'Loading published months…',
    archiveIndexUnavailable: 'The archive index is temporarily unavailable. Reload it to try again.',
    archiveEmpty: 'No published editions are available yet.', archiveNoMonths: 'No published months',
    archiveMonthsUnavailable: 'Months unavailable', archiveLoadingResults: 'Searching the selected month…',
    archiveReadyPrompt: 'Choose a month and search to browse its published editions.',
    archiveNoResults: 'No published editions match these filters in the selected month.',
    archiveResultCount: 'Showing {first}–{last} of {total} published editions · {month}',
    archiveSearchUnavailable: 'This month could not be searched. Please try again.',
    archiveQueryInvalid: 'Enter a keyword of up to 100 characters without control characters.',
    archiveMonthRequired: 'Choose a published month before searching.', archivePage: 'Page {page}',
    archiveOpening: 'Opening the published edition…', archiveEditionNotFound: 'No published edition was found for this date.',
    archiveEditionUnavailable: 'This published edition is temporarily unavailable. Please try again.',
    archiveDateInvalid: 'Choose a valid calendar date.', archiveNoExcerpt: 'Open this edition to read the full briefing.'
  });
  Object.assign(TEXT.zh, {
    archiveLink: '往期简报', archivePageTitle: 'LevyQuant｜往期简报',
    archiveDescription: '按月浏览已公开的 LevyQuant 简报，并搜索所选月份的全文。',
    archiveEyebrow: '公开简报归档', archiveHeading: '已公开的简报',
    archiveCopy: '浏览已公开的 LevyQuant 晨间简报，按月查看，也可搜索所选月份的全文。',
    archiveVersionNote: '每个日期保留首次公开版本。',
    archiveFiltersLabel: '查找已公开的简报', archiveMonthLabel: '月份',
    archiveQueryLabel: '搜索该月简报全文', archiveQueryPlaceholder: '公司、主题或关键词',
    archiveSearch: '搜索该月', archiveSearchScope: '全文搜索仅覆盖所选月份；不填关键词即可浏览该月简报。',
    archiveDateLabel: '或按准确日期打开', archiveOpenDate: '打开日期', archiveRetry: '重新加载归档',
    archiveResultsEyebrow: '已公开的简报', archiveResultsHeading: '浏览往期简报',
    archivePagesLabel: '归档结果分页', archivePrevious: '上一页', archiveNext: '下一页',
    archiveReaderEyebrow: '公开简报全文', archiveShareLink: '本期分享链接',
    archivePreviewTitle: 'LevyQuant 公开简报全文', archiveLoadingMonths: '正在加载归档月份…',
    archiveIndexUnavailable: '暂时无法读取归档月份，请重新加载后重试。',
    archiveEmpty: '目前还没有已公开的简报。', archiveNoMonths: '暂无归档月份',
    archiveMonthsUnavailable: '月份暂不可用', archiveLoadingResults: '正在搜索所选月份…',
    archiveReadyPrompt: '请选择月份并搜索，浏览该月已公开的简报。',
    archiveNoResults: '所选月份没有符合条件的已公开简报。',
    archiveResultCount: '{month} · 共 {total} 期，显示第 {first}–{last} 期',
    archiveSearchUnavailable: '暂时无法搜索该月，请稍后重试。',
    archiveQueryInvalid: '请输入不超过 100 个字符且不含控制字符的关键词。',
    archiveMonthRequired: '搜索前请先选择归档月份。', archivePage: '第 {page} 页',
    archiveOpening: '正在打开公开简报…', archiveEditionNotFound: '这个日期没有找到已公开的简报。',
    archiveEditionUnavailable: '暂时无法读取这期公开简报，请稍后重试。',
    archiveDateInvalid: '请选择有效的日历日期。', archiveNoExcerpt: '打开本期即可阅读全文。'
  });
  Object.assign(TEXT.en, {
    navLatest: 'Latest', navSubscribe: 'Subscribe',
    heroSubscribeCta: 'Get the morning briefing', heroReadCta: 'Read the latest edition',
    highlightsHeading: 'Today’s highlights', readFullEdition: 'Read the full edition',
    highlightsNoticeBilingual: 'A selection from this edition. The full briefing runs in English, followed by Simplified Chinese.',
    highlightsNoticeEnglish: 'A selection from this edition. The full briefing is in English.',
    highlightsMore: '+{count} more in the full edition',
    skipToEdition: 'Skip to the latest edition', datelineCity: 'New York',
    mastheadTagline: 'Macro · U.S. Equities · Quantitative Research', primaryNavLabel: 'Primary',
    footerNavLabel: 'Footer', factWhenLabel: 'Delivered', factLanguageLabel: 'Languages',
    factLanguageValue: 'English, then 简体中文', factPriceLabel: 'Price', leadLabel: 'Lead story'
  });
  Object.assign(TEXT.zh, {
    navLatest: '最新一期', navSubscribe: '订阅',
    heroSubscribeCta: '订阅晨间简报', heroReadCta: '阅读最新一期',
    highlightsHeading: '本期要点', readFullEdition: '阅读本期全文',
    highlightsNoticeBilingual: '节选自本期简报。完整版先英文，后简体中文。',
    highlightsNoticeEnglish: '节选自本期简报。本期正文为英文。',
    highlightsMore: '完整版另有 {count} 条',
    skipToEdition: '跳到最新一期', datelineCity: '纽约',
    mastheadTagline: '宏观 · 美股 · 量化研究', primaryNavLabel: '主导航',
    footerNavLabel: '页脚导航', factWhenLabel: '送达', factLanguageLabel: '语言',
    factLanguageValue: '先英文，后简体中文', factPriceLabel: '价格', leadLabel: '头条'
  });
  const DELIVERY_COUNT_FIELDS = [
    ['recipient_count', 'deliveryPlanned'], ['accepted', 'deliveryAccepted'], ['rejected', 'deliveryRejected'],
    ['uncertain', 'deliveryUncertain'], ['reserved', 'deliveryReserved'], ['pending', 'deliveryPending'],
    ['skipped_unsubscribed', 'deliverySkipped'], ['internal_count', 'deliveryInternal'],
    ['already_accepted', 'deliveryAlreadyAccepted']
  ];
  const DELIVERY_ERROR_TYPES = new Set(['Exception', 'RuntimeError', 'ValueError', 'TypeError',
    'ConfigurationError', 'EditorError', 'EditorValidationError', 'StateError', 'StateConflict',
    'DeliveryError', 'DeliveryUncertain', 'SourceSettingsError', 'AdminAuthError']);
  const DELIVERY_ERROR_CODES = new Set(['execution_failed', 'configuration_failed', 'source_failed',
    'editor_failed', 'editor_validation_failed', 'state_failed', 'smtp_failed', 'unknown_error']);
  const STATE_KEYS = {
    pending: 'statePending', confirmed: 'stateConfirmed', seeded: 'stateSeeded',
    suppressed: 'stateSuppressed', unsubscribed: 'stateUnsubscribed',
    queued: 'stateQueued', in_progress: 'stateInProgress', completed: 'stateCompleted',
    success: 'stateSuccess', failure: 'stateFailure', cancelled: 'stateCancelled',
    skipped: 'stateSkipped', timed_out: 'stateTimedOut', waiting: 'stateWaiting',
    requested: 'stateRequested', action_required: 'stateActionRequired'
  };
  const MOOMOO_QUERY_CONTROL_CHARS = /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u;
  let language = 'en';
  let adminToken = '';
  let adminCookieSession = false;
  let adminSessionRestoring = false;
  let adminRefreshSequence = 0;
  let adminGeneration = 0;
  let emailLoginSequence = 0;
  let emailLoginTimer = null;
  let emailLogin = emptyEmailLogin();
  let recoveryLoginBusy = false;
  let logoutBusy = false;
  let previewTimer = null;
  let moomooLoadSequence = 0;
  let deliveryLoadSequence = 0;
  let moomooSettings = emptyMoomooSettings();
  const currentMessages = new Map();
  const pendingSubscriberActions = new Set();
  const archiveState = {months: [], month: '', query: '', date: '', results: null, selected: null,
    indexLoading: true, indexError: '', searching: false, searchError: '', opening: false, openError: ''};
  let archiveIndexSequence = 0, archiveSearchSequence = 0, archiveOpenSequence = 0;
  let archiveSearchController = null, archiveOpenController = null;
  const view = {
    edition: null, signupEnabled: false, signupSubmitting: false, flow: null,
    subscribers: [], subscribersLoading: false, subscribersUnavailable: false,
    runs: [], runsUnavailable: false, adminStatus: null, adminStatusUnavailable: false,
    deliveryReport: null, deliveryReportState: 'idle'
  };
  function t(key, values = {}) {
    const value = TEXT[language][key] || TEXT.en[key] || key;
    return value.replace(/\{(\w+)\}/g, (_, name) => String(values[name] == null ? '' : values[name]));
  }
  function preferredLanguage() {
    try {
      const saved = localStorage.getItem(LANGUAGE_KEY);
      if (saved === 'en' || saved === 'zh') return saved;
    } catch { /* Language choice also works when browser storage is disabled. */ }
    return 'en';
  }
  function setLanguage(next, save = false) {
    if (!['en', 'zh'].includes(next)) return;
    language = next;
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
    for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = t(node.getAttribute('data-i18n'));
    for (const attribute of ['aria-label', 'placeholder', 'title', 'content']) {
      for (const node of document.querySelectorAll('[data-i18n-' + attribute + ']')) {
        node.setAttribute(attribute, t(node.getAttribute('data-i18n-' + attribute)));
      }
    }
    for (const button of document.querySelectorAll('[data-language]')) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-language') === language));
    }
    if (save) { try { localStorage.setItem(LANGUAGE_KEY, language); } catch { /* Optional preference only. */ } }
    renderDynamic();
    for (const [id, entry] of currentMessages) paintMessage(id, entry);
  }
  function errorFor(key, status) {
    const error = new Error(t(key));
    error.i18nKey = key;
    if (status) error.status = status;
    return error;
  }
  function hasAdminSession() {
    return adminCookieSession || !!adminToken;
  }
  async function api(path, {method = 'GET', body, admin = false, signal} = {}) {
    const sessionGeneration = adminGeneration;
    const headers = {'Accept': 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (admin && adminToken) headers.Authorization = 'Bearer ' + adminToken;
    const response = await fetch(path, {method, headers, credentials: 'same-origin', cache: 'no-store', ...(signal ? {signal} : {}), ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    if (admin && sessionGeneration !== adminGeneration) {
      const stale = errorFor('msgStaleSession');
      stale.stale = true;
      throw stale;
    }
    let data;
    try { data = await response.json(); } catch { throw errorFor('msgServiceUnavailable'); }
    if (admin && sessionGeneration !== adminGeneration) {
      const stale = errorFor('msgStaleSession');
      stale.stale = true;
      throw stale;
    }
    if (!response.ok) {
      const sessionExpired = admin && response.status === 401 && (adminCookieSession || adminToken.startsWith('lq_session_'));
      if (admin && response.status === 401) {
        clearAdminSession();
        message(sessionExpired ? 'admin-email-login-status' : 'login-status',
          sessionExpired ? 'adminSessionExpired' : 'msgInvalidAdmin', true);
      }
      throw errorFor(sessionExpired ? 'adminSessionExpired' : response.status === 401 ? 'msgInvalidAdmin' : response.status === 429 ? 'msgRateLimited' :
        response.status === 503 ? 'msgTemporaryUnavailable' : 'msgOperationFailed', response.status);
    }
    return data;
  }
  function paintMessage(id, entry) {
    const node = $(id);
    if (!node) return;
    node.textContent = entry.key ? t(entry.key, entry.values) : '';
    node.classList.toggle('error', entry.error);
    node.classList.toggle('success', !entry.error && !!entry.key);
  }
  function message(id, key, error = false, values = {}) {
    const entry = {key, error, values};
    currentMessages.set(id, entry);
    paintMessage(id, entry);
  }
  function showError(id, error) {
    message(id, error.i18nKey || 'msgOperationFailed', true);
  }
  function renderPublicState() {
    if (!$('signup-button')) return;
    const edition = view.edition;
    const highlights = edition?.html ? editionHighlights(edition.html, language) : null;
    const useHighlights = Boolean(highlights?.shown);
    $('edition-heading').textContent = t(useHighlights ? 'highlightsHeading' : edition ? 'publicEditionFallback' : 'publicPreviewEmptyHeading');
    $('edition-date').textContent = edition ? (validArchiveDate(edition.date) ? archiveDateLabel(edition.date) : edition.date || '') : t('comingSoon');
    $('edition-notice').textContent = t(useHighlights ? (highlights.bilingual ? 'highlightsNoticeBilingual' : 'highlightsNoticeEnglish')
      : edition ? 'publicPreviewNotice' : 'publicPreviewPreparing');
    const languageNote = document.querySelector('#preview .content-language-note');
    if (languageNote) languageNote.hidden = useHighlights;
    if (useHighlights) renderHighlights(highlights);
    $('edition-highlights').hidden = !useHighlights;
    const fullLink = $('edition-full-link');
    fullLink.hidden = !edition || !validArchiveDate(edition.date);
    if (!fullLink.hidden) fullLink.href = '/archive?date=' + encodeURIComponent(edition.date);
    $('signup-button').disabled = !view.signupEnabled || view.signupSubmitting;
    $('signup-button').textContent = t(view.signupSubmitting ? 'signupSubmitting' : view.signupEnabled ? 'signupOpen' : 'signupClosed');
  }
  function renderFlow() {
    const flow = view.flow;
    if (!flow) return;
    $('flow-title').textContent = t(flow.unsubscribe ? 'flowTitleUnsubscribe' : 'flowTitleConfirm');
    $('flow-description').textContent = t(flow.unsubscribe ? 'flowDescriptionUnsubscribe' : 'flowDescriptionConfirm');
    $('flow-button').textContent = t(flow.unsubscribe ? 'flowButtonUnsubscribe' : 'flowButtonConfirm');
    $('flow-button').disabled = !flow.id || !flow.token || flow.busy || flow.completed;
  }
  function renderDateline() {
    const node = $('masthead-date');
    if (!node) return;
    const now = new Date();
    node.dateTime = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(now);
    node.textContent = new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en-US',
      matchMedia('(max-width: 640px)').matches
        ? {weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'America/New_York'}
        : {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'America/New_York'}).format(now);
  }
  function renderDynamic() {
    renderDateline();
    if (document.body.dataset.page === 'archive') {
      renderArchive();
    } else if (document.body.dataset.page === 'admin') {
      if (view.adminStatus) renderAdminStatus();
      renderSubscribers();
      renderDeliveryReport();
      renderMoomooSettings();
      renderEmailLogin();
    } else {
      renderPublicState();
      renderFlow();
    }
  }
  const HIGHLIGHT_LIMIT = 7, HIGHLIGHT_PER_SECTION = 3;
  const highlightCache = new Map();
  function safeSourceUrl(value) {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch { return ''; }
  }
  function editionHighlights(html, lang) {
    const cacheKey = lang + '\u0000' + html;
    if (highlightCache.has(cacheKey)) return highlightCache.get(cacheKey);
    // DOMParser documents are inert: scripts do not run and nothing is fetched.
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const chinese = parsed.querySelector('[data-digest-language="zh-CN"]');
    const root = (lang === 'zh' && chinese) || parsed.querySelector('[data-digest-language="en"]') || parsed.body;
    const sections = [];
    let total = 0, shown = 0;
    for (const heading of root.querySelectorAll('h2')) {
      const cell = heading.closest('tr')?.nextElementSibling?.querySelector(':scope > td');
      if (!cell) continue;
      const items = [];
      for (const block of cell.querySelectorAll(':scope > div')) {
        const paragraphs = Array.from(block.querySelectorAll(':scope > p'));
        const title = paragraphs.find(p => /font-weight:\s*bold/i.test(p.getAttribute('style') || ''));
        if (!title || !title.textContent.trim()) continue;
        total += 1;
        if (items.length >= HIGHLIGHT_PER_SECTION || shown >= HIGHLIGHT_LIMIT) continue;
        const summary = paragraphs.find(p => p !== title && !p.querySelector('strong, a') &&
          !/font-size:\s*12px/i.test(p.getAttribute('style') || ''));
        const anchor = Array.from(block.querySelectorAll('a[href]')).find(a => safeSourceUrl(a.getAttribute('href')));
        const after = anchor?.nextSibling?.nodeType === Node.TEXT_NODE ? anchor.nextSibling.textContent : '';
        const time = (after.match(/^\s*·\s*([^\n·]+)/) || [])[1] || '';
        items.push({title: title.textContent.trim(), summary: summary?.textContent.trim() || '',
          source: anchor ? {name: anchor.textContent.trim(), url: safeSourceUrl(anchor.getAttribute('href')), time: time.trim()} : null});
        shown += 1;
      }
      if (items.length) sections.push({title: heading.textContent.trim(), items});
    }
    const result = {bilingual: Boolean(chinese), contentLang: chinese && root === chinese ? 'zh-CN' : 'en', sections, total, shown};
    highlightCache.clear();
    highlightCache.set(cacheKey, result);
    return result;
  }
  function highlightStory(item, tag, className) {
    const story = document.createElement(tag); story.className = className;
    const title = document.createElement(tag === 'article' ? 'h3' : 'p'); title.className = 'highlight-title'; title.textContent = item.title;
    story.append(title);
    if (item.summary) {
      const summary = document.createElement('p'); summary.className = 'highlight-summary'; summary.textContent = item.summary;
      story.append(summary);
    }
    if (item.source) {
      const source = document.createElement('p'); source.className = 'highlight-source';
      const link = document.createElement('a'); link.href = item.source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = item.source.name || item.source.url;
      source.append(link);
      if (item.source.time) {
        const time = document.createElement('span'); time.className = 'highlight-time'; time.textContent = item.source.time;
        source.append(time);
      }
      story.append(source);
    }
    return story;
  }
  function renderHighlights(highlights) {
    const container = $('edition-highlights');
    const nodes = [];
    const [first, ...others] = highlights.sections;
    // The first item of the first section leads, front-page style.
    const lead = highlightStory(first.items[0], 'article', 'lead-story');
    const kicker = document.createElement('p'); kicker.className = 'lead-kicker';
    const label = document.createElement('span'); label.textContent = t('leadLabel');
    kicker.append(label, ' · ' + first.title);
    lead.prepend(kicker);
    nodes.push(lead);
    const columns = document.createElement('div'); columns.className = 'front-columns';
    for (const section of [{...first, items: first.items.slice(1)}, ...others]) {
      if (!section.items.length) continue;
      const block = document.createElement('section'); block.className = 'highlight-section';
      const heading = document.createElement('h3'); heading.className = 'highlight-section-title'; heading.textContent = section.title;
      const list = document.createElement('ol'); list.className = 'highlight-list';
      for (const item of section.items) list.append(highlightStory(item, 'li', 'highlight-item'));
      block.append(heading, list); columns.append(block);
    }
    if (columns.children.length) nodes.push(columns);
    if (highlights.total > highlights.shown) {
      const more = document.createElement('p'); more.className = 'highlight-more'; more.lang = document.documentElement.lang;
      more.textContent = t('highlightsMore', {count: highlights.total - highlights.shown});
      nodes.push(more);
    }
    container.lang = highlights.contentLang;
    container.replaceChildren(...nodes);
  }
  function fitFrame(frame) {
    try {
      const doc = frame.contentDocument;
      if (!doc?.documentElement || frame.hidden) return;
      frame.style.height = '0px';
      const borders = frame.offsetHeight - frame.clientHeight;
      frame.style.height = Math.ceil(doc.documentElement.scrollHeight + borders) + 'px';
      frame.classList.add('fitted');
    } catch { /* A frame that cannot be measured keeps its stylesheet height. */ }
  }
  let fitTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(() => document.querySelectorAll('iframe.digest-frame.fitted').forEach(fitFrame), 150);
  });
  function showPreview(frameId, preview) {
    const frame = $(frameId);
    frame.onload = () => fitFrame(frame);
    if (typeof preview?.html !== 'string' || !preview.html) return false;
    const parsed = new DOMParser().parseFromString(preview.html, 'text/html');
    const hasChinese = Boolean(parsed.querySelector('[data-digest-language="zh-CN"]'));
    const languageNote = frame.parentElement?.querySelector('.content-language-note');
    if (languageNote) {
      const label = hasChinese ? 'contentBilingualNotice' : 'contentLanguageNotice';
      languageNote.setAttribute('data-i18n', label);
      languageNote.textContent = t(label);
    }
    let coverage = hasChinese ? null : parsed.querySelector('[data-digest-block="coverage"]')?.closest('tr');
    if (!hasChinese && !coverage) {
      const heading = Array.from(parsed.querySelectorAll('td > strong')).find(node =>
        ['Coverage notice', '资料覆盖提醒'].includes(node.textContent.trim()));
      coverage = heading?.closest('tr');
    }
    const parent = coverage?.parentElement;
    if (parent?.tagName === 'TBODY') {
      const footer = Array.from(parent.children).find(row => row.tagName === 'TR' &&
        (row.matches('[data-digest-block="footer"]') || Array.from(row.children).some(cell =>
          cell.tagName === 'TD' && (cell.matches('[data-digest-block="footer"]') ||
            cell.textContent.trim().startsWith('LevyQuant Daily ·')))));
      if (footer && footer !== coverage && footer.parentElement === parent) {
        if (coverage.nextElementSibling !== footer) parent.insertBefore(coverage, footer);
        for (const node of [coverage, ...Array.from(coverage.children).filter(cell => cell.tagName === 'TD')]) {
          node.style.fontSize = '11px';
          node.style.color = '#70757a';
          node.style.backgroundColor = 'transparent';
          node.style.borderLeft = '0';
        }
      }
    }
    frame.srcdoc = '<!doctype html>\n' + parsed.documentElement.outerHTML;
    frame.hidden = false;
    return true;
  }
  function validArchiveMonth(value) {
    return typeof value === 'string' && /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(value) && !value.startsWith('0000');
  }
  function validArchiveDate(value) {
    if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000')) return false;
    try { return new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value; } catch { return false; }
  }
  function archiveMonths(values) {
    if (!Array.isArray(values) || values.some(value => !validArchiveMonth(value))) throw errorFor('archiveIndexUnavailable');
    return [...new Set(values)].sort().reverse();
  }
  function archiveMonthLabel(value) {
    return new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en-US',
      {year: 'numeric', month: 'long', timeZone: 'UTC'}).format(new Date(value + '-01T00:00:00Z'));
  }
  function archiveDateLabel(value) {
    return new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en-US',
      {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(new Date(value + 'T00:00:00Z'));
  }
  function renderArchive() {
    if (!$('archive-month')) return;
    const state = archiveState;
    const month = $('archive-month'); month.replaceChildren();
    for (const value of state.months) {
      const option = document.createElement('option'); option.value = value; option.textContent = archiveMonthLabel(value); month.append(option);
    }
    if (!state.months.length) {
      const option = document.createElement('option'); option.value = '';
      option.textContent = t(state.indexLoading ? 'archiveLoadingMonths' : state.indexError ? 'archiveMonthsUnavailable' : 'archiveNoMonths');
      month.append(option);
    }
    month.value = state.month; month.disabled = state.indexLoading || !state.months.length;
    if ($('archive-query').value !== state.query) $('archive-query').value = state.query;
    if ($('archive-date').value !== state.date) $('archive-date').value = state.date;
    $('archive-search-button').disabled = state.indexLoading || state.searching || !state.month;
    $('archive-date-button').disabled = state.opening || !validArchiveDate(state.date);
    $('archive-retry').hidden = !state.indexError || state.indexLoading;
    message('archive-index-status', state.indexLoading ? 'archiveLoadingMonths' : state.indexError || (!state.months.length ? 'archiveEmpty' : ''), !!state.indexError);
    const results = state.results, list = $('archive-results-list'); list.replaceChildren();
    list.setAttribute('aria-busy', String(state.searching));
    if (results) {
      for (const item of results.items) {
        const row = document.createElement('li'); row.className = 'archive-item';
        const link = document.createElement('a'); link.className = 'archive-result-link';
        link.href = '/archive?date=' + encodeURIComponent(item.date);
        if (state.selected?.date === item.date) link.setAttribute('aria-current', 'date');
        const date = document.createElement('time'); date.className = 'archive-result-date'; date.dateTime = item.date; date.textContent = archiveDateLabel(item.date);
        const subject = document.createElement('span'); subject.className = 'archive-subject'; subject.textContent = item.subject;
        link.append(date, subject);
        link.addEventListener('click', event => {
          if (event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); openArchiveEdition(item.date);
        });
        const excerpt = document.createElement('p'); excerpt.className = 'archive-excerpt'; excerpt.textContent = item.excerpt || t('archiveNoExcerpt');
        row.append(link, excerpt); list.append(row);
      }
    }
    const count = results?.items.length || 0;
    const values = results ? {first: count ? (results.page - 1) * 10 + 1 : 0,
      last: count ? (results.page - 1) * 10 + count : 0, total: results.total, month: archiveMonthLabel(results.month)} : {};
    message('archive-results-status', state.searching ? 'archiveLoadingResults' : state.searchError ||
      (results ? count ? 'archiveResultCount' : 'archiveNoResults' : state.indexLoading || !state.months.length ? '' : 'archiveReadyPrompt'), !!state.searchError, values);
    $('archive-prev').disabled = state.searching || !results || results.page <= 1;
    $('archive-next').disabled = state.searching || !results || !results.has_more;
    $('archive-page').textContent = results ? t('archivePage', {page: results.page}) : '';
    $('archive-reader-panel').hidden = !state.selected && !state.opening;
    $('archive-reader-heading').textContent = state.selected?.subject || (state.opening ? t('archiveOpening') : '');
    $('archive-reader-date').textContent = state.selected ? archiveDateLabel(state.selected.date) : '';
    $('archive-share-link').hidden = !state.selected;
    if (state.selected) $('archive-share-link').href = '/archive?date=' + encodeURIComponent(state.selected.date);
    message('archive-open-status', state.opening ? 'archiveOpening' : state.openError, !!state.openError);
  }
  function archiveFiltersChanged() {
    archiveSearchSequence += 1;
    archiveSearchController?.abort(); archiveSearchController = null;
    archiveState.searching = false; archiveState.searchError = ''; archiveState.results = null;
    renderArchive();
  }
  function archiveSearchResult(data, requestedMonth, query, page) {
    const months = archiveMonths(data.months), month = requestedMonth || months[0] || '';
    if (data.month !== month || data.page !== page || data.page_size !== 10 || !Number.isSafeInteger(data.total) || data.total < 0 ||
        typeof data.has_more !== 'boolean' || !Array.isArray(data.items) || data.items.length > 10 || data.items.some(item =>
          !item || !validArchiveDate(item.date) || item.date.slice(0, 7) !== month || typeof item.subject !== 'string' || typeof item.excerpt !== 'string') ||
        (!month && (data.total !== 0 || data.items.length || data.has_more))) throw errorFor('archiveSearchUnavailable');
    return {months, month, query, page, total: data.total, has_more: data.has_more, items: data.items.map(item =>
      ({date: item.date, subject: item.subject, excerpt: item.excerpt}))};
  }
  async function loadArchiveIndex(preferredDate = '') {
    const sequence = ++archiveIndexSequence;
    const searchSequence = ++archiveSearchSequence, query = archiveState.query.trim();
    archiveSearchController?.abort(); archiveSearchController = null;
    let month = validArchiveDate(preferredDate) ? preferredDate.slice(0, 7) : archiveState.month;
    archiveState.indexLoading = true; archiveState.indexError = ''; archiveState.searching = true;
    archiveState.searchError = ''; archiveState.results = null; renderArchive();
    try {
      let data = await api('/api/archive/search', {method: 'POST', body: {month, query, page: 1}});
      if (sequence !== archiveIndexSequence) return;
      let result = archiveSearchResult(data, month, query, 1);
      if (month && !result.months.includes(month)) {
        month = result.months[0] || '';
        if (month) {
          data = await api('/api/archive/search', {method: 'POST', body: {month, query, page: 1}});
          if (sequence !== archiveIndexSequence) return;
          result = archiveSearchResult(data, month, query, 1);
          if (!result.months.includes(month)) throw errorFor('archiveSearchUnavailable');
        } else if (result.total || result.items.length || result.has_more) throw errorFor('archiveSearchUnavailable');
      }
      archiveState.months = result.months; archiveState.month = month || result.months[0] || '';
      archiveState.results = archiveState.month && searchSequence === archiveSearchSequence ? result : null;
    } catch (error) {
      if (sequence !== archiveIndexSequence) return;
      archiveState.indexError = error.status === 429 ? 'msgRateLimited' : 'archiveIndexUnavailable';
    } finally {
      if (sequence === archiveIndexSequence) {
        archiveState.indexLoading = false;
        if (searchSequence === archiveSearchSequence) archiveState.searching = false;
        renderArchive();
      }
    }
  }
  async function searchArchive(page = 1) {
    if (archiveState.indexLoading) return;
    const month = archiveState.month, query = archiveState.query.trim();
    if (!validArchiveMonth(month)) { archiveState.searchError = 'archiveMonthRequired'; renderArchive(); return; }
    if (query.length > 100 || /[\x00-\x1f\x7f]/.test(query)) { archiveState.searchError = 'archiveQueryInvalid'; renderArchive(); return; }
    const sequence = ++archiveSearchSequence;
    archiveSearchController?.abort(); archiveSearchController = new AbortController();
    archiveState.query = query; archiveState.searching = true; archiveState.searchError = ''; archiveState.results = null; renderArchive();
    try {
      const data = await api('/api/archive/search', {method: 'POST', signal: archiveSearchController.signal, body: {month, query, page}});
      if (sequence !== archiveSearchSequence) return;
      archiveState.results = archiveSearchResult(data, month, query, page);
    } catch (error) {
      if (sequence !== archiveSearchSequence || error.name === 'AbortError') return;
      archiveState.searchError = error.status === 429 ? 'msgRateLimited' : 'archiveSearchUnavailable';
    } finally {
      if (sequence === archiveSearchSequence) { archiveState.searching = false; renderArchive(); }
    }
  }
  async function openArchiveEdition(date, scroll = true) {
    if (!validArchiveDate(date)) { archiveState.openError = 'archiveDateInvalid'; renderArchive(); return; }
    const sequence = ++archiveOpenSequence;
    archiveOpenController?.abort(); archiveOpenController = new AbortController();
    archiveState.date = date; archiveState.opening = true; archiveState.openError = ''; archiveState.selected = null;
    $('archive-preview').srcdoc = ''; $('archive-preview').hidden = true; renderArchive();
    try {
      const data = await api('/api/archive/edition', {method: 'POST', signal: archiveOpenController.signal, body: {date}});
      if (sequence !== archiveOpenSequence) return;
      const edition = data.edition;
      if (!edition || edition.date !== date || typeof edition.subject !== 'string' || typeof edition.text !== 'string' ||
          typeof edition.html !== 'string' || !showPreview('archive-preview', edition)) throw errorFor('archiveEditionUnavailable');
      archiveState.selected = {date, subject: edition.subject};
      history.replaceState(null, '', '/archive?date=' + encodeURIComponent(date));
      renderArchive();
      if (scroll) {
        $('archive-reader-heading').focus({preventScroll: true});
        $('archive-reader-panel').scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
      }
    } catch (error) {
      if (sequence !== archiveOpenSequence || error.name === 'AbortError') return;
      archiveState.openError = error.status === 404 ? 'archiveEditionNotFound' : error.status === 429 ? 'msgRateLimited' : 'archiveEditionUnavailable';
    } finally {
      if (sequence === archiveOpenSequence) { archiveState.opening = false; renderArchive(); }
    }
  }
  function archivePage() {
    $('archive-query').addEventListener('input', () => { archiveState.query = $('archive-query').value; archiveFiltersChanged(); });
    $('archive-month').addEventListener('change', () => { archiveState.month = $('archive-month').value; archiveFiltersChanged(); });
    $('archive-date').addEventListener('input', () => { archiveState.date = $('archive-date').value; renderArchive(); });
    $('archive-search-form').addEventListener('submit', event => { event.preventDefault(); searchArchive(1); });
    $('archive-date-form').addEventListener('submit', event => { event.preventDefault(); openArchiveEdition($('archive-date').value); });
    $('archive-prev').addEventListener('click', () => { if (!archiveState.searching && archiveState.results?.page > 1) searchArchive(archiveState.results.page - 1); });
    $('archive-next').addEventListener('click', () => { if (!archiveState.searching && archiveState.results?.has_more) searchArchive(archiveState.results.page + 1); });
    $('archive-retry').addEventListener('click', () => loadArchiveIndex());
    const shared = new URLSearchParams(location.search).get('date') || '';
    loadArchiveIndex(validArchiveDate(shared) ? shared : '').then(() => {
      // Without a shared date, open the newest edition so the reader is never empty.
      if (shared || archiveState.selected || archiveState.opening) return;
      const latest = (archiveState.results?.items || []).map(item => item.date).sort().pop();
      if (latest) openArchiveEdition(latest, false);
    });
    if (shared) {
      if (validArchiveDate(shared)) openArchiveEdition(shared, false);
      else { archiveState.openError = 'archiveDateInvalid'; renderArchive(); }
    }
  }
  async function publicPage() {
    const path = location.pathname.replace(/\/$/, '');
    if (path === '/confirm' || path === '/unsubscribe') {
      $('landing').hidden = true;
      $('subscription-flow').hidden = false;
      const params = new URLSearchParams(location.search);
      view.flow = {unsubscribe: path === '/unsubscribe', id: params.get('id') || '', token: params.get('token') || '', busy: false, completed: false};
      history.replaceState(null, '', path);
      renderFlow();
      if (!view.flow.id || !view.flow.token) {
        message('flow-status', 'flowInvalidLink', true);
        return;
      }
      $('flow-button').addEventListener('click', async () => {
        const flow = view.flow;
        if (flow.busy || flow.completed) return;
        flow.busy = true;
        renderFlow();
        try {
          const result = await api(flow.unsubscribe ? '/api/unsubscribe' : '/api/confirm', {method: 'POST', body: {id: flow.id, token: flow.token}});
          const ok = ['confirmed', 'unsubscribed'].includes(result.status);
          flow.completed = true;
          message('flow-status', ok ? (flow.unsubscribe ? 'flowUnsubscribed' : 'flowConfirmed') : 'flowExpired', !ok);
        } catch {
          message('flow-status', 'flowFailed', true);
        } finally {
          flow.busy = false;
          renderFlow();
        }
      });
      return;
    }
    try {
      const data = await api('/api/public/preview');
      view.signupEnabled = data.signup_enabled === true;
      if (data.available && typeof data.html === 'string' && data.html) {
        const highlights = editionHighlights(data.html, language);
        // The full frame remains the fallback when no item structure is recognised.
        if (highlights.shown || showPreview('public-preview', data)) {
          view.edition = {subject: data.subject, date: data.date, html: highlights.shown ? data.html : ''};
          $('preview-empty').hidden = true;
        }
      }
    } catch { /* The landing page remains usable while the service starts. */ }
    renderPublicState();
    $('signup-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (!view.signupEnabled || view.signupSubmitting || !$('signup-form').reportValidity()) return;
      view.signupSubmitting = true;
      renderPublicState();
      message('signup-status', 'signupSubmitting');
      try {
        await api('/api/subscribe', {method: 'POST', body: {email: $('email').value.trim(), website: $('website').value}});
        message('signup-status', 'signupCheckEmail');
        $('signup-form').reset();
      } catch {
        message('signup-status', 'signupFailed', true);
      } finally {
        view.signupSubmitting = false;
        renderPublicState();
      }
    });
  }
  function emptyEmailLogin() {
    return {email: '', code: '', challengeId: null, requestBusy: false, verifyBusy: false, cooldownUntil: 0};
  }
  function resetEmailLogin() {
    emailLoginSequence += 1;
    if (emailLoginTimer) clearTimeout(emailLoginTimer);
    emailLoginTimer = null;
    emailLogin.email = ''; emailLogin.code = ''; emailLogin.challengeId = null;
    emailLogin = emptyEmailLogin();
    message('admin-email-login-status', '');
    renderEmailLogin();
  }
  function renderEmailLogin() {
    if (!$('admin-email-login-form')) return;
    const busy = emailLogin.requestBusy || emailLogin.verifyBusy || recoveryLoginBusy || logoutBusy || adminSessionRestoring;
    const seconds = Math.max(0, Math.ceil((emailLogin.cooldownUntil - Date.now()) / 1000));
    const email = $('admin-login-email');
    const code = $('admin-login-code');
    if (email.value !== emailLogin.email) email.value = emailLogin.email;
    if (code.value !== emailLogin.code) code.value = emailLogin.code;
    email.disabled = busy;
    code.disabled = busy;
    $('admin-code-login-form').hidden = !emailLogin.challengeId;
    $('admin-email-login-form').setAttribute('aria-busy', String(emailLogin.requestBusy));
    $('admin-code-login-form').setAttribute('aria-busy', String(emailLogin.verifyBusy));
    $('admin-request-code-button').disabled = busy || seconds > 0;
    $('admin-request-code-button').textContent = t(emailLogin.requestBusy ? 'adminRequestingCode' :
      seconds > 0 ? 'adminResendCountdown' : 'adminRequestCode', {seconds});
    $('admin-resend-code-button').disabled = busy || seconds > 0;
    $('admin-resend-code-button').textContent = t(seconds > 0 ? 'adminResendCountdown' : 'adminResendCode', {seconds});
    $('admin-verify-code-button').disabled = busy || !emailLogin.challengeId || !/^[0-9]{6}$/.test(emailLogin.code);
    $('admin-verify-code-button').textContent = t(emailLogin.verifyBusy ? 'adminVerifyingCode' : 'adminVerifyCode');
    $('admin-token').disabled = busy;
    $('admin-recovery-submit').disabled = busy;
    $('logout-button').disabled = logoutBusy;
    $('logout-button').textContent = t(logoutBusy ? 'adminSigningOut' : 'adminLogout');
  }
  function tickEmailLoginCooldown() {
    if (emailLoginTimer) clearTimeout(emailLoginTimer);
    emailLoginTimer = null;
    if (emailLogin.cooldownUntil > Date.now()) {
      emailLoginTimer = setTimeout(() => {
        renderEmailLogin();
        tickEmailLoginCooldown();
      }, 1000);
    }
  }
  async function requestAdminCode() {
    if (emailLogin.requestBusy || emailLogin.verifyBusy || recoveryLoginBusy || logoutBusy || adminSessionRestoring ||
      emailLogin.cooldownUntil > Date.now() || !$('admin-email-login-form').reportValidity()) return;
    const generation = ++adminGeneration;
    const sequence = ++emailLoginSequence;
    const state = emailLogin;
    state.email = $('admin-login-email').value.trim();
    state.code = ''; state.challengeId = null;
    state.requestBusy = true;
    state.cooldownUntil = Date.now() + 60000;
    renderEmailLogin(); tickEmailLoginCooldown();
    message('admin-email-login-status', 'adminRequestingCode');
    try {
      const result = await api('/api/admin-login/request', {method: 'POST', body: {email: state.email}});
      if (generation !== adminGeneration || sequence !== emailLoginSequence || state !== emailLogin) return;
      if (result?.status !== 'check_email' || typeof result.challenge_id !== 'string' ||
        !/^[A-Za-z0-9_-]{24}$/.test(result.challenge_id)) throw errorFor('adminEmailLoginUnavailable');
      state.challengeId = result.challenge_id;
      message('admin-email-login-status', 'adminCodeRequested');
    } catch (error) {
      if (generation !== adminGeneration || sequence !== emailLoginSequence || state !== emailLogin) return;
      message('admin-email-login-status', error.status === 429 ? 'msgRateLimited' : 'adminEmailLoginUnavailable', true);
    } finally {
      if (generation === adminGeneration && sequence === emailLoginSequence && state === emailLogin) {
        state.requestBusy = false;
        renderEmailLogin();
        if (state.challengeId) $('admin-login-code').focus();
      }
    }
  }
  function validAdminSession(result) {
    return result?.status === 'authenticated' && typeof result.expires_at === 'string' &&
      /(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(result.expires_at) &&
      Number.isFinite(Date.parse(result.expires_at));
  }
  function setAdminScreen(screen) {
    $('admin-shell').hidden = screen === 'login';
    $('admin-session-check').hidden = screen !== 'checking';
    $('admin-login').hidden = screen !== 'login';
    $('admin-dashboard').hidden = screen !== 'dashboard';
    $('logout-button').hidden = screen !== 'dashboard';
  }
  function showAdminDashboard(generation) {
    if (generation !== adminGeneration || !hasAdminSession()) return;
    $('admin-token').value = '';
    $('admin-recovery-login').open = false;
    setAdminScreen('dashboard');
    resetEmailLogin();
    message('login-status', '');
    refreshAdmin().catch(error => {
      if (!error.stale && generation === adminGeneration) showError('action-status', error);
    });
  }
  async function verifyAdminCode() {
    const code = $('admin-login-code').value;
    if (!emailLogin.challengeId || !/^[0-9]{6}$/.test(code) || emailLogin.requestBusy ||
      emailLogin.verifyBusy || recoveryLoginBusy || logoutBusy || adminSessionRestoring) return;
    const generation = ++adminGeneration;
    const sequence = ++emailLoginSequence;
    const state = emailLogin;
    state.code = code;
    state.verifyBusy = true;
    renderEmailLogin();
    message('admin-email-login-status', 'adminVerifyingCode');
    try {
      const result = await api('/api/admin-login/verify', {method: 'POST',
        body: {challenge_id: state.challengeId, code: state.code}});
      if (generation !== adminGeneration || sequence !== emailLoginSequence || state !== emailLogin) return;
      if (!validAdminSession(result)) throw errorFor('adminEmailLoginUnavailable');
      adminToken = '';
      adminCookieSession = true;
      state.code = ''; state.challengeId = null;
      showAdminDashboard(generation);
    } catch (error) {
      if (error.stale || generation !== adminGeneration || sequence !== emailLoginSequence || state !== emailLogin) return;
      adminToken = '';
      adminCookieSession = false;
      message('admin-email-login-status', error.status === 401 ? 'adminCodeInvalid' :
        error.status === 429 ? 'msgRateLimited' : 'adminEmailLoginUnavailable', true);
    } finally {
      if (generation === adminGeneration && sequence === emailLoginSequence && state === emailLogin) {
        state.verifyBusy = false;
        renderEmailLogin();
      }
    }
  }
  async function restoreAdminSession() {
    if (adminSessionRestoring) return;
    const generation = ++adminGeneration;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    adminSessionRestoring = true;
    setAdminScreen('checking');
    $('admin-session-retry').hidden = true;
    message('admin-session-status', 'adminRestoringSession');
    try {
      const result = await api('/api/admin/session', {signal: controller.signal});
      if (generation !== adminGeneration) return;
      if (!validAdminSession(result)) throw errorFor('adminSessionRestoreUnavailable');
      adminToken = '';
      adminCookieSession = true;
      showAdminDashboard(generation);
    } catch (error) {
      if (error.stale || generation !== adminGeneration) return;
      if (error.status === 401) {
        clearAdminSession();
      } else {
        message('admin-session-status', 'adminSessionRestoreUnavailable', true);
        $('admin-session-retry').hidden = false;
      }
    } finally {
      clearTimeout(timeout);
      if (generation === adminGeneration) {
        adminSessionRestoring = false;
        renderEmailLogin();
      }
    }
  }
  async function logout() {
    if (logoutBusy) return;
    if (!hasAdminSession()) { clearAdminSession(); return; }
    const generation = ++adminGeneration;
    logoutBusy = true;
    setAdminScreen('login');
    message('admin-email-login-status', 'adminSigningOut');
    renderEmailLogin();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let signedOut = false;
    try {
      const result = await api('/api/admin/logout', {method: 'POST', admin: true, body: {}, signal: controller.signal});
      if (result?.status !== 'signed_out') throw errorFor('adminSignOutUnavailable');
      signedOut = true;
    } catch (error) {
      if (error.stale || generation !== adminGeneration) return;
      setAdminScreen('dashboard');
      message('action-status', 'adminSignOutUnavailable', true);
    }
    finally {
      clearTimeout(timeout);
      if (generation === adminGeneration) {
        if (signedOut) {
          clearAdminSession();
          message('admin-email-login-status', 'adminSignedOut');
        } else {
          logoutBusy = false;
          renderEmailLogin();
        }
      }
    }
  }
  function clearAdminSession() {
    adminGeneration += 1;
    adminToken = '';
    adminCookieSession = false;
    adminSessionRestoring = false;
    recoveryLoginBusy = false;
    logoutBusy = false;
    resetEmailLogin();
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = null;
    view.adminStatus = null;
    view.adminStatusUnavailable = false;
    view.subscribers = [];
    view.subscribersLoading = false;
    view.runs = [];
    view.subscribersUnavailable = false;
    view.runsUnavailable = false;
    deliveryLoadSequence += 1;
    view.deliveryReport = null;
    view.deliveryReportState = 'idle';
    pendingSubscriberActions.clear();
    moomooLoadSequence += 1;
    moomooSettings.draft = '';
    moomooSettings.savedQueries = [];
    moomooSettings.revision = null;
    moomooSettings = emptyMoomooSettings();
    renderMoomooSettings();
    $('admin-token').value = '';
    setAdminScreen('login');
    $('admin-session-retry').hidden = true;
    message('admin-session-status', '');
    $('admin-status').textContent = '';
    $('subscriber-count').textContent = '';
    $('subscribers-body').replaceChildren();
    renderDeliveryReport();
    $('private-preview').srcdoc = '';
    $('private-preview-panel').hidden = true;
    $('publish-button').disabled = true;
    message('login-status', '');
    message('action-status', '');
  }
  function renderSubscribers() {
    const tbody = $('subscribers-body');
    if (!tbody) return;
    tbody.replaceChildren();
    if (view.subscribersLoading) {
      $('subscriber-count').textContent = t('adminSubscribersLoading');
      return;
    }
    if (view.subscribersUnavailable) {
      $('subscriber-count').textContent = t('subscribersUnavailable');
      return;
    }
    const items = view.subscribers;
    $('subscriber-count').textContent = t('subscriberCount', {count: items.filter(item => item.status === 'confirmed').length});
    if (!items.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 3;
      cell.textContent = t('noSubscriptions');
      row.append(cell); tbody.append(row);
      return;
    }
    for (const item of items) {
      const row = document.createElement('tr');
      const email = document.createElement('td');
      email.textContent = item.email || '—';
      const state = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'status-badge';
      badge.textContent = t(STATE_KEYS[item.status] || 'stateUnknown');
      state.append(badge);
      const action = document.createElement('td');
      if (!['suppressed', 'unsubscribed'].includes(item.status)) {
        const button = document.createElement('button');
        button.className = 'table-button';
        button.type = 'button';
        button.textContent = t('unsubscribeAction');
        const generation = adminGeneration;
        const actionKey = String(generation) + ':' + item.id;
        button.disabled = pendingSubscriberActions.has(actionKey);
        button.addEventListener('click', async () => {
          if (pendingSubscriberActions.has(actionKey)) return;
          pendingSubscriberActions.add(actionKey);
          button.disabled = true;
          try {
            await api('/api/admin/subscribers', {method: 'POST', admin: true, body: {id: item.id, action: 'suppress'}});
            await refreshAdmin();
          } catch (error) {
            if (error.stale) return;
            showError('action-status', error);
            button.disabled = false;
          } finally {
            pendingSubscriberActions.delete(actionKey);
            if (generation === adminGeneration) renderSubscribers();
          }
        });
        action.append(button);
      }
      row.append(email, state, action); tbody.append(row);
    }
  }
  function deliveryCount(value) {
    return Number.isSafeInteger(value) && value >= 0 ? String(value) : '—';
  }
  function deliveryDate(value) {
    // Keep the recorded date/offset; never guess a missing timezone.
    return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value) ? value : '—';
  }
  function deliveryCell(value, className = '') {
    const cell = document.createElement('td');
    cell.textContent = value;
    if (className) cell.className = className;
    return cell;
  }
  function deliveryEmptyRow(body, columns, key) {
    const row = document.createElement('tr');
    const cell = deliveryCell(t(key), 'delivery-empty');
    cell.colSpan = columns;
    row.append(cell); body.append(row);
  }
  function deliveryBadge(key) {
    const badge = document.createElement('span');
    badge.className = 'status-badge delivery-badge';
    badge.textContent = t(key);
    return badge;
  }
  function deliveryWorkflowKey(run) {
    const conclusions = {success: 'deliveryWorkflowSuccess', failure: 'deliveryWorkflowFailed',
      cancelled: 'stateCancelled', timed_out: 'stateTimedOut', skipped: 'stateSkipped',
      action_required: 'stateActionRequired', neutral: 'deliveryWorkflowNeutral',
      stale: 'deliveryWorkflowStale', startup_failure: 'deliveryWorkflowStartupFailed'};
    if (Object.hasOwn(conclusions, run.conclusion)) return conclusions[run.conclusion];
    const statuses = {queued: 'stateQueued', in_progress: 'stateInProgress', waiting: 'stateWaiting',
      pending: 'stateWaiting', requested: 'stateRequested'};
    return Object.hasOwn(statuses, run.status) ? statuses[run.status] : 'deliveryWorkflowUnknown';
  }
  function deliveryTaskKey(status) {
    const keys = {running: 'deliveryResultRunning', completed: 'deliveryResultCompleted',
      failed: 'deliveryResultFailed', needs_attention: 'deliveryNeedsAttention'};
    return Object.hasOwn(keys, status) ? keys[status] : 'deliveryUnknown';
  }
  function renderDeliveryRuns(report) {
    const body = $('delivery-runs-body');
    body.replaceChildren();
    if (!report.runs.length) {
      deliveryEmptyRow(body, 7, report.runs_unavailable ? 'deliveryRunsUnavailable' : 'deliveryNoRuns');
      return;
    }
    for (const run of report.runs) {
      if (!run || typeof run !== 'object' || Array.isArray(run)) continue;
      const row = document.createElement('tr');
      const identifier = Number.isSafeInteger(run.id) && run.id > 0 ? String(run.id) : '—';
      const linkCell = document.createElement('td');
      const safeURL = identifier !== '—' && run.html_url ===
        'https://github.com/Rexmiao/levyquant-digest/actions/runs/' + identifier;
      const link = document.createElement(safeURL ? 'a' : 'span');
      if (safeURL) { link.href = run.html_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      link.textContent = t('runLabel', {id: identifier});
      linkCell.append(link);
      const modeKeys = {send: 'deliveryModeSend', preview: 'deliveryModePreview',
        'preview-email': 'deliveryModePreviewEmail', 'smtp-test': 'deliveryModeSmtpTest'};
      const modeCell = document.createElement('td');
      modeCell.append(deliveryBadge(Object.hasOwn(modeKeys, run.mode) ? modeKeys[run.mode] : 'deliveryModeUnknown'));
      const countsCell = document.createElement('td');
      const counts = run.counts;
      if (!counts || typeof counts !== 'object' || Array.isArray(counts) ||
        !DELIVERY_COUNT_FIELDS.some(([key]) => deliveryCount(counts[key]) !== '—')) {
        countsCell.textContent = '—';
      } else {
        const details = document.createElement('details');
        details.className = 'delivery-count-details';
        const summary = document.createElement('summary');
        summary.textContent = t('deliveryCounts');
        const list = document.createElement('dl');
        for (const [key, label] of DELIVERY_COUNT_FIELDS) {
          const name = document.createElement('dt'); name.textContent = t(label);
          const count = document.createElement('dd'); count.textContent = deliveryCount(counts[key]);
          list.append(name, count);
        }
        details.append(summary, list); countsCell.append(details);
      }
      const diagnostics = [];
      if (DELIVERY_ERROR_TYPES.has(run.error_type)) diagnostics.push(run.error_type);
      if (DELIVERY_ERROR_CODES.has(run.error_code)) diagnostics.push(run.error_code);
      row.append(deliveryCell(deliveryDate(run.date)), linkCell, modeCell,
        deliveryCell(t(deliveryWorkflowKey(run)), 'delivery-result-cell'),
        deliveryCell(t(deliveryTaskKey(run.result_status)), 'delivery-result-cell'), countsCell,
        deliveryCell(diagnostics.length ? diagnostics.join(' / ') : '—', 'delivery-diagnostic'));
      body.append(row);
    }
  }
  function renderDeliveryReport() {
    const body = $('delivery-editions-body');
    if (!body) return;
    const runsBody = $('delivery-runs-body');
    body.replaceChildren(); runsBody.replaceChildren();
    const state = view.deliveryReportState;
    const busy = state === 'loading';
    for (const id of ['delivery-report-panel', 'delivery-runs-panel']) $(id).setAttribute('aria-busy', String(busy));
    const reportStatus = $('delivery-report-status');
    const runsStatus = $('delivery-runs-status');
    reportStatus.textContent = '';
    runsStatus.textContent = '';
    reportStatus.classList.toggle('error', state === 'unavailable');
    runsStatus.classList.toggle('warning', false);
    if (!hasAdminSession() || state === 'idle') return;
    if (busy || state === 'unavailable') {
      const key = busy ? 'deliveryLoading' : 'deliveryUnavailable';
      reportStatus.textContent = t(key);
      deliveryEmptyRow(body, 11, key); deliveryEmptyRow(runsBody, 7, key);
      return;
    }
    const report = view.deliveryReport;
    if (!report) return;
    if (report.runs_unavailable) {
      runsStatus.textContent = t('deliveryRunsUnavailable');
      runsStatus.classList.toggle('warning', true);
    }
    if (!report.editions.length) deliveryEmptyRow(body, 11, 'deliveryNoEditions');
    for (const edition of report.editions) {
      if (!edition || typeof edition !== 'object' || edition.mode !== 'send') continue;
      const row = document.createElement('tr');
      const stateCell = document.createElement('td');
      stateCell.className = 'delivery-edition-state';
      stateCell.append(deliveryBadge(edition.status === 'completed' ? 'deliveryEditionCompleted' : deliveryTaskKey(edition.status)));
      if (edition.legacy_counts === true) {
        const legacy = document.createElement('span');
        legacy.className = 'delivery-legacy-note';
        legacy.textContent = t('deliveryLegacyCounts'); stateCell.append(legacy);
      }
      row.append(deliveryCell(deliveryDate(edition.date)), stateCell);
      for (const [key] of DELIVERY_COUNT_FIELDS) {
        const cell = deliveryCell(deliveryCount(edition[key]), 'delivery-number');
        if (key === 'internal_count') cell.classList.add('delivery-internal-count');
        row.append(cell);
      }
      body.append(row);
    }
    renderDeliveryRuns(report);
  }
  function deliveryReportResponse(value) {
    if (!value || !Array.isArray(value.editions) || !Array.isArray(value.runs) || value.window_days !== 7 ||
      value.editions.length > 7 || value.runs.length > 50 || typeof value.runs_unavailable !== 'boolean' ||
      value.editions.some(edition => !edition || typeof edition !== 'object' || Array.isArray(edition) || edition.mode !== 'send') ||
      value.runs.some(run => !run || typeof run !== 'object' || Array.isArray(run))) {
      throw errorFor('deliveryUnavailable');
    }
    return value;
  }
  async function loadDeliveryReport() {
    if (!hasAdminSession()) return;
    const generation = adminGeneration;
    const sequence = ++deliveryLoadSequence;
    view.deliveryReport = null;
    view.deliveryReportState = 'loading';
    renderDeliveryReport();
    try {
      const report = deliveryReportResponse(await api('/api/admin/delivery-report', {admin: true}));
      if (generation !== adminGeneration || sequence !== deliveryLoadSequence) return;
      view.deliveryReport = report;
      view.deliveryReportState = 'loaded';
    } catch (error) {
      if (error.stale || generation !== adminGeneration || sequence !== deliveryLoadSequence) return;
      view.deliveryReport = null;
      view.deliveryReportState = 'unavailable';
    }
    renderDeliveryReport();
  }
  function renderAdminStatus() {
    const status = view.adminStatus;
    if (!$('admin-status')) return;
    if (view.adminStatusUnavailable || !status) {
      $('admin-status').textContent = t(view.adminStatusUnavailable ? 'adminStatusUnavailable' : 'adminStatusLoading');
      return;
    }
    $('admin-status').textContent = Array.isArray(status.missing) && status.missing.length ?
      t('adminMissing', {names: status.missing.join(language === 'zh' ? '、' : ', ')}) : t('adminConnected');
    if (view.subscribersUnavailable) $('admin-status').textContent += ' ' + t('stateReadFailed');
  }
  function emptyMoomooSettings() {
    return {status: 'unavailable', revision: null, savedQueries: [], draft: ''};
  }
  function moomooQueriesFromDraft(draft) {
    const lines = draft.split(/\r?\n/);
    if (lines.some(value => MOOMOO_QUERY_CONTROL_CHARS.test(value))) return null;
    const queries = lines.map(value => value.trim()).filter(Boolean);
    if (queries.length < 1 || queries.length > 4 || queries.some(value =>
      Array.from(value).length > 200)) return null;
    return queries;
  }
  function moomooSettingsResponse(value) {
    if (!value || !Array.isArray(value.queries) || value.queries.length < 1 || value.queries.length > 4 ||
      !Number.isSafeInteger(value.revision) || value.revision < 0 || value.queries.some(query =>
        typeof query !== 'string' || !query || query !== query.trim() || Array.from(query).length > 200 ||
        MOOMOO_QUERY_CONTROL_CHARS.test(query))) throw errorFor('moomooUnavailable');
    return {queries: [...value.queries], revision: value.revision};
  }
  function moomooDraftIsDirty(state = moomooSettings) {
    const queries = moomooQueriesFromDraft(state.draft);
    return queries === null || JSON.stringify(queries) !== JSON.stringify(state.savedQueries);
  }
  function renderMoomooSettings() {
    const field = $('moomoo-queries');
    if (!field) return;
    const state = moomooSettings;
    const busy = ['loading', 'saving'].includes(state.status);
    const blocked = ['unavailable', 'conflict', 'invalid'].includes(state.status);
    const valid = moomooQueriesFromDraft(state.draft) !== null;
    if (field.value !== state.draft) field.value = state.draft;
    field.disabled = !hasAdminSession() || state.revision === null || busy;
    field.setAttribute('aria-invalid', String(state.status === 'invalid'));
    $('moomoo-settings-form').setAttribute('aria-busy', String(busy));
    $('moomoo-save-button').disabled = !hasAdminSession() || busy || blocked || !valid ||
      state.revision === null || !moomooDraftIsDirty(state);
    $('moomoo-save-button').textContent = t(state.status === 'saving' ? 'moomooSaving' : 'moomooSave');
    $('moomoo-refresh-button').disabled = !hasAdminSession() || busy;
    const statusKeys = {loading: 'moomooLoading', loaded: 'moomooLoaded', dirty: 'moomooDirty',
      saving: 'moomooSaving', saved: 'moomooSaved', conflict: 'moomooConflict',
      unavailable: 'moomooUnavailable', invalid: 'moomooInvalid'};
    const statusNode = $('moomoo-settings-status');
    statusNode.textContent = hasAdminSession() ? t(statusKeys[state.status] || 'moomooUnavailable') : '';
    statusNode.classList.toggle('error', ['conflict', 'unavailable', 'invalid'].includes(state.status));
    statusNode.classList.toggle('success', state.status === 'saved');
  }
  async function loadMoomooSettings({replaceDraft = false} = {}) {
    if (!hasAdminSession() || moomooSettings.status === 'saving') return;
    const generation = adminGeneration;
    const sequence = ++moomooLoadSequence;
    const state = moomooSettings;
    const keepDraft = !replaceDraft && state.revision !== null && moomooDraftIsDirty(state);
    const draft = state.draft;
    state.status = 'loading';
    renderMoomooSettings();
    try {
      const result = moomooSettingsResponse(await api('/api/admin/moomoo-settings', {admin: true}));
      if (generation !== adminGeneration || sequence !== moomooLoadSequence || state !== moomooSettings) return;
      state.revision = result.revision;
      state.savedQueries = result.queries;
      state.draft = keepDraft ? draft : result.queries.join('\n');
      state.status = moomooDraftIsDirty(state) ? 'dirty' : 'loaded';
      renderMoomooSettings();
    } catch (error) {
      if (error.stale || generation !== adminGeneration || sequence !== moomooLoadSequence || state !== moomooSettings) return;
      state.status = 'unavailable';
      renderMoomooSettings();
    }
  }
  async function saveMoomooSettings() {
    const state = moomooSettings;
    const queries = moomooQueriesFromDraft(state.draft);
    if (!hasAdminSession() || state.revision === null || !queries || !moomooDraftIsDirty(state) ||
      ['loading', 'saving', 'unavailable', 'conflict', 'invalid'].includes(state.status)) return;
    const generation = adminGeneration;
    const revision = state.revision;
    state.status = 'saving';
    renderMoomooSettings();
    try {
      const result = moomooSettingsResponse(await api('/api/admin/moomoo-settings', {
        method: 'POST', admin: true, body: {queries, revision}
      }));
      if (generation !== adminGeneration || state !== moomooSettings) return;
      if (result.revision !== revision + 1) throw errorFor('moomooUnavailable');
      state.revision = result.revision;
      state.savedQueries = result.queries;
      state.draft = result.queries.join('\n');
      state.status = 'saved';
    } catch (error) {
      if (error.stale || generation !== adminGeneration || state !== moomooSettings) return;
      state.status = error.status === 409 ? 'conflict' : error.status === 400 ? 'invalid' : 'unavailable';
    }
    if (generation === adminGeneration && state === moomooSettings) renderMoomooSettings();
  }
  function isCurrentAdminRefresh(generation, sequence) {
    return generation === adminGeneration && sequence === adminRefreshSequence;
  }
  async function loadAdminStatus(generation, sequence) {
    try {
      const status = await api('/api/admin/status', {admin: true});
      if (!isCurrentAdminRefresh(generation, sequence)) return;
      view.adminStatus = status;
      view.runs = Array.isArray(status.runs) ? status.runs : [];
      view.runsUnavailable = !!status.runs_error;
      renderAdminStatus();
      renderDeliveryReport();
    } catch (error) {
      if (!isCurrentAdminRefresh(generation, sequence)) return;
      view.adminStatusUnavailable = true;
      renderAdminStatus();
      throw error;
    }
  }
  async function loadAdminSubscribers(generation, sequence) {
    try {
      const list = await api('/api/admin/subscribers', {admin: true});
      if (!isCurrentAdminRefresh(generation, sequence)) return;
      view.subscribers = Array.isArray(list.subscribers) ? list.subscribers : [];
      view.subscribersUnavailable = false;
    } catch (error) {
      if (!isCurrentAdminRefresh(generation, sequence)) return;
      view.subscribers = [];
      view.subscribersUnavailable = true;
      if (error.status !== 503) throw error;
    } finally {
      if (isCurrentAdminRefresh(generation, sequence)) {
        view.subscribersLoading = false;
        renderSubscribers();
        renderAdminStatus();
      }
    }
  }
  async function refreshAdmin() {
    if (!hasAdminSession()) return;
    const generation = adminGeneration;
    const sequence = ++adminRefreshSequence;
    view.adminStatusUnavailable = false;
    view.subscribersLoading = true;
    renderAdminStatus();
    renderSubscribers();
    const status = loadAdminStatus(generation, sequence);
    const subscribers = loadAdminSubscribers(generation, sequence);
    loadDeliveryReport();
    loadMoomooSettings();
    await Promise.all([status, subscribers]);
  }
  async function pollPreview(attempt = 0) {
    try {
      const data = await api('/api/admin/preview', {admin: true});
      if (data.status === 'ready' && showPreview('private-preview', data.preview || data)) {
        $('private-preview-panel').hidden = false;
        $('private-preview-date').textContent = (data.preview || data).date || '';
        $('publish-button').disabled = false;
        $('generate-button').disabled = false;
        message('action-status', 'previewReady');
      } else if (['failed', 'error'].includes(data.status)) {
        throw errorFor('previewFailed');
      } else if (attempt < 180 && hasAdminSession()) {
        previewTimer = setTimeout(() => pollPreview(attempt + 1), 3000);
      } else {
        $('generate-button').disabled = false;
        message('action-status', 'previewPending', true);
      }
    } catch (error) {
      if (error.stale) return;
      $('generate-button').disabled = false;
      showError('action-status', error);
    }
  }
  function adminPage() {
    $('admin-login-email').addEventListener('input', event => {
      if (emailLogin.requestBusy || emailLogin.verifyBusy || recoveryLoginBusy || logoutBusy || adminSessionRestoring) return;
      if (emailLogin.email !== event.target.value && emailLogin.challengeId) {
        emailLogin.challengeId = null;
        emailLogin.code = '';
      }
      emailLogin.email = event.target.value;
      renderEmailLogin();
    });
    $('admin-login-code').addEventListener('input', event => {
      emailLogin.code = event.target.value;
      renderEmailLogin();
    });
    $('admin-email-login-form').addEventListener('submit', event => {
      event.preventDefault(); requestAdminCode();
    });
    $('admin-code-login-form').addEventListener('submit', event => {
      event.preventDefault(); verifyAdminCode();
    });
    $('admin-resend-code-button').addEventListener('click', requestAdminCode);
    $('moomoo-queries').addEventListener('input', event => {
      const state = moomooSettings;
      if (['loading', 'saving'].includes(state.status)) return;
      state.draft = event.target.value;
      if (!['conflict', 'unavailable'].includes(state.status)) {
        state.status = !moomooQueriesFromDraft(state.draft) ? 'invalid' :
          moomooDraftIsDirty(state) ? 'dirty' : 'loaded';
      }
      renderMoomooSettings();
    });
    $('moomoo-settings-form').addEventListener('submit', event => {
      event.preventDefault();
      saveMoomooSettings();
    });
    $('moomoo-refresh-button').addEventListener('click', () => loadMoomooSettings({replaceDraft: true}));
    $('login-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (emailLogin.requestBusy || emailLogin.verifyBusy || recoveryLoginBusy || logoutBusy || adminSessionRestoring) return;
      const generation = ++adminGeneration;
      emailLoginSequence += 1;
      const token = $('admin-token').value.trim();
      $('admin-token').value = '';
      adminToken = token;
      recoveryLoginBusy = true;
      renderEmailLogin();
      message('login-status', 'validatingAdmin');
      try {
        const result = await api('/api/admin/session', {method: 'POST', admin: true, body: {}});
        if (generation !== adminGeneration) return;
        if (!validAdminSession(result)) throw errorFor('adminEmailLoginUnavailable');
        adminToken = '';
        adminCookieSession = true;
        showAdminDashboard(generation);
      } catch (error) {
        if (error.stale || generation !== adminGeneration) return;
        adminToken = '';
        adminCookieSession = false;
        showError('login-status', error);
      } finally {
        if (generation === adminGeneration) { recoveryLoginBusy = false; renderEmailLogin(); }
      }
    });
    $('admin-session-retry').addEventListener('click', restoreAdminSession);
    $('logout-button').addEventListener('click', logout);
    $('refresh-button').addEventListener('click', () => refreshAdmin().catch(error => {
      if (!error.stale) showError('action-status', error);
    }));
    $('generate-button').addEventListener('click', async () => {
      $('generate-button').disabled = true; $('publish-button').disabled = true;
      message('action-status', 'previewGenerating');
      try {
        await api('/api/admin/preview', {method: 'POST', admin: true, body: {}});
        pollPreview();
      } catch (error) {
        if (error.stale) return;
        $('generate-button').disabled = false;
        showError('action-status', error);
      }
    });
    $('publish-button').addEventListener('click', async () => {
      $('publish-button').disabled = true;
      try {
        await api('/api/admin/publish', {method: 'POST', admin: true, body: {}});
        message('action-status', 'previewPublished');
      } catch (error) {
        if (!error.stale) showError('action-status', error);
      } finally { $('publish-button').disabled = false; }
    });
    $('send-button').addEventListener('click', async () => {
      $('send-button').disabled = true;
      try {
        await api('/api/admin/send', {method: 'POST', admin: true, body: {}});
        message('action-status', 'sendQueued');
        await refreshAdmin();
      } catch (error) {
        if (!error.stale) showError('action-status', error);
      } finally { $('send-button').disabled = false; }
    });
    let framed = false;
    try { framed = window.self !== window.top; } catch (error) { framed = true; }
    if (framed && $('admin-framed-notice')) {
      $('admin-framed-link').href = location.origin + '/admin';
      $('admin-framed-notice').hidden = false;
    }
    restoreAdminSession();
  }
  for (const button of document.querySelectorAll('[data-language]')) {
    button.addEventListener('click', () => setLanguage(button.getAttribute('data-language'), true));
  }
  setLanguage(preferredLanguage());
  if (document.body.dataset.page === 'archive') archivePage();
  else if (document.body.dataset.page === 'admin') adminPage();
  else publicPage();
})();
