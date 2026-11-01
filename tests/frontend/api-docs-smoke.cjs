// Run with the root npm dependencies on NODE_PATH. Uses no external network.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('jsdom');

test('the locally bundled Swagger UI renders documentation and a password authorization dialog', async () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="swagger-ui"></div></body></html>', {
    url: 'http://localhost:18081/api/docs', runScripts: 'outside-only', pretendToBeVisual: true,
    virtualConsole: new VirtualConsole(),
  });
  try {
    const window = dom.window;
    window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
    let networkRequests = 0;
    window.fetch = async () => { networkRequests++; throw new Error('Unexpected network access'); };
    window.eval(fs.readFileSync(require.resolve('swagger-ui-dist/swagger-ui-bundle.js'), 'utf8'));
    window.SwaggerUIBundle({
      dom_id: '#swagger-ui', validatorUrl: null, persistAuthorization: false,
      presets: [window.SwaggerUIBundle.presets.apis, window.SwaggerUIBundle.SwaggerUIStandalonePreset],
      spec: {
        openapi: '3.1.0', info: { title: 'Fixture API documentation', version: '1.0' },
        components: { securitySchemes: { PlatformLogin: { type: 'oauth2', flows: { password: { tokenUrl: '/api/auth/token', scopes: {} } } } } },
        paths: { '/api/auth/me': { get: { security: [{ PlatformLogin: [] }], responses: { 200: { description: 'User profile' } } } } },
      },
    });
    for (let attempt = 0; attempt < 40 && !window.document.querySelector('button.authorize'); attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    assert.ok(window.document.body.textContent.includes('Fixture API documentation'));
    const authorize = window.document.querySelector('button.authorize');
    assert.ok(authorize, 'Authorize button is available');
    authorize.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    assert.ok(window.document.querySelector('input[type="password"]'), 'Password authorization form is usable');
    assert.equal(networkRequests, 0);
  } finally {
    dom.window.close();
  }
});
