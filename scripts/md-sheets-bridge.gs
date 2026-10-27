/**
 * Bead Universe Office ↔ 구글시트 브리지 (MD팀 탭)
 *
 * 오피스 MD팀 탭이 아래 6개 구글시트를 실시간으로 읽고, 오피스에서 고친 칸을 구글시트에 바로 써넣는다.
 * 수식·자동수집 스크립트는 구글시트에서 그대로 돌아가고, 오피스는 "보이는 값(표시값)"을 그대로 보여준다.
 *
 * ── 설치 (한 번만) ──────────────────────────────────────────────
 *  1. https://script.google.com → 새 프로젝트 → 이 파일 내용 전체를 붙여넣고 저장
 *     (6개 시트 모두 편집 권한이 있는 구글 계정으로 해야 한다)
 *  2. 오른쪽 위 [배포] → [새 배포] → 유형: 웹 앱
 *       · 실행 계정: 나
 *       · 액세스 권한: 모든 사용자
 *     → [배포] → 권한 승인 → "웹 앱 URL"(…/exec) 복사
 *  3. 오피스 MD팀 탭 → [구글시트 연결] 칸에 URL 붙여넣기 → [연결]
 *     (첫 연결 때 이 스크립트가 비밀 토큰을 만들어 오피스에 넘겨준다. 이후 다른 곳에서는 연결 불가)
 *
 *  연결을 처음부터 다시 하고 싶으면 편집기에서 resetPairing 함수를 한 번 실행한다.
 *  코드를 고친 뒤에는 [배포] → [배포 관리] → 연필 → 버전: 새 버전 → [배포] (URL 유지)
 */

const BOOKS = {
  ably_price: '1AxXEFYfGx_IK8AOj83b8qZQW7F9J1IBHiTLkJ5c_wEQ',
  zig_price:  '1aMAQncyPOwaoWkkwtL6U-JD0ziv_60E9eRmr1gWjZLk',
  coferry:    '1bnKosG3_Ytjg-maMKt1SeaO-ojeQemKp_mzyjnWscD0',
  apeti:      '1u6u15dxSUthAYKxqjYH8zLSdOAeWAiFtM24dVYZwOS0',
  kozmi:      '1TS-HqffOap11AdGwiffMr38KwHAUq1fmcjmmBPdKLMU',
  invoice:    '1hE7jVLZvE3gBYWflk6d3p2vZroQC9Hz3HY7jf2eqIcA',
};

// MD 업무 탭만 — 판매원본·주문로그·날짜별 주문 원본(개인정보)·시스템(_로 시작) 탭은 오피스에 노출하지 않는다
const EXCLUDE = /판매원본|주문로그|_state|^_|^\d+\.\d+(코페리|아페티|코즈미)$|^(코페리|아페티|코즈미)\d+\.\d+$|^플토/;
// 날짜가 붙어 매일 새로 생기는 송장출력 탭은 브랜드별로 가장 왼쪽(최신) 탭 하나만
const LATEST_ONLY = /^\d+\.\d+(코페리|아페티|코즈미)송장출력$/;

const MAX_ROWS = 3000;

function doGet(e) { return route_((e && e.parameter) || {}); }
function doPost(e) {
  let p = {};
  try { p = JSON.parse((e && e.postData && e.postData.contents) || '{}'); } catch (_) {}
  return route_(p);
}

