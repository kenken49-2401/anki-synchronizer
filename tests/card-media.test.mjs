import test from 'node:test';
import assert from 'node:assert/strict';
import {observeCardMedia} from '../web/card-media.mjs';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const image = id => ({dataset: {mediaId: id}, isConnected: true});
const card = (...images) => ({isConnected: true, querySelectorAll: () => images});

test('nearby cards load in display order, question before hidden answer', async () => {
  const first = [image('question-1'), image('answer-1')];
  const second = [image('question-2'), image('answer-2')];
  const cards = [card(...first), card(...second)];
  let callback;
  class Observer {
    constructor(cb) { callback = cb; }
    observe() {}
    disconnect() {}
  }
  const calls = [];
  const stop = observeCardMedia({querySelectorAll: () => cards}, {
    async loadImage(id) { calls.push(id); return 'blob:' + id; },
  }, () => true, Observer);
  callback([{target: cards[1], isIntersecting: true}, {target: cards[0], isIntersecting: true}]);
  await tick();
  assert.deepEqual(calls, ['question-1', 'answer-1', 'question-2', 'answer-2']);
  assert.equal(first[1].src, 'blob:answer-1');
  stop();
});

test('stopping after a view change prevents stale work and DOM updates', async () => {
  const images = [image('question'), image('answer')];
  let resolve;
  const calls = [];
  const stop = observeCardMedia({querySelectorAll: () => [card(...images)]}, {
    loadImage(id) { calls.push(id); return new Promise(done => { resolve = done; }); },
  }, () => true, null);
  stop();
  resolve('blob:question');
  await tick();
  assert.deepEqual(calls, ['question']);
  assert.equal(images[0].src, undefined);
});
