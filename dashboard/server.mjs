import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const dataFile = join(root, 'data', 'radar.json');
try {
  const localEnv = await readFile(join(root, '.env'), 'utf8');
  const key = localEnv.match(/^YOUTUBE_API_KEY=([A-Za-z0-9_-]+)$/m)?.[1];
  if (key && !process.env.YOUTUBE_API_KEY) process.env.YOUTUBE_API_KEY = key;
} catch {}
const port = Number(process.env.PORT || 4173);
const platforms = new Set(['YouTube', 'TikTok', 'Instagram', 'Threads']);
const sample = [
  { id: 'demo-1', platform: 'TikTok', title: 'Один приём для запоминания новой темы за 15 секунд', creator: '@academy.example', url: '', topic: 'Онлайн-обучение', format: 'Быстрый урок', views: 1280000, likes: 90600, comments: 2840, shares: 15200, reach: null, publishedAt: new Date(Date.now()-22*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' },
  { id: 'demo-2', platform: 'Instagram', title: 'До / после: прогресс ученика за месяц', creator: '@school.example', url: '', topic: 'Онлайн-обучение', format: 'История результата', views: 842000, likes: 57400, comments: 1670, shares: 10800, reach: null, publishedAt: new Date(Date.now()-31*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' },
  { id: 'demo-3', platform: 'YouTube', title: 'Три ошибки при изучении языка онлайн', creator: 'Learning Example', url: '', topic: 'Онлайн-обучение', format: 'Разбор ошибок', views: 635000, likes: 38100, comments: 1290, shares: null, reach: null, publishedAt: new Date(Date.now()-39*3600000).toISOString(), collectedAt: new Date().toISOString(), source: 'demo' }
];
let state = { settings: { region: 'RU', query: 'онлайн обучение' }, items: [], lastSync: null, lastUpdated: null, syncError: null };
try { state = { ...state, ...JSON.parse(await readFile(dataFile, 'utf8')) }; } catch {}

function score(item) {
  const ageHours = Math.max(1, (Date.now() - Date.parse(item.publishedAt)) / 3600000);
  const engagement = ((item.likes || 0) + 2*(item.comments || 0) + 3*(item.shares || 0)) / Math.max(1,item.views);
  return (item.views / Math.pow(ageHours + 6, .72)) * (1 + Math.min(engagement, .25)*3);
}
function topThree(ranked) {
  const selected = [], creators = new Set();
  for (const item of ranked) {
    const creator = (item.creator || item.id).trim().toLocaleLowerCase();
    if (creators.has(creator)) continue;
    selected.push(item); creators.add(creator);
    if (selected.length === 3) return selected;
  }
  for (const item of ranked) {
    if (!selected.includes(item)) selected.push(item);
    if (selected.length === 3) break;
  }
  return selected;
}
function publicState() {
  const items = state.items.length ? state.items : sample;
  const ranked = [...items].sort((a,b)=>score(b)-score(a));
  return { settings: state.settings, lastSync: state.lastSync, lastUpdated: state.lastUpdated, syncError: state.syncError, demo: !state.items.length, hasYouTubeKey: !!process.env.YOUTUBE_API_KEY,
    count: items.length, top: topThree(ranked).map(x=>({...x,trendScore:Math.round(score(x))})),
    items: ranked.map(x=>({...x,trendScore:Math.round(score(x))})) };
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
  const searches = state.settings.query === 'онлайн обучение'
    ? ['"онлайн обучение"', '"онлайн курс"', '"онлайн школа"']
    : [state.settings.query];
  const results = await Promise.all(searches.map(async term => {
    const q = new URL('https://www.googleapis.com/youtube/v3/search');
    q.search = new URLSearchParams({part:'snippet',type:'video',videoDuration:'short',order:'viewCount',maxResults:'15',publishedAfter:new Date(Date.now()-7*86400000).toISOString(),regionCode:state.settings.region,q:term,key}).toString();
    const found = await fetch(q); const result = await found.json();
    if (!found.ok) throw Error(result.error?.message || 'YouTube API недоступен');
    return result.items || [];
  }));
  const ids = [...new Set(results.flat().map(x=>x.id?.videoId).filter(Boolean))];
  if (!ids.length) throw Error('По текущему запросу видео не найдены');
  const u = new URL('https://www.googleapis.com/youtube/v3/videos');
  u.search = new URLSearchParams({part:'snippet,statistics,contentDetails',id:ids.join(','),key}).toString();
  const response = await fetch(u); const details = await response.json();
  if (!response.ok) throw Error(details.error?.message || 'Не удалось получить метрики видео');
  const relevant = v => {
    if (state.settings.query !== 'онлайн обучение') return true;
    const title = v.snippet?.title || '';
    return (state.settings.region !== 'RU' || /[а-яё]/i.test(title))
      && /(онлайн|online|on-line|дистанцион|zoom)/i.test(title)
      && /(обуч|курс|школ|урок|образован|учеб|education|learn|class|school)/i.test(title);
  };
  const items = (details.items||[]).filter(relevant).map(v=>({id:`youtube-${v.id}`,platform:'YouTube',title:v.snippet?.title||'Видео',creator:v.snippet?.channelTitle||'',url:`https://www.youtube.com/watch?v=${v.id}`,topic:state.settings.query,format:'Короткое видео',views:Number(v.statistics?.viewCount||0),likes:Number(v.statistics?.likeCount||0),comments:Number(v.statistics?.commentCount||0),shares:null,reach:null,publishedAt:v.snippet?.publishedAt||new Date().toISOString(),collectedAt:new Date().toISOString(),source:'youtube'}));
  const others = state.items.filter(x=>x.source !== 'youtube');
  state.items = [...others,...items]; state.lastSync = new Date().toISOString(); state.lastUpdated = state.lastSync; state.syncError = null; await save();
  return items.length;
}
let syncing = false;
async function scheduledSync() {
  if (!process.env.YOUTUBE_API_KEY || syncing) return;
  const last = state.lastSync ? Date.parse(state.lastSync) : 0;
  if (Date.now()-last < 24*3600000) return;
  syncing=true; try { await syncYouTube(); } catch(e) { state.syncError=e.message; await save(); } finally { syncing=false; }
}
setInterval(scheduledSync, 3600000).unref();
scheduledSync();

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
      const x=await body(req); const region=String(x.region||'RU').toUpperCase(); const query=String(x.query||'онлайн обучение').trim();
      if (!/^[A-Z]{2}$/.test(region)||!query||query.length>80) throw Error('Укажите регион из двух букв и тему до 80 символов');
      state.settings={region,query}; await save(); return json(res,200,state.settings);
    }
    if (req.method==='POST' && url.pathname==='/api/sync') { if(syncing) return json(res,409,{error:'Обновление уже идёт'}); syncing=true; try { return json(res,200,{added:await syncYouTube()}); } finally { syncing=false; } }
    if (req.method==='GET' && (url.pathname==='/'||url.pathname==='/index.html'||url.pathname==='/style.css'||url.pathname==='/app.js')) {
      const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
      const type=name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'text/html';
      res.writeHead(200,{'Content-Type':`${type}; charset=utf-8`}); return res.end(await readFile(join(root,'public',name)));
    }
    json(res,404,{error:'Не найдено'});
  } catch(e) { json(res,400,{error:e.message||'Ошибка запроса'}); }
}).listen(port,'127.0.0.1',()=>console.log(`Trend Radar: http://127.0.0.1:${port}`));
