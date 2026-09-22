import assert from 'node:assert/strict';
import { startTelegramBot } from './telegram.mjs';

const subscribers = new Set();
const replies = [];
let updatesServed = false;
globalThis.fetch = async (url, options) => {
  const method = new URL(url).pathname.split('/').pop();
  const payload = JSON.parse(options.body);
  if (method === 'getMe') return { ok: true, json: async () => ({ ok: true, result: {} }) };
  if (method === 'getUpdates') {
    if (updatesServed) return new Promise(() => {});
    updatesServed = true;
    return { ok: true, json: async () => ({ ok: true, result: [
      { update_id: 1, message: { chat: { id: 101, type: 'private' }, text: '/start' } },
      { update_id: 2, message: { chat: { id: 202, type: 'private' }, text: '/start' } },
      { update_id: 3, message: { chat: { id: 202, type: 'private' }, text: '/global' } },
      { update_id: 4, message: { chat: { id: 101, type: 'private' }, text: '/stop' } }
    ] }) };
  }
  if (method === 'sendMessage') {
    replies.push(payload);
    return { ok: true, json: async () => ({ ok: true, result: {} }) };
  }
  throw Error(`Unexpected method: ${method}`);
};

startTelegramBot({
  token: 'test', hour: 23,
  getSnapshot: () => ({ demo: true, top: [], globalTop: [], settings: { query: 'test' } }),
  getSubscribers: () => [...subscribers],
  addSubscriber: async chat => subscribers.add(chat),
  removeSubscriber: async chat => subscribers.delete(chat),
  getLastSentDate: () => null,
  markSentDate: async () => {},
  reportError: error => { throw error; }
});

for (let attempt = 0; replies.length < 4 && attempt < 70; attempt++) await new Promise(resolve => setTimeout(resolve, 100));
assert.equal(replies.length, 4);
assert.deepEqual([...subscribers], ['202']);
assert.equal(replies[0].chat_id, '101');
assert.equal(replies[1].chat_id, '202');
assert.equal(replies[2].chat_id, '202');
assert.match(replies[2].text, /Глобальных видео/);
assert.equal(replies[3].chat_id, '101');
console.log('Multiple chats can use commands and manage subscriptions');
