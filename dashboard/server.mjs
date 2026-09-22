import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startTelegramBot } from './telegram.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const dataFile = join(root, 'data', 'radar.json');
try {
  const localEnv = await readFile(join(root, '.env'), 'utf8');
  for (const line of localEnv.split(/\r?\n/)) {
    const match = line.match(/^([A-Z][A-Z0-9_]*)=(.*)$/);
    if (match && !process.env[match[1]]) process.env[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/, '$2');
  }
} catch {}
const port = Number(process.env.PORT || 4173);
const platforms = new Set(['YouTube', 'TikTok', 'Instagram', 'Threads']);
const defaultQuery = 'онлайн обучение и курсы ЕГЭ';
const sample = [
  { id: 'demo-1', platform: 'TikTok', title: 'Один приём для запоминания новой темы за 15 секунд', creator: '@academy.example', url: '', topic: 'Онлайн-обучение', format: 'Быстрый урок', views: 1280000, likes: 90600, comments: 2840, shares: 15200, reach: null, publishedAt: new Date(Date.now()-22*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' },
  { id: 'demo-2', platform: 'Instagram', title: 'До / после: прогресс ученика за месяц', creator: '@school.example', url: '', topic: 'Онлайн-обучение', format: 'История результата', views: 842000, likes: 57400, comments: 1670, shares: 10800, reach: null, publishedAt: new Date(Date.now()-31*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' },
  { id: 'demo-3', platform: 'YouTube', title: 'Три ошибки при изучении языка онлайн', creator: 'Learning Example', url: '', topic: 'Онлайн-обучение', format: 'Разбор ошибок', views: 635000, likes: 38100, comments: 1290, shares: null, reach: null, publishedAt: new Date(Date.now()-39*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' }
];
let state = { settings: { region: 'RU', query: defaultQuery }, items: [], globalItems: [], lastSync: null, globalLastSync: null, lastUpdated: null, syncError: null, globalSyncError: null, telegramLastSentDate: null };
try { state = { ...state, ...JSON.parse(await readFile(dataFile, 'utf8')) }; } catch {}
state.globalItems ||= [];
if (state.settings.query === 'онлайн обучение') {
  state.settings.query = defaultQuery;
  state.lastSync = null;
  await save();
}

function score(item) {
  const ageHours = Math.max(1, (Date.now() - Date.parse(item.publishedAt)) / 3600000);
  const engagement = ((item.likes || 0) + 2*(item.comments || 0) + 3*(item.shares || 0)) / Math.max(1,item.views);
  return (item.views / Math.pow(ageHours + 6, .72)) * (1 + Math.min(engagement, .25)*3);
}
function topThree(ranked) {
  const selected = [], creators = new Set();
  if (state.settings.query === defaultQuery) {
    const online = ranked.find(item => item.topic !== 'Курсы подготовки к ЕГЭ');
    const ege = ranked.find(item => item.topic === 'Курсы подготовки к ЕГЭ' && item.creator !== online?.creator);
    for (const item of [online, ege].filter(Boolean)) {
      selected.push(item);
      creators.add((item.creator || item.id).trim().toLocaleLowerCase());
    }
  }
  for (const item of ranked) {
    const creator = (item.creator || item.id).trim().toLocaleLowerCase();
    if (creators.has(creator)) continue;
    selected.push(item); creators.add(creator);
    if (selected.length === 3) return selected.sort((a,b)=>score(b)-score(a));
  }
  for (const item of ranked) {
    if (!selected.includes(item)) selected.push(item);
    if (selected.length === 3) break;
  }
  return selected.sort((a,b)=>score(b)-score(a));
}
function publicState() {
  const items = state.items.length ? state.items : sample;
  const ranked = [...items].sort((a,b)=>score(b)-score(a));
  const since = Date.now() - 7*86400000;
  const manualGlobal = state.items.filter(item => item.source === 'manual' && Date.parse(item.publishedAt) >= since);
  const global = [...state.globalItems, ...manualGlobal].filter(item => item.url).sort((a,b)=>b.views-a.views);
  return { settings: state.settings, lastSync: state.lastSync, lastUpdated: state.lastUpdated, syncError: state.syncError, demo: !state.items.length, hasYouTubeKey: !!process.env.YOUTUBE_API_KEY,
    telegramConfigured: !!process.env.TELEGRAM_BOT_TOKEN, telegramLinked: !!process.env.TELEGRAM_CHAT_ID, telegramLastSentDate: state.telegramLastSentDate,
    count: items.length, top: topThree(ranked).map(x=>({...x,trendScore:Math.round(score(x))})),
    items: ranked.map(x=>({...x,trendScore:Math.round(score(x))})),
    globalCount: global.length, globalTop: global.slice(0,3), globalLastSync: state.globalLastSync, globalSyncError: state.globalSyncError };
}
async function save() { await mkdir(dirname(dataFile), {recursive:true}); await writeFile(dataFile, JSON.stringify(state,null,2)); }
function json(res, code, value) { res.writeHead(code, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}); res.end(JSON.stringify(value)); }
async function body(req) { let text=''; for await (const part of req) { text += part; if (text.length > 2_000_000) throw Error('Файл слишком большой'); } return JSON.parse(text); }
function validItem(x) {
  if (!x || !platforms.has(x.platform) || typeof x.title !== 'string' || !x.title.trim() || !Number.isFinite(Number(x.views)) || Number(x.views)<0 || !Number.isFinite(Date.parse(x.publishedAt))) throw Error('Нужны платформа, название, просмотры и дата публикации');
  if (!x.url || !/^https:\/\//.test(x.url)) throw Error('Укажите ссылку на видео, начинающуюся с https://');
  return { id: crypto.randomUUID(), platform:x.platform, title:x.title.trim().slice(0,180), creator:String(x.creator||'').slice(0,90), url:String(x.url), topic:String(x.topic||'Онлайн-обучение').slice(0,80), format:String(x.format||'Короткое видео').slice(0,80), views:Number(x.views), likes:Number(x.likes)||0, comments:Number(x.comments)||0, shares:x.shares==null||x.shares===''?null:Number(x.shares), reach:x.reach==null||x.reach===''?null:Number(x.reach), publishedAt:new Date(x.publishedAt).toISOString(), collectedAt:new Date().toISOString(), source:'manual' };
}
async function syncYouTube() {
  const key = process.env.YOUTUBE_API_KEY;
  if (!key) throw Error('Добавьте YOUTUBE_API_KEY в окружение сервера');
  const searches = state.settings.query === defaultQuery
    ? ['"онлайн обучение"', '"онлайн курс"', 'ЕГЭ подготовка', 'ЕГЭ разбор задания', 'ЕГЭ онлайн курс']
    : [state.settings.query];
  const results = [], searchErrors = [];
  for (const term of searches) {
    try {
      const q = new URL('https://www.googleapis.com/youtube/v3/search');
      q.search = new URLSearchParams({part:'snippet',type:'video',videoDuration:'short',order:'viewCount',maxResults:'15',publishedAfter:new Date(Date.now()-7*86400000).toISOString(),regionCode:state.settings.region,q:term,key}).toString();
      const found = await fetch(q); const result = await found.json();
      if (!found.ok) throw Error(result.error?.message || 'YouTube API недоступен');
      results.push(result.items || []);
    } catch(e) { searchErrors.push(`${term}: ${e.message}`); }
  }
  if (!results.length) throw Error(searchErrors.join('; ') || 'YouTube API недоступен');
  const ids = [...new Set(results.flat().map(x=>x.id?.videoId).filter(Boolean))];
  if (!ids.length) throw Error('По текущему запросу видео не найдены');
  const videos = [];
  for (let index=0; index<ids.length; index+=50) {
    const u = new URL('https://www.googleapis.com/youtube/v3/videos');
    u.search = new URLSearchParams({part:'snippet,statistics,contentDetails',id:ids.slice(index,index+50).join(','),key}).toString();
    const response = await fetch(u); const details = await response.json();
    if (!response.ok) throw Error(details.error?.message || 'Не удалось получить метрики видео');
    videos.push(...(details.items||[]));
  }
  const relevant = v => {
    if (state.settings.query !== defaultQuery) return true;
    const title = v.snippet?.title || '';
    return (state.settings.region !== 'RU' || /[а-яё]/i.test(title))
      && (/(егэ)/i.test(title)
        ? /(курс|онлайн|online|школ|обуч|подготовк|задани|разбор|балл|урок|экзамен)/i.test(title)
        : /(онлайн|online|on-line|дистанцион|zoom)/i.test(title)
          && /(обуч|курс|школ|урок|образован|учеб|education|learn|class|school)/i.test(title));
  };
  const items = videos.filter(relevant).map(v=>({id:`youtube-${v.id}`,platform:'YouTube',title:v.snippet?.title||'Видео',creator:v.snippet?.channelTitle||'',url:`https://www.youtube.com/watch?v=${v.id}`,topic:/егэ/i.test(v.snippet?.title||'')?'Курсы подготовки к ЕГЭ':'Онлайн-обучение',format:'Короткое видео',views:Number(v.statistics?.viewCount||0),likes:Number(v.statistics?.likeCount||0),comments:Number(v.statistics?.commentCount||0),shares:null,reach:null,publishedAt:v.snippet?.publishedAt||new Date().toISOString(),collectedAt:new Date().toISOString(),source:'youtube'}));
  if (!items.length) throw Error('По выбранным темам пока нет релевантных видео; прежние записи сохранены');
  const others = state.items.filter(x=>x.source !== 'youtube');
  state.items = [...others,...items]; state.lastSync = new Date().toISOString(); state.lastUpdated = state.lastSync; state.syncError = searchErrors.length?`Часть запросов не выполнена: ${searchErrors.join('; ')}`:null; await save();
  return items.length;
}
async function syncGlobalYouTube() {
  const key = process.env.YOUTUBE_API_KEY;
  if (!key) throw Error('Добавьте YOUTUBE_API_KEY в окружение сервера');
  const search = new URL('https://www.googleapis.com/youtube/v3/search');
  search.search = new URLSearchParams({part:'snippet',type:'video',videoDuration:'short',order:'viewCount',maxResults:'50',publishedAfter:new Date(Date.now()-7*86400000).toISOString(),safeSearch:'moderate',q:'#shorts',key}).toString();
  const response = await fetch(search);
  const found = await response.json();
  if (!response.ok) throw Error(found.error?.message || 'Глобальный поиск YouTube недоступен');
  const ids = [...new Set((found.items||[]).map(item=>item.id?.videoId).filter(Boolean))];
  if (!ids.length) throw Error('Глобальный поиск не вернул коротких видео');
  const detailsUrl = new URL('https://www.googleapis.com/youtube/v3/videos');
  detailsUrl.search = new URLSearchParams({part:'snippet,statistics,contentDetails',id:ids.join(','),key}).toString();
  const detailsResponse = await fetch(detailsUrl);
  const details = await detailsResponse.json();
  if (!detailsResponse.ok) throw Error(details.error?.message || 'Не удалось получить просмотры глобальных видео');
  const items = (details.items||[]).map(v=>({id:`global-youtube-${v.id}`,platform:'YouTube',title:v.snippet?.title||'Видео',creator:v.snippet?.channelTitle||'',url:`https://www.youtube.com/watch?v=${v.id}`,topic:'Без тематического фильтра',format:'Короткое видео',views:Number(v.statistics?.viewCount||0),likes:Number(v.statistics?.likeCount||0),comments:Number(v.statistics?.commentCount||0),shares:null,reach:null,publishedAt:v.snippet?.publishedAt||new Date().toISOString(),collectedAt:new Date().toISOString(),source:'global-youtube'}));
  if (!items.length) throw Error('Глобальный поиск не вернул видео с метриками; прежние записи сохранены');
  state.globalItems = items.sort((a,b)=>b.views-a.views);
  state.globalLastSync = new Date().toISOString(); state.globalSyncError = null; await save();
  return items.length;
}
let syncing = false;
async function scheduledSync() {
  if (!process.env.YOUTUBE_API_KEY || syncing) return;
  const thematicDue = Date.now()-(state.lastSync ? Date.parse(state.lastSync) : 0) >= 24*3600000;
  const globalDue = Date.now()-(state.globalLastSync ? Date.parse(state.globalLastSync) : 0) >= 24*3600000;
  if (!thematicDue && !globalDue) return;
  syncing=true;
  try {
    if (thematicDue) try { await syncYouTube(); } catch(e) { state.syncError=e.message; await save(); }
    if (globalDue) try { await syncGlobalYouTube(); } catch(e) { state.globalSyncError=e.message; await save(); }
  } finally { syncing=false; }
}
setInterval(scheduledSync, 3600000).unref();
scheduledSync();
startTelegramBot({
  token: process.env.TELEGRAM_BOT_TOKEN,
  chatId: process.env.TELEGRAM_CHAT_ID,
  hour: /^([01]?\d|2[0-3])$/.test(process.env.TELEGRAM_DIGEST_HOUR || '') ? Number(process.env.TELEGRAM_DIGEST_HOUR) : 9,
  getSnapshot: publicState,
  getLastSentDate: () => state.telegramLastSentDate,
  markSentDate: async day => { state.telegramLastSentDate = day; await save(); },
  reportError: error => console.error('Telegram bot:', error.message)
});

createServer(async(req,res)=>{
  try {
    const url = new URL(req.url, `http://localhost:${port}`);
    if (req.method==='GET' && url.pathname==='/api/state') return json(res,200,publicState());
    if (req.method==='POST' && url.pathname==='/api/import') {
      const payload=await body(req); const rows=Array.isArray(payload)?payload:[payload];
      if (rows.length>500) throw Error('Максимум 500 записей за раз');
      const added=rows.map(validItem); state.items.push(...added); state.lastUpdated=new Date().toISOString(); await save(); return json(res,200,{added:added.length});
    }
    if (req.method==='POST' && url.pathname==='/api/settings') {
      const x=await body(req); const region=String(x.region||'RU').toUpperCase(); const query=String(x.query||defaultQuery).trim();
      if (!/^[A-Z]{2}$/.test(region)||!query||query.length>80) throw Error('Укажите регион из двух букв и тему до 80 символов');
      state.settings={region,query}; await save(); return json(res,200,state.settings);
    }
    if (req.method==='POST' && url.pathname==='/api/sync') {
      if(syncing) return json(res,409,{error:'Обновление уже идёт'});
      syncing=true;
      try {
        let added=0, globalAdded=0; const errors=[];
        try { added=await syncYouTube(); } catch(e) { state.syncError=e.message; await save(); errors.push(`Темы: ${e.message}`); }
        try { globalAdded=await syncGlobalYouTube(); } catch(e) { state.globalSyncError=e.message; await save(); errors.push(`Глобально: ${e.message}`); }
        return json(res,errors.length===2?502:200,{added,globalAdded,...(errors.length?{warning:errors.join('; '),error:errors.join('; ')}:{})});
      } finally { syncing=false; }
    }
    if (req.method==='GET' && (url.pathname==='/'||url.pathname==='/index.html'||url.pathname==='/style.css'||url.pathname==='/app.js')) {
      const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
      const type=name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'text/html';
      res.writeHead(200,{'Content-Type':`${type}; charset=utf-8`}); return res.end(await readFile(join(root,'public',name)));
    }
    json(res,404,{error:'Не найдено'});
  } catch(e) { json(res,400,{error:e.message||'Ошибка запроса'}); }
}).listen(port,'127.0.0.1',()=>console.log(`Trend Radar: http://127.0.0.1:${port}`));