function route_(p) {
  try {
    if (p.action === 'pair') return json_(pair_());
    if (!checkToken_(p.token)) return json_({ ok: false, error: 'unauthorized' });
    switch (p.action) {
      case 'ping':  return json_({ ok: true });
      case 'meta':  return json_(meta_(p.fresh === '1' || p.fresh === true));
      case 'read':  return json_(read_(p.book, p.sheet, p.have || null, p.parts || ''));
      case 'write': return json_(write_(p.book, p.sheet, p.edits || []));
      case 'audit_fix': return json_(auditFix_(!(p.apply === true || p.apply === '1'), p.babyB === '16400'));
      default:      return json_({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return json_({ ok: false, error: String((err && err.message) || err) });
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

/* ── 연결(페어링) ── */
function pair_() {
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('TOKEN')) return { ok: false, error: 'already_paired' };
  const token = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  props.setProperty('TOKEN', token);
  return { ok: true, token: token };
}
function checkToken_(t) {
  const saved = PropertiesService.getScriptProperties().getProperty('TOKEN');
  return !!saved && t === saved;
}
function resetPairing() {
  PropertiesService.getScriptProperties().deleteProperty('TOKEN');
  CacheService.getScriptCache().remove('meta');
}

/* ── 탭 목록 ── */
function allowedSheets_(ss) {
  const seenLatest = {};
  return ss.getSheets().filter(function (sh) {
    const name = sh.getName();
    if (sh.isSheetHidden() || EXCLUDE.test(name)) return false;
    const m = name.match(LATEST_ONLY);
    if (m) {
      if (seenLatest[m[1]]) return false;
      seenLatest[m[1]] = true;
    }
    return true;
  });
}
function openBook_(key) {
  const id = BOOKS[key];
  if (!id) throw new Error('unknown_book');
  return SpreadsheetApp.openById(id);
}
function sheetOf_(key, name) {
  const ss = openBook_(key);
  const sh = ss.getSheetByName(name);
  if (!sh || sh.isSheetHidden() || EXCLUDE.test(name)) throw new Error('sheet_not_allowed');
  // 날짜 붙은 송장출력 탭만 "브랜드별 최신 1개" 규칙을 확인한다 (전체 탭 훑기는 이때만)
  if (LATEST_ONLY.test(name) && !allowedSheets_(ss).some(function (s) { return s.getName() === name; })) throw new Error('sheet_not_allowed');
  return { ss: ss, sh: sh };
}

/* ── 캐시 — CacheService 값 1개당 100KB 제한이라 잘라서 저장한다 ── */
const CHUNK = 30000;
function cachePut_(key, obj, ttl) {
  try {
    const s = JSON.stringify(obj), n = Math.max(1, Math.ceil(s.length / CHUNK)), m = {};
    for (let i = 0; i < n; i++) m[key + ':' + i] = s.slice(i * CHUNK, (i + 1) * CHUNK);
    m[key + ':n'] = String(n);
    CacheService.getScriptCache().putAll(m, ttl);
  } catch (_) {}
}
function cacheGet_(key) {
  try {
    const c = CacheService.getScriptCache(), n = Number(c.get(key + ':n'));
    if (!n) return null;
    const keys = [];
    for (let i = 0; i < n; i++) keys.push(key + ':' + i);
    const got = c.getAll(keys);
    let s = '';
    for (let i = 0; i < n; i++) {
      const part = got[key + ':' + i];
      if (part == null) return null;
      s += part;
    }
    return JSON.parse(s);
  } catch (_) { return null; }
}
function cacheDel_(key) { try { CacheService.getScriptCache().remove(key + ':n'); } catch (_) {} }
function sig_(s) {
  return Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, s, Utilities.Charset.UTF_8));
}

function meta_(fresh) {
  const cache = CacheService.getScriptCache();
  if (!fresh) {
    const hit = cache.get('meta');
    if (hit) return JSON.parse(hit);
  }
  const books = Object.keys(BOOKS).map(function (key) {
    try {
      const ss = openBook_(key);
      return {
        key: key, id: BOOKS[key], name: ss.getName(), url: ss.getUrl(),
        tabs: allowedSheets_(ss).map(function (sh) {
          return { name: sh.getName(), gid: sh.getSheetId(), rows: sh.getLastRow(), cols: sh.getLastColumn() };
        }),
      };
    } catch (err) {
      return { key: key, id: BOOKS[key], error: String((err && err.message) || err), tabs: [] };
    }
  });
  const out = { ok: true, books: books, at: new Date().toISOString() };
  try { cache.put('meta', JSON.stringify(out), 300); } catch (_) {}
  return out;
}

/* ── 읽기 v2 ──
 * 내용(표시값·수식)과 구조(서식·드롭다운·숨김열·병합)를 따로 캐시한다.
 *  · 내용 20초 캐시 (쓰기 때 지움) — 여러 사람이 같은 탭을 보거나 60초 갱신이 몰려도 시트를 한 번만 읽는다
 *  · 구조 30분 캐시 — 서식·드롭다운은 거의 안 바뀌는데 큰 탭에서 가장 오래 걸린다
 * 같은 수식(아래로 채우기)은 R1C1 로 한 번만, 서식은 같은 열의 연속 구간 단위로 묶어 보낸다.
 * 오피스가 have={ct,st} 로 이미 가진 버전을 알려주면 바뀐 부분만 보낸다. */
const SPILL = /\b(QUERY|FILTER|SORT|SORTN|SEQUENCE|ARRAYFORMULA|UNIQUE|IMPORTRANGE|FLATTEN|TRANSPOSE)\s*\(/i;
function cacheBase_(key, sh) {
  return key + ':' + sh.getSheetId() + ':' + Math.min(sh.getLastRow(), MAX_ROWS) + 'x' + sh.getLastColumn();
}
function read_(key, name, have, parts) {
  const T = {}, t0 = Date.now();
  const sh = sheetOf_(key, name).sh;
  T.open = Date.now() - t0;
  const lastRow = sh.getLastRow(), lastCol = sh.getLastColumn(), gid = sh.getSheetId(), at = new Date().toISOString();
  if (!lastRow || !lastCol) {
    return { ok: true, v: 2, rows: 0, cols: 0, totalRows: 0, gid: gid, at: at,
      content: { sig: 'empty', values: [], fxList: [], fxRuns: [], img: {}, ro: false },
      structure: { sig: 'empty', bg: [], fc: [], bold: [], dv: [], lists: [], hiddenCols: [], merges: [], frozenRows: 0, frozenCols: 0 } };
  }
  const nRows = Math.min(lastRow, MAX_ROWS), base = cacheBase_(key, sh);
  // parts='content' 면 값만(빠름), 'structure' 면 서식만 — 오피스가 처음 여는 탭은 둘을 따로 받아 값부터 그린다
  const out = { ok: true, v: 2, rows: nRows, cols: lastCol, totalRows: lastRow, truncated: lastRow > nRows, gid: gid, at: at, ms: T };
  let t = Date.now();
  if (parts !== 'structure') {
    let content = cacheGet_('c2:' + base);
    if (!content) { content = readContent_(sh, nRows, lastCol); cachePut_('c2:' + base, content, 20); }
    if (!have || have.ct !== content.sig) out.content = content;
  }
  T.content = Date.now() - t; t = Date.now();
  if (parts !== 'content') {
    let st = cacheGet_('s2:' + base);
    if (!st) { st = readStructure_(sh, nRows, lastCol, key + ':' + base); cachePut_('s2:' + base, st, 1800); }
    if (!have || have.st !== st.sig) out.structure = st;
  }
  T.structure = Date.now() - t;
  return out;
}

// 같은 열에서 연속된 같은 값을 [열, 시작행, 끝행, 값] 으로 묶는다 (값이 null 이면 생략)
function runs_(grid, nRows, nCols, pick) {
  const out = [];
  for (let c = 0; c < nCols; c++) {
    let run = null;
    for (let r = 0; r < nRows; r++) {
      const v = pick(grid[r][c], r, c);
      if (run && run[3] === v && run[2] === r - 1) { run[2] = r; continue; }
      if (run && run[3] != null) out.push(run);
      run = [c, r, r, v];
    }
    if (run && run[3] != null) out.push(run);
  }
  return out;
}

function readContent_(sh, nRows, nCols) {
  const rg = sh.getRange(1, 1, nRows, nCols);
  const values = rg.getDisplayValues();
  const fr = rg.getFormulasR1C1();
  const fxList = [], fxIdx = {}, img = {};
  let ro = false;
  const fxRuns = runs_(fr, nRows, nCols, function (f, r, c) {
    if (!f) return null;
    if (!(f in fxIdx)) { fxIdx[f] = fxList.length; fxList.push(f); if (SPILL.test(f)) ro = true; }
    const src = imageSrc_(f, r, c, values);
    if (src) img[r + ',' + c] = src;
    return fxIdx[f];
  });
  // 뒤쪽 빈칸·빈 행은 잘라서 전송량을 줄인다
  for (let r = 0; r < values.length; r++) {
    let e = values[r].length;
    while (e > 0 && values[r][e - 1] === '') e--;
    values[r] = values[r].slice(0, e);
  }
  let last = values.length;
  while (last > 0 && !values[last - 1].length) last--;
  values.length = last;
  const body = { values: values, fxList: fxList, fxRuns: fxRuns, img: img, ro: ro };
  body.sig = sig_(JSON.stringify(body));
  return body;
}

function imageSrc_(f, r, c, values) {
  const m = f.match(/^=\s*IMAGE\s*\(\s*(?:"([^"]+)"|R(\[-?\d+\]|\d+)?C(\[-?\d+\]|\d+)?)/i);
  if (!m) return '';
  if (m[1]) return m[1];
  const v = String(((values[relIdx_(m[2], r)] || [])[relIdx_(m[3], c)]) || '');
  return /^https?:\/\//i.test(v) ? v : '';
}
function relIdx_(part, base) {
  if (part == null || part === '') return base;
  if (part.charAt(0) === '[') return base + Number(part.slice(1, -1));
  return Number(part) - 1;
}

function readStructure_(sh, nRows, nCols, ckey) {
  const rg = sh.getRange(1, 1, nRows, nCols);
  const lower = function (def) { return function (x) { x = String(x || '').toLowerCase(); return x && x !== def ? x : null; }; };
  const bg = runs_(rg.getBackgrounds(), nRows, nCols, lower('#ffffff'));
  const fc = runs_(rg.getFontColors(), nRows, nCols, lower('#000000'));
  const bold = runs_(rg.getFontWeights(), nRows, nCols, function (x) { return x === 'bold' ? 1 : null; });
  const dvHit = ckey ? cacheGet_('d2:' + ckey) : null;
  const lists = dvHit ? dvHit.lists : [], listIdx = {}, rangeCache = {};
  const dv = dvHit ? dvHit.dv : runs_(rg.getDataValidations(), nRows, nCols, function (v) {
    if (!v) return null;
    const spec = dvSpec_(v, rangeCache);
    if (!spec) return null;
    const sk = JSON.stringify(spec);
    if (!(sk in listIdx)) { listIdx[sk] = lists.length; lists.push(spec); }
    return listIdx[sk];
  });
  if (!dvHit && ckey) cachePut_('d2:' + ckey, { dv: dv, lists: lists }, 21600);
  const hiddenCols = [];
  for (let c = 1; c <= nCols; c++) if (sh.isColumnHiddenByUser(c)) hiddenCols.push(c - 1);
  const merges = rg.getMergedRanges().map(function (m) {
    return [m.getRow() - 1, m.getColumn() - 1, m.getNumRows(), m.getNumColumns()];
  });
  const st = { bg: bg, fc: fc, bold: bold, dv: dv, lists: lists, hiddenCols: hiddenCols, merges: merges,
    frozenRows: sh.getFrozenRows(), frozenCols: sh.getFrozenColumns() };
  st.sig = sig_(JSON.stringify(st));
  return st;
}

// 편집기에서 실행해 큰 탭 읽기 속도를 본다 (두 번째 실행은 캐시 효과)
function perfTest() {
  const t = Date.now();
  const r = read_('coferry', 'Product List', null);
  Logger.log('total ' + (Date.now() - t) + 'ms ' + JSON.stringify(r.ms) + ' size ' + JSON.stringify(r).length);
}

function dvSpec_(v, rangeCache) {
  const type = v.getCriteriaType(), args = v.getCriteriaValues();
  const T = SpreadsheetApp.DataValidationCriteria;
  if (type === T.VALUE_IN_LIST) return { t: 'list', items: (args[0] || []).map(String).slice(0, 300) };
  if (type === T.VALUE_IN_RANGE) {
    const range = args[0];
    if (!range) return null;
    const a1 = range.getSheet().getName() + '!' + range.getA1Notation();
    if (!(a1 in rangeCache)) {
      const seen = {}, items = [];
      range.getDisplayValues().forEach(function (row) {
        row.forEach(function (x) { if (x !== '' && !seen[x]) { seen[x] = 1; items.push(x); } });
      });
      rangeCache[a1] = items.slice(0, 500);
    }
    return { t: 'list', items: rangeCache[a1] };
  }
  if (type === T.CHECKBOX) {
    return { t: 'check', on: args.length ? String(args[0]) : 'TRUE', off: args.length > 1 ? String(args[1]) : 'FALSE' };
  }
  return null;
}

/* ── 쓰기 ── 수식 칸은 거부, 그 사이 다른 사람이 바꾼 칸은 충돌로 돌려보낸다 */
function write_(key, name, edits) {
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    const o = sheetOf_(key, name), sh = o.sh;
    const results = [], touchedRows = {};
    edits.slice(0, 200).forEach(function (e) {
      const r = Number(e.r), c = Number(e.c);
      if (!(r >= 1 && c >= 1)) { results.push({ r: r, c: c, ok: false, error: 'bad_cell' }); return; }
      const cell = sh.getRange(r, c);
      if (cell.getFormula()) { results.push({ r: r, c: c, ok: false, error: 'formula_cell' }); return; }
      const cur = cell.getDisplayValue();
      if (e.old != null && String(e.old) !== cur) {
        results.push({ r: r, c: c, ok: false, error: 'conflict', current: cur }); return;
      }
      cell.setValue(coerce_(cell, e.v));
      touchedRows[r] = true;
      results.push({ r: r, c: c, ok: true });
    });
    SpreadsheetApp.flush();
    cacheDel_('c2:' + cacheBase_(key, sh));
    const lastCol = sh.getLastColumn();
    const rows = {};
    Object.keys(touchedRows).forEach(function (r) {
      rows[r] = sh.getRange(Number(r), 1, 1, lastCol).getDisplayValues()[0];
    });
    return { ok: true, results: results, rows: rows, at: new Date().toISOString() };
  } finally {
    lock.releaseLock();
  }
}

// 오피스에서 입력한 글자를 그 칸의 원래 형식(숫자·날짜·체크박스)에 맞춰 넣는다. '='로 시작하면 수식이 아닌 글자로 넣는다.
function coerce_(cell, input) {
  const s = input == null ? '' : String(input);
  if (s === '') return '';
  if (s.charAt(0) === '=') return "'" + s;
  const raw = cell.getValue();
  if (typeof raw === 'boolean') {
    if (/^(true|1|y|yes|o|✓)$/i.test(s)) return true;
    if (/^(false|0|n|no|x)$/i.test(s)) return false;
  }
  if (raw instanceof Date) {
    const m = s.match(/^(\d{4})\s*[.\-\/]\s*(\d{1,2})\s*[.\-\/]\s*(\d{1,2})/);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }
  const t = s.replace(/[,\s₩￦원]/g, '');
  if (/^-?\d+(\.\d+)?%$/.test(t)) return parseFloat(t) / 100;
  if (/^-?\d+(\.\d+)?$/.test(t) && !/^0\d/.test(t)) return parseFloat(t);
  return s;
}

/* ── 2026-10-27 로직 점검에서 찾은 수식 오류 3건 수정 ──
 * 정해진 세 가지만 고치고, 지금 수식이 "고장 난 모양" 그대로일 때만 바꾼다 → 여러 번 돌려도 안전하다.
 * 웹에서는 action=audit_fix (apply 없으면 미리보기만), 편집기에서는 fixAuditErrors 를 실행하면 바로 적용된다.
 *  1) 코즈미 [50%할인이벤트] C열: 지워진 칸 참조(=#REF!*9.5) → =B×9.5 (공급가×9.5, Product List 공홈 최저 판매가와 같은 규칙)
 *  2) 아페티 [플랫폼 세트] K·L열: 다른 행의 플랫폼 최저가($J윗행)로 마진율을 계산한 칸 → 자기 행 $J
 *  3) 에이블리 가격표 [아페티] H열: =G×0.85 인데 G(세트 할인가)가 비면 0이 되는 칸 → G가 비면 F(최종 판매가)로
 *     babyB16400 이면 Baby-B 의 비어 있는 G 칸에 Baby-A 와 같은 세트 할인가 16,400 을 넣는다
 */
function fixAuditErrors() {
  const r = auditFix_(false, false);
  Logger.log(JSON.stringify(r, null, 2));
  return r;
}

function auditFix_(dry, babyB16400) {
  const out = { ok: true, dry: dry, changes: [], at: new Date().toISOString() };
  const note = function (book, sheet, a1, before, after) { out.changes.push({ book: book, sheet: sheet, cell: a1, before: before, after: after }); };

  // 1) 코즈미 50%할인이벤트 C열 — 연속된 #REF! 구간 단위로 한 번에 넣는다 (수백 칸)
  (function () {
    const sh = openBook_('kozmi').getSheetByName('50%할인이벤트');
    if (!sh || sh.getLastRow() < 2) return;
    const n = sh.getLastRow() - 1;
    const fs = sh.getRange(2, 3, n, 1).getFormulas();
    let runStart = -1;
    const flush = function (endIdx) {
      if (runStart < 0) return;
      const from = runStart + 2, to = endIdx + 1, rows = [];
      for (let r = from; r <= to; r++) rows.push(['=B' + r + '*9.5']);
      note('kozmi', '50%할인이벤트', 'C' + from + ':C' + to, '=#REF!*9.5', '=B' + from + '*9.5 … (' + rows.length + '칸)');
      if (!dry) sh.getRange(from, 3, rows.length, 1).setFormulas(rows);
      runStart = -1;
    };
    for (let i = 0; i < n; i++) {
      if (/^=#REF!\*9\.5$/i.test(fs[i][0])) { if (runStart < 0) runStart = i; }
      else flush(i);
    }
    flush(n);
  })();

  // 2) 아페티 플랫폼 세트 K(에이블리)·L(지그재그) 마진율 — $J 가 자기 행이 아닌 칸
  (function () {
    const sh = openBook_('apeti').getSheetByName('플랫폼 세트');
    if (!sh || sh.getLastRow() < 2) return;
    const n = sh.getLastRow() - 1;
    const fs = sh.getRange(2, 11, n, 2).getFormulas();
    for (let i = 0; i < n; i++) {
      const row = i + 2;
      for (let k = 0; k < 2; k++) {
        const f = fs[i][k];
        const refs = (f.match(/\$J(\d+)/g) || []).map(function (x) { return Number(x.slice(2)); });
        if (!refs.length || refs.every(function (x) { return x === row; })) continue;
        const after = f.replace(/\$J\d+/g, '$J' + row);
        note('apeti', '플랫폼 세트', (k ? 'L' : 'K') + row, f, after);
        if (!dry) sh.getRange(row, 11 + k).setFormula(after);
      }
    }
  })();

  // 3) 에이블리 가격표 아페티 H열 — =G×0.85 (세트 할인가 기준) 칸에 G 가 비었을 때 F 로 대신 계산
  (function () {
    const sh = openBook_('ably_price').getSheetByName('아페티');
    if (!sh || sh.getLastRow() < 2) return;
    const n = sh.getLastRow() - 1;
    const rg = sh.getRange(2, 5, n, 4); // E(옵션명) F G H
    const fs = rg.getFormulas(), vs = rg.getDisplayValues();
    for (let i = 0; i < n; i++) {
      const row = i + 2, f = fs[i][3];
      const m = f.match(/^=G(\d+)\*0\.85$/i);
      if (!m || Number(m[1]) !== row) continue;
      if (babyB16400 && vs[i][0] === 'Baby-B' && vs[i][2] === '') {
        note('ably_price', '아페티', 'G' + row, '(빈칸)', '16400');
        if (!dry) sh.getRange(row, 7).setValue(16400);
      }
      const after = '=IF(G' + row + '="",F' + row + ',G' + row + ')*0.85';
      note('ably_price', '아페티', 'H' + row, f, after);
      if (!dry) sh.getRange(row, 8).setFormula(after);
    }
  })();

  if (!dry) SpreadsheetApp.flush();
  return out;
}
