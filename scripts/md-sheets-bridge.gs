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
      case 'read':  return json_(read_(p.book, p.sheet));
      case 'write': return json_(write_(p.book, p.sheet, p.edits || []));
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
  const sh = allowedSheets_(ss).filter(function (s) { return s.getName() === name; })[0];
  if (!sh) throw new Error('sheet_not_allowed');
  return { ss: ss, sh: sh };
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

/* ── 읽기 ── 표시값 + 수식 + 서식(배경·글자색·굵게) + 드롭다운 + 병합 + 열 너비 */
function read_(key, name) {
  const o = sheetOf_(key, name), sh = o.sh;
  const lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (!lastRow || !lastCol) return { ok: true, rows: 0, cols: 0, values: [], at: new Date().toISOString() };
  const nRows = Math.min(lastRow, MAX_ROWS);
  const rg = sh.getRange(1, 1, nRows, lastCol);

  const values = rg.getDisplayValues();
  const formulas = rg.getFormulas();
  const bgs = rg.getBackgrounds();
  const fcs = rg.getFontColors();
  const fws = rg.getFontWeights();
  const dvs = rg.getDataValidations();

  const f = {}, bg = {}, fc = {}, bold = [], dv = {}, lists = [], listIdx = {}, rangeCache = {};
  for (let r = 0; r < nRows; r++) {
    for (let c = 0; c < lastCol; c++) {
      const k = r + ',' + c;
      if (formulas[r][c]) f[k] = formulas[r][c];
      const b = String(bgs[r][c] || '').toLowerCase();
      if (b && b !== '#ffffff') bg[k] = b;
      const t = String(fcs[r][c] || '').toLowerCase();
      if (t && t !== '#000000') fc[k] = t;
      if (fws[r][c] === 'bold') bold.push(k);
      const v = dvs[r][c];
      if (v) {
        const spec = dvSpec_(v, rangeCache);
        if (spec) {
          const sk = JSON.stringify(spec);
          if (!(sk in listIdx)) { listIdx[sk] = lists.length; lists.push(spec); }
          dv[k] = listIdx[sk];
        }
      }
    }
    // 뒤쪽 빈칸은 잘라서 전송량을 줄인다
    let end = values[r].length;
    while (end > 0 && values[r][end - 1] === '') end--;
    values[r] = values[r].slice(0, end);
  }

  const widths = [], hiddenCols = [];
  for (let c = 1; c <= lastCol; c++) {
    widths.push(sh.getColumnWidth(c));
    if (sh.isColumnHiddenByUser(c)) hiddenCols.push(c - 1);
  }
  const merges = rg.getMergedRanges().map(function (m) {
    return [m.getRow() - 1, m.getColumn() - 1, m.getNumRows(), m.getNumColumns()];
  });

  return {
    ok: true, rows: nRows, cols: lastCol, totalRows: lastRow, truncated: lastRow > nRows,
    frozenRows: sh.getFrozenRows(), frozenCols: sh.getFrozenColumns(),
    values: values, f: f, bg: bg, fc: fc, bold: bold, dv: dv, lists: lists,
    widths: widths, hiddenCols: hiddenCols, merges: merges,
    gid: sh.getSheetId(), at: new Date().toISOString(),
  };
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
