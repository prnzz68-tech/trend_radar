const number = new Intl.NumberFormat('ru-RU');

export function dayAndHour(date, timeZone = 'Europe/Moscow') {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23'
  }).formatToParts(date).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}

export function digestText(snapshot) {
  if (snapshot.demo || !snapshot.top?.length) return null;
  const top = snapshot.top.filter(item => item.url?.startsWith('https://')).slice(0, 3);
  if (!top.length) return null;
  const lines = [`Тренд радар · ${snapshot.settings.query}`, '', 'Топ видео сегодня:'];
  for (const [index, item] of top.entries()) {
    const reactions = ((item.likes || 0) + (item.comments || 0)) / Math.max(1, item.views);
    lines.push('', `${index + 1}. ${item.platform} · ${item.title.slice(0, 120)}`,
      `${number.format(item.views)} просмотров · ${(reactions * 100).toFixed(1).replace('.', ',')}% реакций`, item.url);
  }
  const leader = [...top].sort((a, b) => b.views - a.views)[0];
  const engaged = [...top].sort((a, b) => ((b.likes || 0) + (b.comments || 0)) / Math.max(1, b.views) - ((a.likes || 0) + (a.comments || 0)) / Math.max(1, a.views))[0];
  const cohort = (snapshot.items || top).filter(item => item.source !== 'demo');
  const views = cohort.map(item => item.views).sort((a, b) => a - b);
  const midpoint = Math.floor(views.length / 2);
  const medianViews = views.length % 2 ? views[midpoint] : (views[midpoint - 1] + views[midpoint]) / 2;
  const comparison = medianViews ? `${(leader.views / medianViews).toFixed(1).replace('.', ',')} раза от медианы ${cohort.length} видео` : `медиана ${cohort.length} видео равна нулю`;
  const firstVariant = /егэ/i.test(leader.title)
    ? `Проверьте тему «${leader.title.slice(0, 90)}»: покажите ошибку в задании ЕГЭ, её решение и предложите диагностику знаний или пробный урок курса.`
    : `Проверьте тему «${leader.title.slice(0, 90)}»: покажите результат ученика в первые секунды, затем фрагмент урока и приглашение на курс.`;
  const secondVariant = /егэ/i.test(engaged.title)
    ? `Второй вариант — ответ преподавателя на вопрос по заданию из ролика «${engaged.title.slice(0, 90)}» и приглашение на курс подготовки.`
    : `Второй вариант — короткий ответ преподавателя на вопрос по теме «${engaged.title.slice(0, 90)}».`;
  lines.push('', 'Гипотеза для рекламы:',
    `Лидер по просмотрам набрал ${number.format(leader.views)}; ${comparison}. Лучший отклик в топ-3 у «${engaged.title.slice(0, 70)}».`,
    firstVariant, secondVariant,
    'Покажите оба варианта одной аудитории с равным бюджетом 3 дня. Сравните заявки и их стоимость.');
  return lines.join('\n').slice(0, 4000);
}

export function globalText(snapshot) {
  const top = snapshot.globalTop || [];
  if (!top.length) return 'Глобальных видео пока нет. Обновите данные в панели.';
  return [
    'Глобальные тренды · топ-3 по просмотрам',
    'Короткие YouTube видео за 7 дней без тематического фильтра; ручные сигналы других платформ учитываются, если добавлены.',
    ...top.flatMap((item, index) => ['', `${index+1}. ${item.platform} · ${item.title.slice(0,120)}`, `${number.format(item.views)} просмотров`, item.url]),
    '', 'Это рейтинг по просмотрам, а не рекомендация запускать рекламу по любой из этих тем.'
  ].join('\n').slice(0,4000);
}

