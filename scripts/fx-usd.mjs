// 미국 USD 환율(하나은행 매매기준율, 네이버 증권) → data/fx-usd.json
// GitHub Actions(.github/workflows/fx-usd.yml)가 평일 오전 9시(KST)에 실행.
//   - 오늘 날짜: 실행 시점의 현재 고시 환율(= 오전 9시 기준)
//   - 비어 있는 과거 평일: 네이버 일별 시세(종가)로 백필
// 주말·공휴일은 기록하지 않는다 → 오피스 광고 시트가 직전 영업일 환율을 쓴다.
import fs from 'node:fs';

const FILE = new URL('../data/fx-usd.json', import.meta.url);
const NOW_URL = 'https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW';
const HIST_URL = (page) => `https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW&page=${page}&pageSize=30`;
const num = (s) => Number(String(s || '').replace(/,/g, ''));

async function getJson(url) {
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

const kst = new Date(Date.now() + 9 * 3600 * 1000);
const today = kst.toISOString().slice(0, 10);
const hhmm = kst.toISOString().slice(11, 16);
const isWeekday = kst.getUTCDay() >= 1 && kst.getUTCDay() <= 5;

let data = { rates: {} };
try { data = JSON.parse(fs.readFileSync(FILE, 'utf8')); } catch (e) {}
data.rates = data.rates || {};

// 1) 과거 백필 (최근 90일, 이미 있는 날짜는 건드리지 않음)
for (let page = 1; page <= 3; page++) {
  const j = await getJson(HIST_URL(page));
  for (const row of j.result || []) {
    const d = row.localTradedAt;
    const v = num(row.closePrice);
    if (d && d < today && v > 0 && !data.rates[d]) data.rates[d] = { rate: v, at: '종가' };
  }
}

// 2) 오늘 — 평일에만, 수동 실행이면 이미 있는 값은 유지
const force = process.env.FX_FORCE_TODAY === '1';
if (isWeekday && (force || !data.rates[today])) {
  const j = await getJson(NOW_URL);
  const v = num(j.result && j.result.closePrice);
  if (!(v > 0)) throw new Error('현재 환율 파싱 실패');
  data.rates[today] = { rate: v, at: hhmm };
}

data.rates = Object.fromEntries(Object.entries(data.rates).sort(([a], [b]) => a.localeCompare(b)));
data.updatedAt = Date.now();
fs.writeFileSync(FILE, JSON.stringify(data, null, 1) + '\n');
console.log(`today=${today} ${hhmm} rate=${data.rates[today] ? data.rates[today].rate : '-'} days=${Object.keys(data.rates).length}`);
