// Component integration checks with real React and Ant Design, isolated API calls.
// Run with frontend dependencies plus jsdom on NODE_PATH, and
// DRAFT_FRONTEND_ROOT pointing to frontend/. No service or real account is used.
const { test, after, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'SVGElement', 'Element', 'ShadowRoot', 'MutationObserver', 'File', 'Blob', 'Event', 'MouseEvent']) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true });
}
globalThis.getComputedStyle = (element) => dom.window.getComputedStyle(element);
globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
globalThis.cancelAnimationFrame = clearTimeout;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const { MemoryRouter } = require('react-router-dom');
const { ConfigProvider, message } = require('antd');
message.config({ duration: 0 });
const frontendRoot = process.env.DRAFT_FRONTEND_ROOT || path.resolve(__dirname, '../../frontend');
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'draft-workbench-'));
const outputFile = path.join(outputDir, 'page.cjs');
const apiNames = [
  'addDraftAsset', 'createDraftFromNote', 'deleteDraft', 'deleteDraftAsset', 'fetchDraftAssets',
  'fetchDrafts', 'fetchGeneratedImageAssets', 'fetchSavedNote', 'fetchUserImages',
  'generateImageWithAi', 'generateNoteWithAi', 'generateTagOptions', 'generateTitleOptions',
  'reorderDraftAssets', 'rewriteDraftWithAi', 'sendDraftToPublish', 'updateDraft',
  'updateDraftAsset', 'uploadAssetFile',
];
const ready = require('esbuild').build({
  entryPoints: [path.join(frontendRoot, 'src/pages/platforms/xhs/rewrite-page.tsx')],
  outfile: outputFile,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
  nodePaths: [path.join(frontendRoot, 'node_modules')],
  jsx: 'automatic',
  plugins: [{
    name: 'isolated-page-dependencies',
    setup(build) {
      build.onResolve({ filter: /^(react|antd|@)/ }, ({ path: name }) => ({ path: name, external: true }));
      build.onResolve({ filter: /\/lib\/api$/ }, () => ({ path: 'api', namespace: 'mock' }));
      build.onResolve({ filter: /\/components\/layout\/app-shell$/ }, () => ({ path: 'header', namespace: 'mock' }));
      build.onLoad({ filter: /.*/, namespace: 'mock' }, ({ path: name }) => ({
        loader: 'jsx',
        contents: name === 'api'
          ? apiNames.map((name) => `export const ${name} = (...args) => globalThis.draftTestApi.${name}(...args);`).join('\n')
          : 'import React from "react"; export function PageHeader({ title, action }) { return <header><h1>{title}</h1>{action}</header>; }',
      }));
    },
  }],
});