export function startTelegramBot({ token, hour, getSnapshot, getSubscribers, addSubscriber, removeSubscriber, getLastSentDate, markSentDate, reportError }) {
  if (!token) return;
  let offset;
  let sending = false;
  let nextSendAt = 0;
  let telegramBlockedUntil = 0;
  let sendQueue = Promise.resolve();
  const commandCooldowns = new Map();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const api = async (method, payload = {}) => {
    await pause(Math.max(0, telegramBlockedUntil - Date.now()));
    if (method === 'sendMessage') {
      const queued = sendQueue.then(async () => {
        await pause(Math.max(0, nextSendAt - Date.now()));
        nextSendAt = Date.now() + 1000;
      });
      sendQueue = queued.catch(() => {});
      await queued;
    }
    const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(30000)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      const error = Error(`Telegram ${method}: ${result.description || response.status}`);
      error.retryAfter = Number(result.parameters?.retry_after) || Number(response.headers.get('retry-after')) || 0;
      error.status = response.status;
      if (error.retryAfter) telegramBlockedUntil = Math.max(telegramBlockedUntil, Date.now() + error.retryAfter * 1000);
      throw error;
    }
    return result.result;
  };
  const send = (target, text) => api('sendMessage', { chat_id: target, text });
  const sendDigest = async (target) => {
    const message = digestText(getSnapshot());
    await send(target, message || 'Пока нет реальных видео со ссылками. Обновите YouTube или добавьте ролики вручную.');
    return Boolean(message);
  };
  const scheduled = async () => {
    if (sending) return;
    const { day, hour: currentHour } = dayAndHour(new Date());
    if (currentHour < hour) return;
    if (!digestText(getSnapshot())) return;
    sending = true;
    try {
      for (const chat of getSubscribers()) {
        if (getLastSentDate(chat) === day) continue;
        try { await sendDigest(chat); await markSentDate(chat, day); }
        catch (error) {
          reportError(error);
          if (error.status === 403 || error.status === 400) await removeSubscriber(chat);
        }
      }
    } finally { sending = false; }
  };
  const poll = async () => {
    let backoffMs = 5000;
    while (true) {
      try { await api('getMe'); console.log('Telegram bot: connected'); break; }
      catch (error) {
        reportError(error);
        if (error.status === 401 || error.status === 404) return;
        await pause(error.retryAfter ? error.retryAfter * 1000 : backoffMs);
        backoffMs = Math.min(backoffMs * 2, 300000);
      }
    }
    backoffMs = 5000;
    while (true) {
      try {
        const updates = await api('getUpdates', { offset, timeout: 20, allowed_updates: ['message'] });
        backoffMs = 5000;
        for (const update of updates) {
          offset = update.update_id + 1;
          const message = update.message;
          if (!message?.chat?.id || typeof message.text !== 'string') continue;
          const incomingChat = String(message.chat.id);
          const command = message.text.split(/\s+/)[0].split('@')[0].toLowerCase();
          if (['/digest', '/global', '/status', '/start', '/help', '/stop'].includes(command)) {
            const key = `${incomingChat}:${command}`;
            if (Date.now() - (commandCooldowns.get(key) || 0) < 30000) continue;
            commandCooldowns.set(key, Date.now());
          }
          if (command === '/start') {
            if (message.chat.type === 'private') await addSubscriber(incomingChat);
            await send(incomingChat, `Тренд радар подключён.${message.chat.type === 'private' ? ' Ежедневная подборка включена.' : ''} /digest — онлайн-обучение и ЕГЭ, /global — общие тренды по просмотрам, /status — состояние источников, /stop — отключить ежедневную подборку.`);
          }
          if (command === '/help') await send(incomingChat, '/start — включить ежедневную подборку; /digest — темы онлайн-обучения и ЕГЭ; /global — глобальные тренды; /status — состояние источников; /stop — отключить ежедневную подборку.');
          if (command === '/stop') {
            await removeSubscriber(incomingChat);
            await send(incomingChat, 'Ежедневная подборка отключена. Команды /digest и /global по-прежнему доступны. Для подписки отправьте /start.');
          }
          if (command === '/digest') await sendDigest(incomingChat);
          if (command === '/global') await send(incomingChat, globalText(getSnapshot()));
          if (command === '/status') {
            const snapshot = getSnapshot();
            await send(incomingChat, `Видео по темам: ${snapshot.demo ? 0 : snapshot.count}\nГлобальные сигналы: ${snapshot.globalCount}\nYouTube: ${snapshot.hasYouTubeKey ? 'подключён' : 'нет ключа'}\nТемы обновлены: ${snapshot.lastSync || 'ещё не было'}\nГлобально обновлено: ${snapshot.globalLastSync || 'ещё не было'}`);
          }
        }
      } catch (error) {
        reportError(error);
        await pause(error.retryAfter ? error.retryAfter * 1000 : backoffMs + Math.random() * 1000);
        backoffMs = Math.min(backoffMs * 2, 300000);
      }
    }
  };
  setInterval(scheduled, 60000).unref();
  scheduled();
  poll();
}
