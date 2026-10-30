// Real React/Ant Design interactions; API calls are isolated from user accounts.
// Requires the frontend dependencies and jsdom on NODE_PATH.
const { test, afterEach, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'SVGElement', 'Element', 'ShadowRoot', 'MutationObserver', 'Event', 'MouseEvent']) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true });
}
globalThis.getComputedStyle = (element) => dom.window.getComputedStyle(element);
globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
globalThis.cancelAnimationFrame = clearTimeout;
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const { MemoryRouter } = require('react-router-dom');
const { ConfigProvider } = require('antd');
const frontendRoot = process.env.DRAFT_FRONTEND_ROOT || path.resolve(__dirname, '../../frontend');
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'account-notes-'));
const outputFile = path.join(outputDir, 'page.cjs');
const ready = require('esbuild').build({
  entryPoints: [path.join(frontendRoot, 'src/pages/platforms/xhs/account-notes-page.tsx')],
  outfile: outputFile, bundle: true, platform: 'node', format: 'cjs', packages: 'external', jsx: 'automatic',
  plugins: [{ name: 'isolated-api', setup(build) {
    build.onResolve({ filter: /^(react|antd|@)/ }, ({ path }) => ({ path, external: true }));
    build.onResolve({ filter: /\/lib\/api$/ }, () => ({ path: 'api', namespace: 'mock' }));
    build.onResolve({ filter: /\/components\/layout\/app-shell$/ }, () => ({ path: 'header', namespace: 'mock' }));
    build.onLoad({ filter: /.*/, namespace: 'mock' }, ({ path }) => ({ loader: 'jsx', contents: path === 'api'
      ? ['fetchAccountNotes', 'fetchNoteAccounts', 'syncAccountNotes'].map((name) => `export const ${name} = (...args) => globalThis.notesTestApi.${name}(...args);`).join('\n')
      : 'import React from "react"; export function PageHeader({title,action}) {return <header><h1>{title}</h1>{action}</header>;}',
    }));
  } }],
});
let root;
let container;
async function settle(action = () => {}) {
  await act(async () => { await action(); await new Promise((resolve) => setTimeout(resolve, 30)); });
}
function account(id, nickname) {
  return { account_id: id, nickname, avatar_url: '', account_types: ['creator', 'pc'], login_status: 'active',
    total_notes: 1, current_notes: 1, missing_notes: 0, totals: { views: null, likes: 0, collects: 0, comments: 0, shares: 0 },
    metric_note_counts: { views: 0, likes: 1, collects: 1, comments: 1, shares: 1 }, sync_status: 'success', sync_source: 'creator',
    sync_message: '同步完成', synced_at: '2026-10-30T15:12:00', last_attempt_at: '2026-10-30T15:12:00' };
}
function result(owner, title = 'Fixture note') {
  return { account: owner, total: 1, page: 1, page_size: 20, items: [{ id: owner.account_id, title, note_id: `fixture-${owner.account_id}`,
    note_url: 'https://www.xiaohongshu.com/explore/fixture', cover_url: '', media_type: 'image', platform_status: '',
    published_at: null, source: 'creator', synced_at: '2026-10-30T15:12:00', in_latest_sync: true,
    views: null, likes: 0, collects: 0, comments: 0, shares: 0 }] };
}
async function mount(accounts, overrides = {}) {
  await ready;
  globalThis.notesTestApi = { fetchNoteAccounts: async () => ({ items: accounts }),
    fetchAccountNotes: async (id) => result(accounts.find((item) => item.account_id === id)), ...overrides };
  container = document.createElement('main');
  document.body.append(container);
  root = createRoot(container);
  const { XhsAccountNotesPage } = require(outputFile);
  await settle(() => root.render(React.createElement(ConfigProvider, { theme: { token: { motion: false } } },
    React.createElement(MemoryRouter, null, React.createElement(XhsAccountNotesPage)))));
  await settle();
}
function button(text) {
  const matches = [...document.querySelectorAll('button')].filter((item) => item.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
  assert.equal(matches.length, 1, text);
  return matches[0];
}
afterEach(async () => { if (root) await settle(() => root.unmount()); root = undefined; container?.remove(); });
after(() => { dom.window.close(); fs.rmSync(outputDir, { recursive: true, force: true }); });

test('an empty account list offers binding and disables sync-all', async () => {
  await mount([]);
  assert.equal(button('同步全部账号').disabled, true);
  assert.equal(document.querySelector('a[href="/platforms/xhs/accounts"]').textContent, '前往账号矩阵');
});

test('missing metrics remain unavailable while a real zero stays zero', async () => {
  await mount([account(1, 'Account A')]);
  const row = document.querySelector('.ant-table-row');
  assert.ok(row);
  assert.equal(row.children[2].textContent, '—');
  assert.equal(row.children[3].textContent, '0');
  assert.ok(document.querySelector('a[href="https://www.xiaohongshu.com/explore/fixture"]'));
});

test('switching accounts rejects a stale response from the previous account', async () => {
  let finishOld;
  const accounts = [account(1, 'Account A'), account(2, 'Account B')];
  await mount(accounts, { fetchAccountNotes: async (id) => id === 1
    ? new Promise((resolve) => { finishOld = resolve; }) : result(accounts[1], 'B note') });
  await settle(() => document.querySelector('[aria-label="查看Account B的笔记"]').click());
  await settle(() => finishOld(result(accounts[0], 'A stale note')));
  assert.ok(document.querySelector('.ant-table-row').textContent.includes('B note'));
  assert.ok(!document.querySelector('.ant-table-row').textContent.includes('A stale note'));
});

test('sync-all processes the remaining account after one fails and reports partial success', async () => {
  const accounts = [account(1, 'Account A'), account(2, 'Account B')];
  const calls = [];
  await mount(accounts, { syncAccountNotes: async (id) => {
    calls.push(id);
    if (id === 1) throw { response: { data: { detail: '登录失效，历史数据保留' } } };
    return { synced_count: 1, account: accounts[1] };
  } });
  await settle(() => button('同步全部账号').click());
  await settle();
  assert.deepEqual(calls, [1, 2]);
  assert.ok(document.querySelector('.ant-alert-error').textContent.includes('Account A'));
  assert.ok(document.querySelector('.ant-alert-success').textContent.includes('1 个账号成功'));
});

test('search passes the selected account and query to the list endpoint', async () => {
  const owner = account(7, 'Search account');
  const calls = [];
  await mount([owner], { fetchAccountNotes: async (id, query) => { calls.push([id, query]); return result(owner); } });
  const input = document.querySelector('input[aria-label="搜索笔记标题"]');
  await settle(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, '100% design');
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await settle(() => input.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true })));
  assert.equal(calls.at(-1)[0], 7);
  assert.equal(calls.at(-1)[1].q, '100% design');
  assert.equal(calls.at(-1)[1].page, 1);
});
