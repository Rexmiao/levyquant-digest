(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let adminToken = '';
  let adminGeneration = 0;
  let previewTimer = null;
  async function api(path, {method = 'GET', body, admin = false} = {}) {
    const sessionGeneration = adminGeneration;
    const headers = {'Accept': 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (admin) headers['Authorization'] = `Bearer ${adminToken}`;
    const response = await fetch(path, {method, headers, credentials: 'same-origin', cache: 'no-store', ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    let data;
    try { data = await response.json(); } catch { throw new Error('服务暂时不可用，请稍后再试。'); }
    if (admin && sessionGeneration !== adminGeneration) {
      const stale = new Error('当前管理会话已结束。');
      stale.stale = true;
      throw stale;
    }
    if (!response.ok) {
      if (admin && response.status === 401) logout();
      const err = new Error(response.status === 401 ? '管理员凭据不正确。' : response.status === 429 ? '操作较频繁，请稍后再试。' : response.status === 503 ? '服务配置尚未完成。' : '操作未完成，请检查配置后重试。');
      err.status = response.status;
      throw err;
    }
    return data;
  }
  function message(id, text, error = false) {
    const node = $(id); if (!node) return;
    node.textContent = text;
    node.classList.toggle('error', error);
    node.classList.toggle('success', !error && !!text);
  }
  function showPreview(frameId, preview) {
    const frame = $(frameId);
    if (typeof preview?.html !== 'string' || !preview.html) return false;
    frame.srcdoc = preview.html;
    frame.hidden = false;
    return true;
  }
  async function publicPage() {
    const flow = location.pathname.replace(/\/$/, '');
    if (flow === '/confirm' || flow === '/unsubscribe') {
      $('landing').hidden = true;
      $('subscription-flow').hidden = false;
      const unsubscribe = flow === '/unsubscribe';
      const params = new URLSearchParams(location.search);
      const id = params.get('id') || '';
      const token = params.get('token') || '';
      history.replaceState(null, '', flow);
      $('flow-title').textContent = unsubscribe ? 'Leave the list.' : 'Confirm your email.';
      $('flow-description').textContent = unsubscribe ? 'Click below to stop receiving the briefing at this address.' : 'One last step: confirm that you want to receive the LevyQuant morning briefing.';
      $('flow-button').textContent = unsubscribe ? 'Unsubscribe' : 'Confirm subscription';
      if (!id || !token) { $('flow-button').disabled = true; message('flow-status', 'This link is incomplete. Please use the link from your email.', true); return; }
      $('flow-button').addEventListener('click', async () => {
        $('flow-button').disabled = true;
        try {
          const result = await api(unsubscribe ? '/api/unsubscribe' : '/api/confirm', {method: 'POST', body: {id, token}});
          const ok = ['confirmed', 'unsubscribed'].includes(result.status);
          message('flow-status', ok ? (unsubscribe ? 'You have been unsubscribed.' : 'You are subscribed. Your next briefing is on its way in the morning.') : 'This link is invalid or has expired. You can request a new confirmation on the home page.', !ok);
        } catch { message('flow-status', 'We could not complete this request. Please try again shortly.', true); $('flow-button').disabled = false; }
      });
      return;
    }
    let signupEnabled = false;
    try {
      const data = await api('/api/public/preview');
      signupEnabled = data.signup_enabled === true;
      if (data.available && showPreview('public-preview', data)) {
        $('preview-empty').hidden = true;
        $('edition-heading').textContent = data.subject || 'The latest morning briefing';
        $('edition-date').textContent = data.date || '';
        $('edition-notice').textContent = 'The published edition, with links to the original sources.';
      }
    } catch { /* The landing page remains usable while the service starts. */ }
    $('signup-button').disabled = !signupEnabled;
    $('signup-button').textContent = signupEnabled ? 'Get the morning briefing →' : 'Subscriptions opening soon';
    $('signup-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (!signupEnabled || !$('signup-form').reportValidity()) return;
      $('signup-button').disabled = true;
      message('signup-status', 'Submitting…');
      try {
        await api('/api/subscribe', {method: 'POST', body: {email: $('email').value.trim(), website: $('website').value}});
        message('signup-status', 'Check your inbox for a confirmation link. If you are already subscribed, no action is needed.');
        $('signup-form').reset();
      } catch { message('signup-status', 'We could not accept this request. Please check your address or try again later.', true); }
      finally { $('signup-button').disabled = false; }
    });
  }
  function logout() {
    adminGeneration += 1;
    adminToken = '';
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = null;
    $('admin-token').value = '';
    $('admin-dashboard').hidden = true;
    $('admin-login').hidden = false;
    $('subscribers-body').replaceChildren();
    $('runs-list').replaceChildren();
    $('private-preview').srcdoc = '';
    $('private-preview-panel').hidden = true;
    $('publish-button').disabled = true;
    message('login-status', '');
  }
  function renderSubscribers(items) {
    const tbody = $('subscribers-body'); tbody.replaceChildren();
    $('subscriber-count').textContent = `${items.filter(x => x.status === 'confirmed').length} 位已确认`;
    if (!items.length) { const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 3; cell.textContent = '尚无公开订阅记录。'; row.append(cell); tbody.append(row); return; }
    for (const item of items) {
      const row = document.createElement('tr');
      const email = document.createElement('td'); email.textContent = item.email || '—';
      const state = document.createElement('td'); const badge = document.createElement('span'); badge.className = 'status-badge'; badge.textContent = item.status || 'unknown'; state.append(badge);
      const action = document.createElement('td');
      if (!['suppressed', 'unsubscribed'].includes(item.status)) {
        const button = document.createElement('button'); button.className = 'table-button'; button.type = 'button'; button.textContent = '取消订阅';
        button.addEventListener('click', async () => { button.disabled = true; try { await api('/api/admin/subscribers', {method: 'POST', admin: true, body: {id: item.id, action: 'suppress'}}); await refreshAdmin(); } catch (error) { message('action-status', error.message, true); button.disabled = false; } });
        action.append(button);
      }
      row.append(email, state, action); tbody.append(row);
    }
  }
  function renderRuns(items) {
    $('runs-list').replaceChildren();
    if (!items.length) { $('runs-list').textContent = '暂无可显示的运行记录。'; return; }
    for (const run of items) {
      const row = document.createElement('div'); row.className = 'run-item';
      const link = document.createElement('a');
      if (typeof run.html_url === 'string' && /^https:\/\/github\.com\/Rexmiao\/levyquant-digest\/actions\/runs\/\d+$/.test(run.html_url)) { link.href = run.html_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      link.textContent = `运行 #${run.id || '—'}`;
      const state = document.createElement('span'); state.textContent = run.conclusion || run.status || 'unknown'; row.append(link, state); $('runs-list').append(row);
    }
  }
  async function refreshAdmin() {
    const [status, list] = await Promise.all([api('/api/admin/status', {admin: true}), api('/api/admin/subscribers', {admin: true})]);
    $('admin-status').textContent = Array.isArray(status.missing) && status.missing.length ? `待配置：${status.missing.join('、')}` : '后台已连接。可管理订阅、预览和发送任务。';
    renderRuns(Array.isArray(status.runs) ? status.runs : []);
    renderSubscribers(Array.isArray(list.subscribers) ? list.subscribers : []);
  }
  async function pollPreview(attempt = 0) {
    try {
      const data = await api('/api/admin/preview', {admin: true});
      if (data.status === 'ready' && showPreview('private-preview', data.preview || data)) {
        $('private-preview-panel').hidden = false;
        $('private-preview-date').textContent = (data.preview || data).date || '';
        $('publish-button').disabled = false;
        $('generate-button').disabled = false;
        message('action-status', '私人预览已生成。确认后可发布到公开页面。');
      } else if (['failed', 'error'].includes(data.status)) { throw new Error('预览生成失败。请检查来源和模型配置。'); }
      else if (attempt < 180 && adminToken) { previewTimer = setTimeout(() => pollPreview(attempt + 1), 3000); }
      else { $('generate-button').disabled = false; message('action-status', '预览尚未完成，请稍后刷新。', true); }
    } catch (error) { if (error.stale) return; $('generate-button').disabled = false; message('action-status', error.message, true); }
  }
  function adminPage() {
    $('login-form').addEventListener('submit', async event => {
      event.preventDefault(); adminGeneration += 1; adminToken = $('admin-token').value.trim();
      message('login-status', '正在验证…');
      try { await refreshAdmin(); $('admin-token').value = ''; $('admin-login').hidden = true; $('admin-dashboard').hidden = false; message('login-status', ''); }
      catch (error) { if (error.stale) return; adminToken = ''; message('login-status', error.message, true); }
    });
    $('logout-button').addEventListener('click', logout);
    $('refresh-button').addEventListener('click', () => refreshAdmin().catch(error => message('action-status', error.message, true)));
    $('generate-button').addEventListener('click', async () => {
      $('generate-button').disabled = true; $('publish-button').disabled = true;
      message('action-status', '正在采集和整理，可能需要几分钟…');
      try { await api('/api/admin/preview', {method: 'POST', admin: true, body: {}}); pollPreview(); }
      catch (error) { $('generate-button').disabled = false; message('action-status', error.message, true); }
    });
    $('publish-button').addEventListener('click', async () => {
      $('publish-button').disabled = true;
      try { await api('/api/admin/publish', {method: 'POST', admin: true, body: {}}); message('action-status', '已发布，访客现在可以看到这份预览。'); }
      catch (error) { message('action-status', error.message, true); }
      finally { $('publish-button').disabled = false; }
    });
    $('send-button').addEventListener('click', async () => {
      $('send-button').disabled = true;
      try { await api('/api/admin/send', {method: 'POST', admin: true, body: {}}); message('action-status', '发送任务已提交。稍后刷新运行状态，核实实际投递结果。'); await refreshAdmin(); }
      catch (error) { message('action-status', error.message, true); }
      finally { $('send-button').disabled = false; }
    });
  }
  if (document.body.dataset.page === 'admin') adminPage(); else publicPage();
})();
