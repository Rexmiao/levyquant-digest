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
      signupCheckEmail: 'Check your inbox or spam folder for a confirmation link. If you are already subscribed, no action is needed.',
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
      signupCheckEmail: '请查看收件箱或垃圾邮件中的确认链接。已经订阅的邮箱无需重复操作。',
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
  "latestEditionLink": "Latest edition",
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
  "signupConsent": "Email me the morning briefing. I can unsubscribe at any time.",
  "signupConfirmationNote": "Confirm your email to join. Every issue includes an unsubscribe link.",
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
  "latestEditionLink": "最新简报",
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
  "signupConsent": "我希望收到每日晨间简报，并可随时退订。",
  "signupConfirmationNote": "确认邮箱后完成订阅。每期简报都附有退订链接。",
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
  let adminGeneration = 0;
  let previewTimer = null;
  let moomooLoadSequence = 0;
  let moomooSettings = emptyMoomooSettings();
  const currentMessages = new Map();
  const pendingSubscriberActions = new Set();
  const view = {
    edition: null, signupEnabled: false, signupSubmitting: false, flow: null,
    subscribers: [], subscribersUnavailable: false, runs: [], runsUnavailable: false, adminStatus: null
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
    return String(navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
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
  async function api(path, {method = 'GET', body, admin = false} = {}) {
    const sessionGeneration = adminGeneration;
    const headers = {'Accept': 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (admin) headers.Authorization = 'Bearer ' + adminToken;
    const response = await fetch(path, {method, headers, credentials: 'same-origin', cache: 'no-store', ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    let data;
    try { data = await response.json(); } catch { throw errorFor('msgServiceUnavailable'); }
    if (admin && sessionGeneration !== adminGeneration) {
      const stale = errorFor('msgStaleSession');
      stale.stale = true;
      throw stale;
    }
    if (!response.ok) {
      if (admin && response.status === 401) logout();
      throw errorFor(response.status === 401 ? 'msgInvalidAdmin' : response.status === 429 ? 'msgRateLimited' :
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
    $('edition-heading').textContent = t(edition ? 'publicEditionFallback' : 'publicPreviewEmptyHeading');
    $('edition-date').textContent = edition?.date || t('comingSoon');
    $('edition-notice').textContent = t(edition ? 'publicPreviewNotice' : 'publicPreviewPreparing');
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
  function renderDynamic() {
    if (document.body.dataset.page === 'admin') {
      if (view.adminStatus) renderAdminStatus();
      renderSubscribers();
      renderRuns();
      renderMoomooSettings();
    } else {
      renderPublicState();
      renderFlow();
    }
  }
  function showPreview(frameId, preview) {
    const frame = $(frameId);
    if (typeof preview?.html !== 'string' || !preview.html) return false;
    const parsed = new DOMParser().parseFromString(preview.html, 'text/html');
    let coverage = parsed.querySelector('[data-digest-block="coverage"]')?.closest('tr');
    if (!coverage) {
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
      if (data.available && showPreview('public-preview', data)) {
        view.edition = {subject: data.subject, date: data.date};
        $('preview-empty').hidden = true;
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
  function logout() {
    adminGeneration += 1;
    adminToken = '';
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = null;
    view.adminStatus = null;
    view.subscribers = [];
    view.runs = [];
    view.subscribersUnavailable = false;
    view.runsUnavailable = false;
    pendingSubscriberActions.clear();
    moomooLoadSequence += 1;
    moomooSettings.draft = '';
    moomooSettings.savedQueries = [];
    moomooSettings.revision = null;
    moomooSettings = emptyMoomooSettings();
    renderMoomooSettings();
    $('admin-token').value = '';
    $('admin-dashboard').hidden = true;
    $('admin-login').hidden = false;
    $('subscribers-body').replaceChildren();
    $('runs-list').replaceChildren();
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
  function renderRuns() {
    const container = $('runs-list');
    if (!container) return;
    container.replaceChildren();
    if (view.runsUnavailable) { container.textContent = t('runsUnavailable'); return; }
    if (!view.runs.length) { container.textContent = t('noRuns'); return; }
    for (const run of view.runs) {
      const row = document.createElement('div'); row.className = 'run-item';
      const link = document.createElement('a');
      if (typeof run.html_url === 'string' && /^https:\/\/github\.com\/Rexmiao\/levyquant-digest\/actions\/runs\/\d+$/.test(run.html_url)) {
        link.href = run.html_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      }
      link.textContent = t('runLabel', {id: run.id || '—'});
      const state = document.createElement('span');
      state.textContent = t(STATE_KEYS[run.conclusion || run.status] || 'stateUnknown');
      row.append(link, state); container.append(row);
    }
  }
  function renderAdminStatus() {
    const status = view.adminStatus;
    if (!status || !$('admin-status')) return;
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
    field.disabled = !adminToken || state.revision === null || busy;
    field.setAttribute('aria-invalid', String(state.status === 'invalid'));
    $('moomoo-settings-form').setAttribute('aria-busy', String(busy));
    $('moomoo-save-button').disabled = !adminToken || busy || blocked || !valid ||
      state.revision === null || !moomooDraftIsDirty(state);
    $('moomoo-save-button').textContent = t(state.status === 'saving' ? 'moomooSaving' : 'moomooSave');
    $('moomoo-refresh-button').disabled = !adminToken || busy;
    const statusKeys = {loading: 'moomooLoading', loaded: 'moomooLoaded', dirty: 'moomooDirty',
      saving: 'moomooSaving', saved: 'moomooSaved', conflict: 'moomooConflict',
      unavailable: 'moomooUnavailable', invalid: 'moomooInvalid'};
    const statusNode = $('moomoo-settings-status');
    statusNode.textContent = adminToken ? t(statusKeys[state.status] || 'moomooUnavailable') : '';
    statusNode.classList.toggle('error', ['conflict', 'unavailable', 'invalid'].includes(state.status));
    statusNode.classList.toggle('success', state.status === 'saved');
  }
  async function loadMoomooSettings({replaceDraft = false} = {}) {
    if (!adminToken || moomooSettings.status === 'saving') return;
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
    if (!adminToken || state.revision === null || !queries || !moomooDraftIsDirty(state) ||
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
  async function refreshAdmin() {
    const status = await api('/api/admin/status', {admin: true});
    view.adminStatus = status;
    view.runs = Array.isArray(status.runs) ? status.runs : [];
    view.runsUnavailable = !!status.runs_error;
    renderRuns(); renderAdminStatus();
    try {
      const list = await api('/api/admin/subscribers', {admin: true});
      view.subscribers = Array.isArray(list.subscribers) ? list.subscribers : [];
      view.subscribersUnavailable = false;
    } catch (error) {
      if (error.stale || error.status !== 503) throw error;
      view.subscribers = [];
      view.subscribersUnavailable = true;
    }
    renderSubscribers(); renderAdminStatus();
    // Source settings have their own loading/error state and never block the
    // existing subscriber, preview or delivery controls.
    loadMoomooSettings();
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
      } else if (attempt < 180 && adminToken) {
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
      adminGeneration += 1;
      adminToken = $('admin-token').value.trim();
      message('login-status', 'validatingAdmin');
      try {
        await refreshAdmin();
        $('admin-token').value = '';
        $('admin-login').hidden = true;
        $('admin-dashboard').hidden = false;
        message('login-status', '');
      } catch (error) {
        if (error.stale) return;
        adminToken = '';
        showError('login-status', error);
      }
    });
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
  }
  for (const button of document.querySelectorAll('[data-language]')) {
    button.addEventListener('click', () => setLanguage(button.getAttribute('data-language'), true));
  }
  setLanguage(preferredLanguage());
  if (document.body.dataset.page === 'admin') adminPage(); else publicPage();
})();
