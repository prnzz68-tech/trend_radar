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
  lines.push('', 'Гипотеза для рекламы:',
    `Лидер по просмотрам набрал ${number.format(leader.views)}; ${comparison}. Лучший отклик в топ-3 у «${engaged.title.slice(0, 70)}».`,
    `Проверьте тему «${leader.title.slice(0, 90)}»: покажите результат ученика в первые секунды, затем фрагмент урока и приглашение на курс.`,
    `Второй вариант — короткий ответ преподавателя на вопрос по теме «${engaged.title.slice(0, 90)}».`,
    'Покажите оба варианта одной аудитории с равным бюджетом 3 дня. Сравните заявки и их стоимость.');
  return lines.join('\n').slice(0, 4000);
}

export function startTelegramBot({ token, chatId, hour, getSnapshot, getLastSentDate, markSentDate, reportError }) {
  if (!token) return;
  const expectedChat = String(chatId || '').trim();
  let offset;
  let sending = false;
  const api = async (method, payload = {}) => {
    const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(30000)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Error(`Telegram ${method}: ${result.description || response.status}`);
    return result.result;
  };
  const send = (target, text) => api('sendMessage', { chat_id: target, text });
  const sendDigest = async (target) => {
    const message = digestText(getSnapshot());
    await send(target, message || 'Пока нет реальных видео со ссылками. Обновите YouTube или добавьте ролики вручную.');
    return Boolean(message);
  };
  const scheduled = async () => {
    if (!expectedChat || sending) return;
    const { day, hour: currentHour } = dayAndHour(new Date());
    if (currentHour < hour || getLastSentDate() === day) return;
    if (!digestText(getSnapshot())) return;
    sending = true;
    try { await sendDigest(expectedChat); await markSentDate(day); }
    catch (error) { reportError(error); }
    finally { sending = false; }
  };
  const poll = async () => {
    try {
      await api('getMe');
      console.log('Telegram bot: connected');
    } catch (error) { reportError(error); return; }
    while (true) {
      try {
        const updates = await api('getUpdates', { offset, timeout: 20, allowed_updates: ['message'] });
        for (const update of updates) {
          offset = update.update_id + 1;
          const message = update.message;
          if (!message?.chat?.id || typeof message.text !== 'string') continue;
          const incomingChat = String(message.chat.id);
          const command = message.text.split(/\s+/)[0].split('@')[0].toLowerCase();
          if (!expectedChat) {
            if (command === '/start') await send(incomingChat, `Ваш Chat ID: ${incomingChat}\nДобавьте его как TELEGRAM_CHAT_ID в локальный .env и перезапустите сервис.`);
            continue;
          }
          if (incomingChat !== expectedChat) continue;
          if (command === '/start' || command === '/help') await send(incomingChat, 'Тренд радар подключён. /digest — подборка сейчас, /status — состояние источников. Ежедневная отправка выполняется, пока сервер запущен.');
          if (command === '/digest') await sendDigest(incomingChat);
          if (command === '/status') {
            const snapshot = getSnapshot();
            await send(incomingChat, `Видео в базе: ${snapshot.demo ? 0 : snapshot.count}\nYouTube: ${snapshot.hasYouTubeKey ? 'подключён' : 'нет ключа'}\nПоследнее обновление: ${snapshot.lastSync || 'ещё не было'}`);
          }
        }
      } catch (error) {
        reportError(error);
        await new Promise(resolve => setTimeout(resolve, 5000));
      }
    }
  };
  setInterval(scheduled, 60000).unref();
  scheduled();
  poll();
}
