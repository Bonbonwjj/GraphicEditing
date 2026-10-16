// Dependency-free state/handler regressions; browser layout is verified separately.
// Run: node tests/test_chat_frontend.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');

function environment() {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], {
    innerHTML: '', textContent: '', value: '', dataset: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    querySelectorAll() { return []; }, append() {}, setAttribute() {},
    scrollTo() {}, focus() {}, showModal() {}, close() {},
    requestSubmit() { return this.onsubmit({ preventDefault() {} }); },
  }]));
  const sandbox = {
    console, Set, Map, Date, JSON, URL, Promise, encodeURIComponent,
    localStorage: { getItem() { return 'dark'; }, setItem() {} },
    document: {
      getElementById(id) { assert(elements.has(id), 'Unknown DOM ID: ' + id); return elements.get(id); },
      documentElement: { dataset: {} }, querySelectorAll() { return []; }, addEventListener() {},
    },
    IntersectionObserver: class { observe() {} unobserve() {} },
    fetch() { throw Error('Unexpected network'); }, setInterval() {},
  };
  let source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
  const init = source.indexOf('(async()=>{try{if(window.syncTeamOnOpen)');
  assert(init > 0, 'Locate automatic page initialization');
  source = source.slice(0, init);
  source += '\nglobalThis.app = { state, chatContext, sessionMatches, renderDraft, renderChat, generateChat, syncChatContext, warningIds, storeSession, warningList, refreshProjectChats };';
  vm.runInNewContext(source, sandbox);
  const app = sandbox.app;
  app.state.project = 'project';
  app.state.chart = 'B';
  app.state.projects = [{ id: 'project', name: 'Project', charts: ['A', 'B'], chart_metadata: {
    A: { display_name: 'Reference' }, B: { display_name: 'Target' },
  } }];
  return { sandbox, app, elements };
}

function session(id = 'ses_b', chart = 'B') {
  return { id, status: 'open', charts: [{ chart_id: 'cht_' + chart.toLowerCase(), chart }],
    turns: [], drafts: [], active_drafts: { cht_b: 'dft_1' } };
}

async function ready(predicate) {
  for (let i = 0; i < 20 && !predicate(); i++) await Promise.resolve();
  assert(predicate(), 'Expected async operation to begin');
}

async function testTargetIsolation() {
  const { app, sandbox, elements } = environment();
  assert.equal(app.chatContext().charts.join(','), 'B');
  app.state.selectedCharts = new Set(['B', 'A']);
  assert.equal(app.chatContext().charts.join(','), 'A,B');
  app.state.selectedCharts.clear();
  const context = app.chatContext(), current = session();
  assert(app.sessionMatches(current, context));
  app.storeSession(context, current); app.state.chatKey = context.key;
  let release, request;
  sandbox.fetch = async (url, options) => {
    request = { url, body: JSON.parse(options.body) };
    return new Promise(resolve => { release = () => resolve({ ok: true, json: async () => ({
      ...current, turns: [{ id: 'trn_1', user_message: 'change B', results: [
        { chart: 'B', status: 'needs_clarification', question: 'B only question' },
      ] }],
    }) }); });
  };
  const work = app.generateChat({ user_message: 'change B' });
  await ready(() => release);
  assert(request.url.endsWith('/ses_b/turns'));
  elements.get('prompt').value = 'Unsent text for B';
  app.state.chart = 'A'; const next = app.chatContext();
  app.storeSession(next, session('ses_a', 'A')); app.syncChatContext();
  assert.equal(elements.get('prompt').value, 'Unsent text for B');
  release(); await work;
  assert.equal(app.state.chatKey, next.key);
  assert(elements.get('messages').innerHTML.includes('B only question'));
  assert.equal(app.state.chatSessions.get(context.key).turns.length, 1);
  assert.equal(app.state.chatBusy.size, 0);
  app.state.chart = 'B'; app.syncChatContext();
  assert.equal(elements.get('prompt').value, 'Unsent text for B');
}

