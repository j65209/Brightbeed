// 디자인센터 전광판 사진 — 구글시트 'COFERRY LINE SHEET' 의 칸 안 상품 사진을 linesheet/ 로 옮겨 둔다.
// 시트 사진 주소(sheets-images-rt)는 15분 안팎이면 만료되고, 다른 사이트(오피스)에 띄우는 것도 막혀 있어서
// 브라우저가 바로 쓸 수 없다. 그래서 이 스크립트가 주기적으로 받아 오피스와 같은 주소에서 내보낸다.
//   linesheet/images.json  — {v, tabs:{gid:[{k:'번호|상품명', r:블록 머리글 행, f:파일 해시}]}}
//   linesheet/img/<hash>.webp — 240px 썸네일 하나만 (큰 사진은 시트에서 본다 — 레포가 무거워지지 않게)
// 글자(진행 상황)는 오피스가 시트 CSV 를 1분마다 직접 읽는다 — 여기서는 사진만.
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';

const ID = '1Q3eMHCnPsbt3ijGv3Gswym9Q_ao_fJsPSZg8n7R-tng';
const BASE = `https://docs.google.com/spreadsheets/d/${ID}`;
const DEFAULT_TABS = [{ name: '26WINTER', gid: '0' }, { name: '27SS', gid: '417455932' }, { name: '홀딩', gid: '534097050' }];
const OUT = 'linesheet', IMG = `${OUT}/img`, INDEX = `${OUT}/images.json`;

async function get(url, as = 'text') {
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return as === 'buf' ? Buffer.from(await r.arrayBuffer()) : await r.text();
    } catch (e) {
      if (i === 2) throw new Error(`${url.slice(0, 90)} → ${e.message}`);
      await new Promise(res => setTimeout(res, 1500 * (i + 1)));
    }
  }
}

// 따옴표·줄바꿈이 든 칸까지 읽는 작은 CSV 파서
function parseCsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

async function tabs() {
  try {
    const h = await get(`${BASE}/htmlview`), out = [];
    const re = /items\.push\(\{name: "((?:[^"\\]|\\.)*)", pageUrl: "[^"]*", gid: "(\d+)"/g;
    let m; while ((m = re.exec(h))) out.push({ name: m[1], gid: m[2] });
    if (out.length) return out;
  } catch (e) { console.warn('탭 목록 실패, 기본 3탭으로:', e.message); }
  return DEFAULT_TABS;
}

// 상품 블록 = B열 '시즌 카테고리' 머리글 행부터 다음 머리글 전까지. 키는 오피스와 같은 '번호|상품명'
function blocks(rows) {
  const T = v => String(v ?? '').replace(/\r/g, '').trim();
  const out = [];
  rows.forEach((row, r) => {
    if (T(row[1]).replace(/\s/g, '') !== '시즌카테고리') return;
    const next = rows[r + 1] || [];
    out.push({ r, k: `${T(next[0]).replace(/\.0+$/, '')}|${T(row[2]).replace(/\s+/g, ' ')}` });
  });
  return out;
}

// 시트 웹 보기 → [{r: 행 번호(0부터, CSV 행과 같다), src}]
function images(html) {
  const out = [];
  html.split(/<tr[\s>]/).slice(1).forEach(tr => {
    const id = tr.match(/id="\d+R(\d+)"/);
    if (id) for (const m of tr.matchAll(/<img[^>]*?\ssrc="(https:\/\/docs\.google\.com\/sheets-images-rt\/[^"]+)"/g))
      out.push({ r: +id[1], src: m[1].replace(/&amp;/g, '&').replace(/=(?:w\d+-h\d+|s\d+)(?:-[a-z]+)*$/, '') });
  });
  return out;
}

async function main() {
  await mkdir(IMG, { recursive: true });
  const prev = existsSync(INDEX) ? JSON.parse(await readFile(INDEX, 'utf8')) : { tabs: {} };
  const list = await tabs(), next = {};
  let ok = 0;
  for (const tb of list) {
    try {
      const [csv, html] = await Promise.all([get(`${BASE}/export?format=csv&gid=${tb.gid}`), get(`${BASE}/htmlview/sheet?headers=true&gid=${tb.gid}`)]);
      const bl = blocks(parseCsv(csv)), ims = images(html), rows = [];
      for (const im of ims) {
        const b = bl.filter(x => x.r <= im.r).pop();
        if (!b) continue;
        const buf = await get(`${im.src}=w240-h240-rw`, 'buf');
        const f = createHash('sha1').update(buf).digest('hex').slice(0, 16);   // 같은 사진은 같은 이름 → 바뀐 게 없으면 커밋도 없다
        if (!existsSync(`${IMG}/${f}.webp`)) await writeFile(`${IMG}/${f}.webp`, buf);
        rows.push({ k: b.k, r: b.r, f });
      }
      next[tb.gid] = rows; ok++;
      console.log(`${tb.name} (${tb.gid}): 블록 ${bl.length} · 사진 ${rows.length}`);
    } catch (e) {
      console.warn(`${tb.name} 실패 — 이전 사진 목록 유지:`, e.message);
      if (prev.tabs?.[tb.gid]) next[tb.gid] = prev.tabs[tb.gid];
    }
  }
  if (!ok) { console.error('시트를 하나도 못 읽었어요 — 바꾸지 않고 끝냅니다'); return; }
  const body = JSON.stringify({ v: 1, tabs: next });
  if (body !== JSON.stringify({ v: 1, tabs: prev.tabs || {} })) await writeFile(INDEX, body + '\n');
  // 더 이상 안 쓰는 사진 파일 정리
  const used = new Set(Object.values(next).flat().map(x => `${x.f}.webp`));
  for (const fn of await readdir(IMG)) if (!used.has(fn)) await unlink(`${IMG}/${fn}`);
  console.log(`사진 ${used.size}장`);
}
main().catch(e => { console.error(e); process.exit(1); });
