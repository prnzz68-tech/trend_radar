const $ = (s) => document.querySelector(s);
const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1, notation: 'compact' });
const num = (n) => n == null ? '—' : fmt.format(n);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const percent = (x) => `${(x * 100).toFixed(1).replace('.', ',')}%`;
const rate = (x) => ((x.likes || 0) + (x.comments || 0)) / Math.max(1, x.views);
let data, filter = 'all', admin = { enabled: false, loggedIn: true, csrf: '' };

function notice(message, kind='info') {
  const el = $('#notice'); el.textContent=message; el.classList.add('show');
  el.style.background = kind==='error' ? '#382727' : '#253024';
  el.style.borderColor = kind==='error' ? '#8b4b44' : '#4b6935';
}
async function api(path, options={}) {
  const headers = {'Content-Type':'application/json',...(options.headers||{})};
  if(options.method==='POST' && admin.csrf && path!=='/api/login') headers['X-CSRF-Token']=admin.csrf;
  const response = await fetch(path, {...options, headers});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Не удалось загрузить данные');
  return result;
}
function card(x, index) {
  const title = esc(x.title);
  const heading = x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${title} ↗</a>` : title;
  return `<article class="trend-card"><div class="card-top"><span class="rank">#0${index+1} / ${x.source==='demo'?'ПРИМЕР':'СИГНАЛ'}</span><span class="platform ${esc(x.platform)}">${esc(x.platform)}</span></div><div class="thumb" aria-hidden="true"><span>${esc(x.format)}</span></div><h3 class="card-title">${heading}</h3><div class="creator">${esc(x.creator || x.topic)} · ${new Date(x.publishedAt).toLocaleDateString('ru-RU')}</div><div class="card-metrics"><div class="metric"><b>${num(x.views)}</b><span>просмотры</span></div><div class="metric"><b>${percent(rate(x))}</b><span>вовлечённость</span></div><div class="metric"><b>${num(x.reach)}</b><span>охват</span></div></div></article>`;
}
function recommendation(top, demo) {
  if (!top.length) return '<p>Добавьте видео, чтобы получить рекомендацию.</p>';
  const cohort = data.items.filter(x => x.source !== 'demo');
  if (demo || !cohort.length) return '<p class="rec-lead">Добавьте реальные видео, чтобы сравнить форматы и построить рекламную гипотезу на их метриках.</p>';
  const median = values => { const sorted=[...values].sort((a,b)=>a-b); return sorted.length%2?sorted[(sorted.length-1)/2]:(sorted[sorted.length/2-1]+sorted[sorted.length/2])/2; };
  const viewsMedian=median(cohort.map(x=>x.views));
  const rateMedian=median(cohort.map(rate));
  const viewLeader=[...top].sort((a,b)=>b.views-a.views)[0];
  const engageLeader=[...top].sort((a,b)=>rate(b)-rate(a))[0];
  const age=Math.max(1,(Date.now()-Date.parse(viewLeader.publishedAt))/3600000);
  const multiple=viewsMedian?`${(viewLeader.views/viewsMedian).toFixed(1).replace('.',',')} раза`:'—';
  const viewTitle=esc(viewLeader.title.length>100?viewLeader.title.slice(0,97)+'…':viewLeader.title);
  const engageTitle=esc(engageLeader.title.length>100?engageLeader.title.slice(0,97)+'…':engageLeader.title);
  const erComparison=rate(viewLeader)<rateMedian?'ниже':'выше';
  const scaleText=/егэ/i.test(viewLeader.title)
    ? 'Покажите типичную ошибку в задании ЕГЭ и её решение за первые секунды. Затем дайте короткий фрагмент занятия и пригласите на диагностику знаний или пробный урок курса.'
    : 'Используйте механику заголовка лидера: конкретный результат занятия + доступность курса в записи. В первые секунды покажите результат, затем один фрагмент урока и приглашение записаться. Тему адаптируйте к своему курсу.';
  const responseText=/егэ/i.test(engageLeader.title)
    ? 'Проверьте подачу через вопрос ученика по заданию ЕГЭ и разбор преподавателя в кадре. В конце предложите полный план подготовки на курсе.'
    : 'Проверьте подачу через типичный вопрос ученика и короткий ответ преподавателя в кадре.';
  return `<div class="rec-lead">Лидер по просмотрам: «${viewTitle}». У него ${num(viewLeader.views)} просмотров за ${Math.round(age)} ч — ${multiple} больше медианы подборки.</div>
    <div class="rec-evidence"><span>ВОВЛЕЧЁННОСТЬ ЛИДЕРА <b>${percent(rate(viewLeader))}</b></span><span>МЕДИАНА ${cohort.length} ВИДЕО <b>${percent(rateMedian)}</b></span><span>ЛУЧШИЙ ОТКЛИК В ТОП-3 <b>${percent(rate(engageLeader))}</b></span></div>
    <p class="rec-interpret">Отклик лидера ${erComparison} медианы. Поэтому высокий объём просмотров стоит проверить на качество интереса к курсу.</p>
    <div class="rec-list"><div><strong>ВАРИАНТ А · МАСШТАБ</strong><p>${scaleText}</p></div><div><strong>ВАРИАНТ Б · ОТКЛИК</strong><p>В ролике «${engageTitle}» вовлечённость ${percent(rate(engageLeader))}. ${responseText}</p></div></div>
    <p class="rec-test"><strong>Проверка:</strong> запустите оба варианта на одной аудитории и с равным бюджетом на 3 дня. Сравните удержание первых секунд, переходы и стоимость заявки. Победителя выбирайте по заявкам, а не по просмотрам.</p>
    <p class="rec-caveat">Сейчас источники для этого вывода: ${esc([...new Set(cohort.map(x=>x.platform))].join(', '))}. Гипотеза основана на названиях и публичных метриках видео. Содержание роликов и рекламные конверсии сервис пока не анализирует.</p>`;
}
function render() {
  const top=data.top;
  $('#admin-login').hidden=!admin.enabled;
  $('#admin-login').textContent=admin.loggedIn?'Выйти':'Войти';
  $('#connect-bot').hidden=!(admin.enabled && admin.loggedIn && data.telegramConfigured);
  if(admin.enabled){$('#environment-label').textContent='Версия на хостинге';$('#environment-note').textContent='Данные хранятся на сервере';}
  $('#today-date').textContent = new Date().toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
  $('#region-label').textContent=data.settings.region;
  $('#count').textContent=num(data.count);
  $('#views-total').textContent=num(top.reduce((a,x)=>a+x.views,0));
  $('#engagement').textContent=top.length?percent(top.reduce((a,x)=>a+rate(x),0)/top.length):'—';
  $('#last-sync').textContent=data.lastUpdated?new Date(data.lastUpdated).toLocaleDateString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'Нет данных';
  $('#sync-note').textContent=data.demo?'Демонстрационные записи':data.lastSync?'Данные YouTube API и ручной ввод':'Добавлено вручную';
  $('#cards').innerHTML=top.length?top.map(card).join(''):'<p>Видео пока нет. Добавьте первое в базу сигналов.</p>';
  $('#global-cards').innerHTML=data.globalTop?.length?data.globalTop.map(card).join(''):'<p>Глобальных видео пока нет. Обновите данные YouTube или добавьте публичный ролик вручную.</p>';
  $('#global-status').textContent=data.globalSyncError?`Ошибка глобального поиска: ${data.globalSyncError}`:`Короткие YouTube видео со всего мира без тематического запроса за 7 дней; ручные TikTok, Instagram и Threads тоже участвуют, если добавлены за этот период. Найдено: ${data.globalCount || 0}.`;
  $('#recommendation').innerHTML=recommendation(top,data.demo);
  $('#settings-form').elements.query.value=data.settings.query;
  $('#settings-form').elements.region.value=data.settings.region;
  const youtubeStatus=data.hasYouTubeKey?`YouTube API подключён. Тематическая и глобальная выдачи обновляются раз в 24 часа ${admin.enabled?'по расписанию хостинга':'пока локальный сервер работает'}. Ручное обновление доступно раз в час.`:admin.enabled?'YouTube API пока не подключён. Добавьте ключ в закрытый файл настроек хостинга.':'YouTube API пока не подключён. Для автоматического сбора задайте YOUTUBE_API_KEY перед запуском сервера.';
  const limitStatus=Date.parse(data.youtubeBlockedUntil)>Date.now()?`YouTube временно ограничил запросы. Следующая попытка после ${new Date(data.youtubeBlockedUntil).toLocaleString('ru-RU')}.`:'';
  const telegramStatus=!data.telegramConfigured?'Telegram-бот не настроен. Инструкция есть в dashboard/README.md.':`Telegram-бот доступен всем: /start включает ежедневную подборку, /stop отключает её, /digest и /global показывают тренды. Подписчиков: ${data.telegramSubscriberCount || 0}.${data.telegramLastSentDate?` Последняя отправка: ${data.telegramLastSentDate}.`:''}`;
  $('#connection').textContent=[youtubeStatus,limitStatus,telegramStatus].filter(Boolean).join('\n');
  if(data.demo) notice('Демо-режим: карточки и цифры ниже служат примером и не ведут на реальные видео. Добавьте видео об онлайн-обучении или подключите YouTube API.');
  if(data.syncError) notice(`Ошибка обновления YouTube: ${data.syncError}`,'error');
  const counts=Object.fromEntries(['YouTube','TikTok','Instagram','Threads'].map(p=>[p,data.items.filter(x=>x.platform===p).length]));
  document.querySelectorAll('.chip[data-platform]').forEach(btn=>{const p=btn.dataset.platform;btn.textContent=p==='all'?`Все · ${data.items.length}`:`${p} · ${counts[p]}`});
  const pending=['TikTok','Instagram'].filter(p=>counts[p]===0);
  $('#platform-status').textContent=pending.length?`${pending.join(' и ')}: реальных сигналов пока нет. Добавьте ссылки и метрики кнопкой «Добавить видео». Для автоматического сбора публичных роликов разных авторов нужен внешний источник данных.`:`Сигналы TikTok и Instagram доступны в общей таблице и фильтрах.`;
  const rows=data.items.filter(x=>filter==='all'||x.platform===filter);
  $('#table-body').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(x.title)}<small>${esc(x.topic)} · ${new Date(x.publishedAt).toLocaleDateString('ru-RU')}</small></td><td>${esc(x.platform)}</td><td>${num(x.views)}</td><td>${percent(rate(x))}</td><td>${num(x.reach)}</td><td class="${x.source==='demo'?'source-demo':''}">${x.url?`<a class="source-link" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">Смотреть видео ↗</a><small>${x.source==='youtube'?'YouTube API':'Добавлено вручную'}</small>`:'Пример без ссылки'}</td></tr>`).join(''):`<tr><td colspan="6">Пока нет видео из ${filter==='all'?'выбранных источников':esc(filter)}. Добавьте ролик по ссылке и укажите его метрики.</td></tr>`;
}
async function load() {
  data=await api('/api/state');
  admin.enabled=Boolean(data.authRequired);
  admin.loggedIn=!admin.enabled || Boolean(data.isAdmin);
  if(admin.enabled && admin.loggedIn && !admin.csrf){const status=await api('/api/auth');admin.csrf=status.csrfToken;}
  if(!admin.loggedIn) admin.csrf='';
  render();
}
function requireAdmin(){if(!admin.enabled || admin.loggedIn)return true;$('#login-dialog').showModal();return false;}
$('#admin-login').addEventListener('click',async()=>{
  if(!admin.loggedIn){$('#login-dialog').showModal();return;}
  try{await api('/api/logout',{method:'POST'});admin.csrf='';await load();notice('Вы вышли из режима управления.');}catch(error){notice(error.message,'error')}
});
$('#login-close').addEventListener('click',()=>$('#login-dialog').close());
$('#login-form').addEventListener('submit',async(e)=>{
  e.preventDefault();$('#login-error').textContent='';
  try{const password=e.target.elements.password.value;const result=await api('/api/login',{method:'POST',body:JSON.stringify({password})});admin.csrf=result.csrfToken;e.target.reset();$('#login-dialog').close();await load();notice('Режим управления открыт.');}
  catch(error){$('#login-error').textContent=error.message}
});
$('#connect-bot').addEventListener('click',async()=>{
  if(!requireAdmin())return;
  const button=$('#connect-bot');button.disabled=true;
  try{await api('/api/webhook',{method:'POST'});notice('Telegram подключён к сайту. Проверьте команду /status в боте.');}
  catch(error){notice(error.message,'error')}finally{button.disabled=false}
});
$('#refresh').addEventListener('click',async()=>{
  if(!requireAdmin())return;
  const btn=$('#refresh'); btn.disabled=true;
  try { if(!data.hasYouTubeKey){notice('Добавьте ключ YouTube API, чтобы обновлять видео автоматически. Пока можно добавлять их вручную.');return;} const result=await api('/api/sync',{method:'POST'}); await load();notice(`YouTube обновлён: ${result.added} видео по темам, ${result.globalAdded} глобальных.${result.warning?` ${result.warning}`:''}`,result.warning?'error':'info'); }
  catch(e){notice(e.message,'error')}finally{btn.disabled=false}
});
document.querySelectorAll('.chip').forEach(btn=>btn.addEventListener('click',()=>{filter=btn.dataset.platform;document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('selected',x===btn));render()}));
$('#import-open').addEventListener('click',()=>{if(!requireAdmin())return;$('#import-form').elements.publishedAt.value=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16);if(filter!=='all')$('#import-form').elements.platform.value=filter;$('#import-dialog').showModal(); });
$('#import-close').addEventListener('click',()=>$('#import-dialog').close());
$('#import-form').addEventListener('submit',async(e)=>{
  e.preventDefault();$('#form-error').textContent='';
  try{const payload=Object.fromEntries(new FormData(e.target));payload.publishedAt=new Date(payload.publishedAt).toISOString();await api('/api/import',{method:'POST',body:JSON.stringify(payload)});$('#import-dialog').close();e.target.reset();await load();notice('Видео добавлено в базу. Рейтинг обновлён.');}
  catch(error){$('#form-error').textContent=error.message}
});
$('#settings-form').addEventListener('submit',async(e)=>{
  e.preventDefault();if(!requireAdmin())return;try{await api('/api/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});await load();notice('Настройки поиска сохранены. Нажмите «Обновить данные», чтобы получить видео по новой теме.');}catch(error){notice(error.message,'error')}
});
load().catch(e=>notice(e.message,'error'));
