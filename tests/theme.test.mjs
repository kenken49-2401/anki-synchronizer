import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../web/theme.js', import.meta.url), 'utf8');
function setup(saved = null, blocked = false) {
  const storage = new Map([['study-atlas-prototype-v1', '{"studies":["preserve"]}']]);
  if (saved !== null) storage.set('atlas.theme.v1', saved);
  const listeners = {}, select = {value: '', matches: () => true}, status = {};
  const document = {
    documentElement: {dataset: {}},
    querySelector: () => null,
    querySelectorAll: (selector) => selector === '[data-theme-select]' ? [select] : [status],
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
  const window = {
    addEventListener: (name, fn) => { listeners[name] = fn; },
    dispatchEvent: () => {},
  };
  const localStorage = {
    getItem: (key) => { if (blocked) throw Error('blocked'); return storage.get(key); },
    setItem: (key, value) => { if (blocked) throw Error('blocked'); storage.set(key, value); },
  };
  vm.runInNewContext(source, {document, window, localStorage, Event});
  const change = (value) => { select.value = value; listeners.change({target: select}); };
  return {document, storage, select, status, listeners, change};
}
test('restores a valid preference and defaults unknown values to light', () => {
  assert.equal(setup('dark').document.documentElement.dataset.theme, 'dark');
  assert.equal(setup('invalid').document.documentElement.dataset.theme, 'light');
});
test('theme changes preserve study data and only save the appearance key', () => {
  const app = setup();
  const original = app.storage.get('study-atlas-prototype-v1');
  app.change('dark');
  assert.equal(app.select.value, 'dark');
  assert.equal(app.storage.get('atlas.theme.v1'), 'dark');
  assert.equal(app.storage.get('study-atlas-prototype-v1'), original);
  app.change('unexpected');
  assert.equal(app.document.documentElement.dataset.theme, 'dark');
});
test('blocked storage still permits switching and explains persistence failure', () => {
  const app = setup(null, true);
  app.change('dark');
  assert.equal(app.document.documentElement.dataset.theme, 'dark');
  assert.match(app.status.textContent, /保存できない/);
});
test('other tabs update the theme and unrelated storage events do nothing', () => {
  const app = setup();
  app.listeners.storage({key: 'atlas.theme.v1', newValue: 'dark'});
  assert.equal(app.select.value, 'dark');
  app.listeners.storage({key: 'study-atlas-prototype-v1', newValue: '{}'});
  assert.equal(app.select.value, 'dark');
  app.listeners.storage({key: null, newValue: null});
  assert.equal(app.select.value, 'light');
});