function testCards() {
  const { app } = environment();
  const context = app.chatContext(), current = session();
  const draft = { id: 'dft_1', chart_id: 'cht_b', chart: 'B', display_name: 'Target',
    status: 'preview_ready', summary: '<unsafe>', code: { 'charts/B.py': 'print("x")' }, image_url: '/draft.png' };
  const card = app.renderDraft(draft, current, context);
  assert(card.includes('应用此版'));
  assert(card.includes('继续修改的起点'));
  assert(card.includes('&lt;unsafe&gt;'));
  assert(!card.includes('<unsafe>'));
  assert(!app.renderDraft(draft, { ...current, status: 'closed' }, context).includes('data-draft-action'));
  const diagnostic = { ...draft, status: 'needs_clarification', layout: { issues: [{ id: 'warn_1', message: 'tick overlap' }] } };
  assert(app.renderDraft(diagnostic, current, context).includes('仍按要求执行'));
  assert(!app.renderDraft({ ...diagnostic, status: 'validation_failed' }, current, context).includes('data-layout-override'));
  assert(!app.renderDraft({ ...diagnostic, layout: { issues: [{ message: 'no stable ID' }] } }, current, context).includes('data-layout-override'));
  assert.equal(app.warningList({ warnings: null }).length, 0);
  assert.equal(app.warningList({ warnings: 'one warning' }).length, 1);
  assert.equal(app.warningIds({ warnings: [{ id: 'not_a_layout_issue', message: 'Data warning' }] }).length, 0);
  const reviewed = app.renderDraft({ ...draft, layout: { status: 'pass', scope: 'text_spines_and_canvas', limitations: ['Custom artists need review <still>'] }, proposal: {
    interpreted_request: { operations: [{ source_quotes: ['Move legend'], target_element: 'legend', property: 'x', current_value: 1, desired_change: 0.9 }], preserve: [{ details: 'Keep data' }] },
    expected_effects: [{ observable_change: 'Legend moves left', review_required: 'Inspect figure' }],
    normalization_checks: { status: 'pass', visual_rules_verified: false, violations: [] },
  } }, current, context);
  assert(reviewed.includes('修改理解与检查结果'));
  assert(reviewed.includes('Move legend'));
  assert(reviewed.includes('Keep data'));
  assert(reviewed.includes('Legend moves left'));
  assert(reviewed.includes('检测范围内未发现布局冲突'));
  assert(reviewed.includes('Custom artists need review &lt;still&gt;'));
  assert(reviewed.includes('不代表所有视觉规则均已通过'));
  const normalized = app.renderDraft({ ...draft, normalization_report: {
    profile_version: '1.0', matched_template: 'heatmap', warnings: ['Runtime warning <not verified>'],
    font_substitutions: [{ text: 'Reaction time', requested_family: 'Font A', requested_weight: 800, selected_family: 'Font B', reason: 'Weight unavailable' }],
  } }, current, context);
  assert(normalized.includes('标准化运行报告'));
  assert(normalized.includes('模板：heatmap'));
  assert(normalized.includes('Runtime warning &lt;not verified&gt;'));
  assert(normalized.includes('要求字体：Font A'));
  assert(normalized.includes('实际选用：Font B'));
}

function testClarificationQuestion() {
  const { app, elements } = environment(), current = session(), context = app.chatContext();
  app.state.chatKey = context.key;
  current.turns = [{ user_message: 'Change error bars', results: [
    { chart: 'B', status: 'needs_clarification', reason: 'Error meaning is unspecified', question: 'Use SD or SEM?' },
  ] }];
  app.storeSession(context, current); app.renderChat();
  let html = elements.get('messages').innerHTML;
  assert(html.includes('Error meaning is unspecified'));
  assert(html.includes('Use SD or SEM?'));
  current.turns[0].results[0].reason = 'Use SD or SEM?';
  app.renderChat(); html = elements.get('messages').innerHTML;
  assert.equal(html.split('Use SD or SEM?').length - 1, 1);
}

async function testFinalizeRefresh() {
  const { app, sandbox, elements } = environment(), current = session();
  const context = app.chatContext(); app.state.chatKey = context.key;
  app.storeSession(context, current);
  const other = { project: 'project', charts: ['A'], key: JSON.stringify(['project', ['A']]) };
  app.storeSession(other, session('ses_a', 'A'));
  sandbox.fetch = async url => {
    assert(url.endsWith('/chat/history') || url.endsWith('/chat/sessions?charts=B'));
    return { ok: true, json: async () => ({ sessions: [{ ...current, status: 'closed' }] }) };
  };
  await app.refreshProjectChats('project');
  assert.equal(app.state.chatSessions.get(context.key).status, 'closed');
  assert(!app.state.chatSessions.has(other.key));
  assert(!app.state.chatSessionLists.has(other.key));
  assert(elements.get('messages').innerHTML.includes('当前目标会话已结束'));
}

async function testSubmitHandler() {
  const { app, sandbox, elements } = environment();
  assert.match(html, /<form id="chatForm">[\s\S]*?<button id="sendChat"[^>]*type="submit"[\s\S]*?<\/form>/);
  const context = app.chatContext(); app.state.chatKey = context.key;
  app.state.chatSessionLists.set(context.key, []);
  const calls = [], current = session();
  sandbox.fetch = async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return { ok: true, json: async () => calls.length === 1 ? current : ({ ...current,
      turns: [{ user_message: 'Move legend', results: [{ chart: 'B', status: 'needs_clarification', question: 'Which legend?' }] }],
    }) };
  };
  elements.get('prompt').value = 'Move legend';
  let prevented = false;
  assert.equal(typeof elements.get('chatForm').onsubmit, 'function');
  await elements.get('chatForm').onsubmit({ preventDefault() { prevented = true; } });
  assert(prevented);
  assert.equal(elements.get('prompt').value, '');
  assert.equal(calls.length, 2);
  assert(calls[0].url.endsWith('/chat/sessions'));
  assert(calls[1].url.endsWith('/ses_b/turns'));
  assert.equal(calls[1].body.user_message, 'Move legend');
  assert(elements.get('messages').innerHTML.includes('Which legend?'));
}

(async () => {
  testCards();
  testClarificationQuestion();
  await testTargetIsolation();
  await testSubmitHandler();
  await testFinalizeRefresh();
  console.log('PASS: cards, check limitations, closed sessions, scoped layout warnings, target isolation, compose isolation, submit handler, session creation and finalize refresh.');
})().catch(error => { console.error(error); process.exitCode = 1; });