let root;
let mountedContainer;
function draft(id = 1, overrides = {}) {
  return { id, platform: 'xhs', title: '', body: '', tags: [], source_note_id: null, created_at: '2026-10-29T12:00:00', ...overrides };
}
async function settle(action = () => {}) {
  await act(async () => { await action(); await new Promise((resolve) => setTimeout(resolve, 20)); });
}
async function mount(drafts = [], overrides = {}) {
  await ready;
  globalThis.draftTestApi = {
    fetchDrafts: async () => ({ items: drafts }),
    fetchDraftAssets: async () => ({ items: [] }),
    fetchUserImages: async () => ({ items: [] }),
    fetchGeneratedImageAssets: async () => ({ items: [] }),
    ...overrides,
  };
  const container = document.createElement('main');
  mountedContainer = container;
  document.body.append(container);
  root = createRoot(container);
  const { XhsDraftsPage } = require(outputFile);
  await settle(() => root.render(React.createElement(ConfigProvider, { theme: { token: { motion: false } } },
    React.createElement(MemoryRouter, null, React.createElement(XhsDraftsPage)))));
}
function button(text, container = document) {
  const matches = [...container.querySelectorAll('button')].filter((element) => element.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
  assert.equal(matches.length, 1, `Expected one button: ${text}`);
  return matches[0];
}
async function fill(placeholder, value) {
  const input = document.querySelector(`[placeholder="${placeholder}"]`);
  assert.ok(input, placeholder);
  const prototype = input.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  await settle(() => {
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, value);
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}
afterEach(async () => {
  await settle(() => { if (root) root.unmount(); message.destroy(); });
  root = undefined;
  mountedContainer?.remove();
  mountedContainer = undefined;
});
after(() => { dom.window.close(); fs.rmSync(outputDir, { recursive: true, force: true }); });

test('create a blank draft without a model or source note, then upload its first image', async () => {
  let created;
  let added;
  await mount([], {
    createDraftFromNote: async (payload) => { created = payload; return draft(); },
    uploadAssetFile: async (file) => {
      assert.equal(file.name, 'first.png');
      return { asset_type: 'image', download_url: '/api/files/media/first.png', file_name: 'first.png' };
    },
    addDraftAsset: async (id, payload) => { added = { id, ...payload }; return { id: 10, draft_id: id, sort_order: 0, ...payload }; },
  });
  await settle(() => button('新建空白草稿', document.querySelector('header')).click());
  assert.deepEqual(created, { platform: 'xhs', title: '', body: '' });
  assert.equal(document.querySelector('[placeholder="输入标题，也可以使用 AI 润色"]').disabled, false);
  await settle(() => button('上传图片或视频').click());
  const input = document.querySelector('input[type="file"]');
  assert.ok(input, 'upload is reachable with zero media and no source note');
  await settle(() => {
    Object.defineProperty(input, 'files', { value: [new File(['image'], 'first.png', { type: 'image/png' })] });
    input.dispatchEvent(new window.Event('change', { bubbles: true }));
  });
  assert.deepEqual(added, { id: 1, asset_type: 'image', url: '/api/files/media/first.png', local_path: 'first.png' });
  assert.ok(document.querySelector('img[src="/api/files/media/first.png"]'));
});

test('AI generation opens the generated draft editor and its independent media controls', async () => {
  await mount([], { generateNoteWithAi: async () => draft(2, { title: '生成标题', body: '生成正文' }) });
  const option = [...document.querySelectorAll('label')].find((item) => item.textContent.includes('生成新草稿'));
  await settle(() => option.click());
  await fill('例如：通勤低卡早餐怎么搭配', '海报设计');
  await settle(() => button('生成草稿').click());
  assert.equal(document.querySelector('[placeholder="输入标题，也可以使用 AI 润色"]').value, '生成标题');
  assert.equal(document.querySelector('[placeholder="在这里撰写正文，也可以使用 AI 改写。"]').value, '生成正文');
  assert.ok(button('上传图片或视频'));
});

test('sending a draft saves edited title, body and an uncommitted topic before creating the publish job', async () => {
  const calls = [];
  await mount([draft()], {
    updateDraft: async (id, payload) => { calls.push(['save', id, payload]); return draft(id, payload); },
    sendDraftToPublish: async (id) => { calls.push(['send', id]); return { id: 7 }; },
  });
  await fill('输入标题，也可以使用 AI 润色', '手写标题');
  await fill('在这里撰写正文，也可以使用 AI 改写。', '手写正文');
  const addTag = [...document.querySelectorAll('.ant-tag')].find((item) => item.textContent.includes('添加标签'));
  await settle(() => addTag.click());
  await fill('输入标签', '海报设计');
  await settle(() => button('送入发布中心').click());
  assert.deepEqual(calls, [
    ['save', 1, { title: '手写标题', body: '手写正文', tags: [{ id: '', name: '海报设计' }] }],
    ['send', 1],
  ]);
});

test('failed save stops submission and keeps the edited content', async () => {
  await mount([draft()], {
    updateDraft: async () => { throw new Error('save failed'); },
    sendDraftToPublish: async () => { assert.fail('must not submit after failed save'); },
  });
  await fill('输入标题，也可以使用 AI 润色', '待保存标题');
  await settle(() => button('送入发布中心').click());
  assert.equal(document.querySelector('[placeholder="输入标题，也可以使用 AI 润色"]').value, '待保存标题');
  assert.ok(document.querySelector('.ant-alert-error'));
});

test('an upload stays attached to its original draft when another draft is selected', async () => {
  let finishUpload;
  const upload = new Promise((resolve) => { finishUpload = resolve; });
  let attachedDraft;
  await mount([draft(1, { title: '第一份' }), draft(2, { title: '第二份' })], {
    uploadAssetFile: async () => upload,
    addDraftAsset: async (id, payload) => { attachedDraft = id; return { id: 11, draft_id: id, ...payload }; },
  });
  await settle(() => button('上传图片或视频').click());
  const input = document.querySelector('input[type="file"]');
  await settle(() => {
    Object.defineProperty(input, 'files', { value: [new File(['image'], 'slow.png', { type: 'image/png' })] });
    input.dispatchEvent(new window.Event('change', { bubbles: true }));
  });
  assert.equal(button('送入发布中心').disabled, true);
  const second = [...document.querySelectorAll('.ant-list-item')].find((item) => item.textContent.includes('第二份'));
  await settle(() => second.click());
  await settle(() => finishUpload({ asset_type: 'image', download_url: '/api/files/media/slow.png', file_name: 'slow.png' }));
  assert.equal(attachedDraft, 1);
  assert.equal(document.querySelector('[placeholder="输入标题，也可以使用 AI 润色"]').value, '第二份');
  assert.equal(document.querySelector('img[src="/api/files/media/slow.png"]'), null);
});
