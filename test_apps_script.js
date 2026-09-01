/**
 * Подставное окружение Google Apps Script — чтобы прогнать apps_script.gs
 * обычным node и убедиться, что логика верна ДО заливки в таблицу.
 * Запуск:  node test_apps_script.js
 *
 * Редакция 01.09.2026: вкладки-воронка («Новые», «Согласен», «Отказ»,
 * «Зарегистрирован»), отдельная вкладка «Без ника», колонка «Тип продавца»
 * убрана, неудача = пустая ячейка с примечанием.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// ─────────────── заглушки Google ───────────────
function makeSheet(name, maxRows, maxCols) {
  const grid = [];
  const notes = [];   // примечания к ячейкам: notes[row-1][col-1]
  const sheet = {
    _name: name,
    _grid: grid,
    _notes: notes,
    _maxRows: maxRows || 1000,
    _maxCols: maxCols || 26,
    _rules: [],
    getName() { return this._name; },
    setName(n) { this._name = n; },
    getMaxRows() { return this._maxRows; },
    getMaxColumns() { return this._maxCols; },
    insertColumnsAfter(after, howMany) { this._maxCols += howMany; },
    setFrozenRows() {},
    setConditionalFormatRules(r) { this._rules = r; },
    getLastRow() {
      let last = 0;
      for (let i = 0; i < grid.length; i++) {
        const row = grid[i] || [];
        if (row.some((c) => String(c == null ? '' : c) !== '')) last = i + 1;
      }
      return last;
    },
    getLastColumn() {
      let last = 0;
      for (const row of grid) {
        if (!row) continue;
        for (let c = 0; c < row.length; c++) {
          if (String(row[c] == null ? '' : row[c]) !== '') last = Math.max(last, c + 1);
        }
      }
      return last;
    },
    appendRow(values) {
      const r = this.getLastRow();
      grid[r] = values.slice();
    },
    deleteRow(row) { grid.splice(row - 1, 1); notes.splice(row - 1, 1); },
    getRange(row, col, nRows, nCols) {
      nRows = nRows === undefined ? 1 : nRows;
      nCols = nCols === undefined ? 1 : nCols;
      const sh = this;
      return {
        getValues() {
          const out = [];
          for (let i = 0; i < nRows; i++) {
            const line = [];
            const src = grid[row - 1 + i] || [];
            for (let j = 0; j < nCols; j++) {
              const v = src[col - 1 + j];
              line.push(v === undefined || v === null ? '' : v);
            }
            out.push(line);
          }
          return out;
        },
        setValues(vals) {
          if (vals.length !== nRows || vals[0].length !== nCols) {
            throw new Error(
              `setValues: размер не совпал (${vals.length}x${vals[0].length} ` +
              `против ${nRows}x${nCols}) на листе «${sh._name}»`);
          }
          for (let i = 0; i < nRows; i++) {
            if (!grid[row - 1 + i]) grid[row - 1 + i] = [];
            for (let j = 0; j < nCols; j++) grid[row - 1 + i][col - 1 + j] = vals[i][j];
          }
        },
        getNotes() {
          const out = [];
          for (let i = 0; i < nRows; i++) {
            const line = [];
            const src = notes[row - 1 + i] || [];
            for (let j = 0; j < nCols; j++) line.push(src[col - 1 + j] || '');
            out.push(line);
          }
          return out;
        },
        setNotes(vals) {
          if (vals.length !== nRows || vals[0].length !== nCols) {
            throw new Error(`setNotes: размер не совпал на листе «${sh._name}»`);
          }
          for (let i = 0; i < nRows; i++) {
            if (!notes[row - 1 + i]) notes[row - 1 + i] = [];
            for (let j = 0; j < nCols; j++) notes[row - 1 + i][col - 1 + j] = vals[i][j];
          }
        },
        setNote(v) { this.setNotes([[v]]); },
        getNote() { return this.getNotes()[0][0]; },
        clearNote() {
          for (let i = 0; i < nRows; i++) {
            if (!notes[row - 1 + i]) continue;
            for (let j = 0; j < nCols; j++) notes[row - 1 + i][col - 1 + j] = '';
          }
        },
        clearContent() {
          for (let i = 0; i < nRows; i++) {
            if (!grid[row - 1 + i]) continue;
            for (let j = 0; j < nCols; j++) grid[row - 1 + i][col - 1 + j] = '';
          }
        },
        setValue(v) { this.setValues([[v]]); },
        getValue() { return this.getValues()[0][0]; },
        getSheet() { return sh; },
        getRow() { return row; },
        getLastRow() { return row + nRows - 1; },
        getColumn() { return col; },
        getLastColumn() { return col + nCols - 1; },
        setDataValidation() {},
      };
    },
  };
  return sheet;
}

const SS = {
  _sheets: [],
  toast(msg) { console.log('   toast:', msg); },
  getSheetByName(n) { return this._sheets.find((s) => s.getName() === n) || null; },
  insertSheet(n, pos) {
    const sh = makeSheet(n);
    this._sheets.splice(pos === undefined ? this._sheets.length : pos, 0, sh);
    return sh;
  },
  deleteSheet(sh) {
    const i = this._sheets.indexOf(sh);
    if (i !== -1) this._sheets.splice(i, 1);
  },
  getSheets() { return this._sheets.slice(); },
};

function builder(obj) { return obj; }
const SpreadsheetApp = {
  getActiveSpreadsheet: () => SS,
  getActive: () => SS,
  newDataValidation: () => {
    const b = {};
    b.requireValueInList = () => b;
    b.setAllowInvalid = () => b;
    b.build = () => ({});
    return builder(b);
  },
  newConditionalFormatRule: () => {
    const rule = {};
    const b = {};
    b.whenFormulaSatisfied = (f) => { rule.formula = f; return b; };
    b.setBackground = (c) => { rule.bg = c; return b; };
    b.setFontColor = (c) => { rule.fc = c; return b; };
    b.setRanges = (r) => { rule.ranges = r; return b; };
    b.build = () => rule;
    return builder(b);
  },
};
const ContentService = {
  MimeType: { JSON: 'json' },
  createTextOutput: (t) => ({ _t: t, setMimeType() { return this; }, getContent() { return t; } }),
};

// ─────────────── загрузка скрипта ───────────────
const src = fs.readFileSync(path.join(__dirname, 'apps_script.gs'), 'utf8');
const ctx = vm.createContext({ SpreadsheetApp, ContentService, console, JSON, String, Math, Object, Date });
vm.runInContext(src, ctx);
ctx.TOKEN = 'T';

// ─────────────── помощники теста ───────────────
let failed = 0;
function check(name, cond, extra) {
  if (cond) { console.log('  ✅ ' + name); } else {
    failed++;
    console.log('  ❌ ' + name + (extra ? '\n       ' + extra : ''));
  }
}
function post(body) {
  const r = vm.runInContext('doPost', ctx)({ postData: { contents: JSON.stringify(body) } });
  return JSON.parse(r._t);
}
function get(params) {
  const r = vm.runInContext('doGet', ctx)({ parameter: params });
  return JSON.parse(r._t);
}
const NEW = 'Новые';
const AGREED = 'Согласен';
const REFUSED = 'Отказ';
const REGISTERED = 'Зарегистрирован';
const NONICK = 'Без ника';
const AG = 'Недвижимость — агентства';
const CONSENT = 'Согласия';
const COLS = 9;

function dump(tab) {
  const sh = SS.getSheetByName(tab);
  if (!sh) return [];
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, COLS).getValues().filter((r) => String(r[1] || '') !== '');
}
function noteOf(tab, link) {
  const sh = SS.getSheetByName(tab);
  const last = sh.getLastRow();
  if (last < 2) return '';
  const vals = sh.getRange(2, 1, last - 1, COLS).getValues();
  const notes = sh.getRange(2, 9, last - 1, 1).getNotes();
  for (let i = 0; i < vals.length; i++) {
    if (String(vals[i][1]) === link) return String(notes[i][0] || '');
  }
  return '';
}
function findRow(link) {
  for (const tab of [NEW, AGREED, REFUSED, REGISTERED, NONICK, AG]) {
    const row = dump(tab).find((r) => r[1] === link);
    if (row) return { tab, row };
  }
  return null;
}
function row(link) { const f = findRow(link); return f ? f.row : null; }
function tabOf(link) { const f = findRow(link); return f ? f.tab : null; }
function dumpConsent() {
  const sh = SS.getSheetByName(CONSENT);
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, 4).getValues().filter((r) => String(r[0] || '') !== '');
}

// ─────────────── сценарии ───────────────
console.log('\n1. Первая запись: строки сразу ложатся на нужные вкладки');
let res = post({
  token: 'T', action: 'append', rows: [
    { author: 'ivan', link: 'https://t.me/g/1', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-17 10:00', snippet: 'Айфон', seller_type: 'частник' },
    { author: 'ivan', link: 'https://t.me/g/2', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-17 10:05', snippet: 'Макбук', seller_type: 'частник' },
    { author: '', link: 'https://t.me/g/3', channel: 'Барахолка', category: 'Мебель', category_slug: 'home', date: '2026-08-17 10:10', snippet: 'Диван', seller_type: 'частник' },
    { author: 'pattaya_realty', link: 'https://t.me/g/4', channel: 'Аренда', category: 'Недвижимость', category_slug: 'realty', date: '2026-08-17 10:15', snippet: 'Кондо', seller_type: 'бизнес' },
    { author: 'oleg', link: 'https://t.me/g/5', channel: 'Аренда', category: 'Недвижимость', category_slug: 'realty', date: '2026-08-17 10:20', snippet: 'Своя студия', seller_type: 'частник' },
  ],
});
check('записано 5 строк', res.written === 5, JSON.stringify(res));
check('у Ивана ДВЕ строки во «Новых»', dump(NEW).filter((r) => r[0] === 'ivan').length === 2);
check('объявление без ника уехало на «Без ника»',
  tabOf('https://t.me/g/3') === NONICK, String(tabOf('https://t.me/g/3')));
check('во «Новых» строк без ника нет', dump(NEW).every((r) => String(r[0] || '') !== ''));
check('агентство недвижимости — на своей вкладке',
  dump(AG).length === 1 && dump(AG)[0][0] === 'pattaya_realty');
check('частник с недвижимостью остался в «Новых»', tabOf('https://t.me/g/5') === NEW);
check('колонок ровно 9, «Тип продавца» больше нет',
  SS.getSheetByName(NEW).getRange(1, 1, 1, 10).getValues()[0][9] === '' &&
  SS.getSheetByName(NEW).getRange(1, 1, 1, 9).getValues()[0][8] === 'На сайте');
check('«Написали?» по умолчанию Нет', dump(NEW).every((r) => r[6] === 'Нет'));
check('«Присутствие» и «На сайте» пустые', dump(NEW).every((r) => r[7] === '' && r[8] === ''));

console.log('\n2. Дубль по ссылке не проходит');
res = post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/1', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-18 09:00', snippet: 'Айфон снова', seller_type: 'частник' },
  { author: 'ivan', link: 'https://t.me/g/6', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-18 09:01', snippet: 'Наушники', seller_type: 'частник' },
] });
check('добавилась только новая ссылка', res.written === 1, JSON.stringify(res));
check('у Ивана стало три строки', dump(NEW).filter((r) => r[0] === 'ivan').length === 3);

console.log('\n3. «Написали?» ставится ВСЕМ строкам человека и вкладку не меняет');
res = post({ token: 'T', action: 'mark', author: '@Ivan', value: 'Да' });
check('поправлено три строки', res.found === 3, JSON.stringify(res));
check('у всех строк Ивана «Да»', dump(NEW).filter((r) => r[0] === 'ivan').every((r) => r[6] === 'Да'));
check('Иван остался во «Новых»', tabOf('https://t.me/g/1') === NEW);
check('чужие строки не тронуты', dump(NEW).filter((r) => r[0] === 'oleg').every((r) => r[6] === 'Нет'));

console.log('\n4. Новое объявление написанного человека рождается с «Да»');
post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/7', channel: 'Барахолка', category: 'Спорт', category_slug: 'sport', date: '2026-08-19 09:00', snippet: 'Велосипед', seller_type: 'частник' },
] });
check('новая строка унаследовала «Да»', row('https://t.me/g/7')[6] === 'Да');

console.log('\n5. Смена «Присутствия» ПЕРЕВОЗИТ строки на другую вкладку');
res = post({ token: 'T', action: 'presence', author: 'ivan', value: 'согласен' });
check('присутствие проставлено всем строкам Ивана', res.found === 4, JSON.stringify(res));
check('все четыре строки переехали во вкладку «Согласен»',
  dump(AGREED).filter((r) => r[0] === 'ivan').length === 4, JSON.stringify(res));
check('во «Новых» Ивана больше нет', dump(NEW).every((r) => r[0] !== 'ivan'));
check('«Написали?» при переезде не потерялось',
  dump(AGREED).every((r) => r[6] === 'Да' && r[7] === 'согласен'));
check('чужие строки на месте', tabOf('https://t.me/g/5') === NEW);
post({ token: 'T', action: 'presence', author: 'oleg', value: 'ерунда' });
check('мусорное значение присутствия не пишется и не возит', tabOf('https://t.me/g/5') === NEW);

console.log('\n6. Новое объявление согласившегося сразу рождается во вкладке «Согласен»');
post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/8', channel: 'Барахолка', category: 'Спорт', category_slug: 'sport', date: '2026-08-19 10:00', snippet: 'Лыжи', seller_type: 'частник' },
] });
check('сразу в «Согласен»', tabOf('https://t.me/g/8') === AGREED, String(tabOf('https://t.me/g/8')));

console.log('\n7. «На сайте» — три состояния, неудача = пусто + примечание');
res = post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'Ждёт модератора' });
check('успех записан', row('https://t.me/g/1')[8] === 'Ждёт модератора', JSON.stringify(res));
post({ token: 'T', action: 'site', link: 'https://t.me/g/2', value: '', note: 'нет фотографий' });
check('неудача оставляет поле ПУСТЫМ', row('https://t.me/g/2')[8] === '');
check('причина спрятана в примечании', noteOf(AGREED, 'https://t.me/g/2') === 'нет фотографий');
check('у соседнего объявления примечания нет', noteOf(AGREED, 'https://t.me/g/8') === '');
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'В каталоге' });
check('старое «В каталоге» превращается в «На сайте»', row('https://t.me/g/1')[8] === 'На сайте');
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'Удалено' });
check('старое «Удалено» превращается в «Снято»', row('https://t.me/g/1')[8] === 'Снято');
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'Не вышло' });
check('старое «Не вышло» превращается в пустое поле', row('https://t.me/g/1')[8] === '');
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'абракадабра' });
check('мусорное значение = пусто', row('https://t.me/g/1')[8] === '');

console.log('\n8. Очередь авто-подготовки');
let todo = get({ action: 'todo', token: 'T' }).rows;
const todoLinks = todo.map((r) => r.link);
check('в очередь попали только согласившиеся', todo.every((r) => r.nick === 'ivan'), JSON.stringify(todo));
check('строка с примечанием-неудачей в очередь НЕ попала',
  todoLinks.indexOf('https://t.me/g/2') === -1, JSON.stringify(todoLinks));
check('строка без пометки в очереди есть', todoLinks.indexOf('https://t.me/g/8') !== -1);
check('todo с чужим токеном', get({ action: 'todo', token: 'X' }).ok === false);
check('limit урезает очередь', get({ action: 'todo', token: 'T', limit: '1' }).rows.length === 1);
const clr = vm.runInContext('clearFailNotes', ctx)();
check('«Очистить пометки неудач» вернула строку в очередь',
  clr.cleared === 1 &&
  get({ action: 'todo', token: 'T' }).rows.some((r) => r.link === 'https://t.me/g/2'),
  JSON.stringify(clr));

console.log('\n9. Реестр согласий и переезд по нему');
res = post({ token: 'T', action: 'consent', nick: '@Ivan', status: 'зарегистрирован', reason: 'вошёл через Telegram' });
check('запись в реестре появилась', dumpConsent().length === 1 && dumpConsent()[0][0] === 'ivan', JSON.stringify(dumpConsent()));
check('дата проставлена', /^\d{4}-\d{2}-\d{2}$/.test(String(dumpConsent()[0][2])));
check('все строки Ивана уехали в «Зарегистрирован»',
  dump(REGISTERED).filter((r) => r[0] === 'ivan').length === 5 && dump(AGREED).length === 0,
  JSON.stringify(res));
check('примечание пережило переезд', noteOf(REGISTERED, 'https://t.me/g/2') === '');
post({ token: 'T', action: 'site', link: 'https://t.me/g/2', value: '', note: 'нет фотографий' });
post({ token: 'T', action: 'consent', nick: 'ivan', status: 'отказ', reason: 'попросил не писать' });
check('после отказа строки в «Отказ»', dump(REFUSED).filter((r) => r[0] === 'ivan').length === 5);
check('примечание переехало вместе со строкой',
  noteOf(REFUSED, 'https://t.me/g/2') === 'нет фотографий');
res = post({ token: 'T', action: 'consent', nick: 'ivan', status: 'согласен', reason: 'сайт опубликовал ещё одно' });
check('отказ автоматикой не снимается', dumpConsent()[0][1] === 'отказ' && res.kept === true, JSON.stringify(res));
check('строки остались в «Отказ»', dump(REFUSED).filter((r) => r[0] === 'ivan').length === 5);
check('отказавшийся в очередь не попадает',
  get({ action: 'todo', token: 'T' }).rows.length === 0);

console.log('\n10. Ночная сверка: placed / nicks / пакеты');
let placed = get({ action: 'placed', token: 'T' }).rows;
check('размещённые отдаются со ссылкой и статусом', Array.isArray(placed), JSON.stringify(placed));
check('пустые ячейки в сверку не идут', placed.every((r) => String(r.site || '') !== ''));
post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/8', value: 'На сайте' }] });
check('пакетная запись работает', row('https://t.me/g/8')[8] === 'На сайте');
check('повторная запись того же ничего не меняет',
  post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/8', value: 'На сайте' }] }).updated === 0);
res = post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/8', value: '', note: 'снял продавец' }] });
check('пакетом можно поставить и пустое с примечанием',
  row('https://t.me/g/8')[8] === '' && noteOf(REFUSED, 'https://t.me/g/8') === 'снял продавец', JSON.stringify(res));
const nicks = get({ action: 'nicks', token: 'T' }).nicks;
check('ники со всех вкладок, без повторов',
  nicks.indexOf('ivan') !== -1 && nicks.indexOf('pattaya_realty') !== -1 &&
  nicks.length === new Set(nicks).size, JSON.stringify(nicks));
const st = get({ action: 'statuses', token: 'T' }).statuses;
check('статусы собираются со всех вкладок', st.ivan === 'Да' && st.oleg === 'Нет', JSON.stringify(st));

console.log('\n11. Чужой токен отбивается');
check('append с чужим токеном', post({ token: 'X', action: 'append', rows: [] }).ok === false);
check('statuses с чужим токеном', get({ action: 'statuses', token: 'X' }).ok === false);
check('consent с чужим токеном', post({ token: 'X', action: 'consent', nick: 'a', status: 'согласен' }).ok === false);
check('alive работает без токена', get({}).alive === true);

console.log('\n12. Ручная правка «Присутствия» разносит статус и перевозит строки');
SS._sheets.length = 0;
post({ token: 'T', action: 'append', rows: [
  { author: 'anna', link: 'https://t.me/a/1', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:00', snippet: 'Стол', seller_type: 'частник' },
  { author: 'anna', link: 'https://t.me/a/2', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:05', snippet: 'Стул', seller_type: 'частник' },
  { author: 'anna', link: 'https://t.me/a/3', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:10', snippet: 'Шкаф', seller_type: 'частник' },
  { author: 'boris', link: 'https://t.me/a/4', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:15', snippet: 'Диван', seller_type: 'частник' },
] });
function rowsOf(nick) {
  const out = [];
  for (const tab of [NEW, AGREED, REFUSED, REGISTERED, NONICK, AG]) {
    for (const r of dump(tab)) if (r[0] === nick) out.push({ tab, r });
  }
  return out;
}
function editPresence(tab, nick, value) {
  const sh = SS.getSheetByName(tab);
  const all = dump(tab);
  const idx = all.findIndex((r) => r[0] === nick);
  const range = sh.getRange(idx + 2, 8);
  range.setValue(value);
  vm.runInContext('onEdit', ctx)({ range });
}
editPresence(NEW, 'anna', 'согласен');
check('значение разошлось по всем строкам ника',
  rowsOf('anna').length === 3 && rowsOf('anna').every((x) => x.r[7] === 'согласен'),
  JSON.stringify(rowsOf('anna')));
check('и все три строки переехали в «Согласен»',
  rowsOf('anna').every((x) => x.tab === AGREED));
check('чужая строка осталась во «Новых»',
  rowsOf('boris').every((x) => x.tab === NEW && x.r[7] === ''));
check('появилась запись в реестре',
  (dumpConsent().find((r) => r[0] === 'anna') || [])[1] === 'согласен', JSON.stringify(dumpConsent()));

// Ручная правка СИЛЬНЕЕ автоматики.
post({ token: 'T', action: 'consent', nick: 'anna', status: 'отказ', reason: 'сказала стоп' });
check('автоматика увезла в «Отказ»', rowsOf('anna').every((x) => x.tab === REFUSED));
editPresence(REFUSED, 'anna', 'согласен');
check('ручная правка перебивает отказ и возвращает во «Согласен»',
  rowsOf('anna').every((x) => x.tab === AGREED && x.r[7] === 'согласен') &&
  (dumpConsent().find((r) => r[0] === 'anna') || [])[1] === 'согласен',
  JSON.stringify(rowsOf('anna')));

// Очистка ячейки = человек снова «чистый», строки уезжают в «Новые».
editPresence(AGREED, 'anna', '');
check('пустое значение вернуло строки во «Новые»',
  rowsOf('anna').length === 3 && rowsOf('anna').every((x) => x.tab === NEW && String(x.r[7] || '') === ''),
  JSON.stringify(rowsOf('anna')));
check('запись из реестра удалена', !dumpConsent().some((r) => r[0] === 'anna'));

// Опечатку не разносим и не возим.
editPresence(NEW, 'anna', 'сагласен');
check('мусорное значение остаётся в одной ячейке и никуда не едет',
  rowsOf('anna').filter((x) => x.r[7] === 'сагласен').length === 1 &&
  rowsOf('anna').every((x) => x.tab === NEW));
editPresence(NEW, 'anna', '');

// «Нет ответа» — это тоже вкладка «Новые».
editPresence(NEW, 'anna', 'нет ответа');
check('«нет ответа» оставляет строки во «Новых»',
  rowsOf('anna').every((x) => x.tab === NEW && x.r[7] === 'нет ответа'));

// «Написали?» вкладку не меняет.
function editWritten(tab, nick, value) {
  const sh = SS.getSheetByName(tab);
  const all = dump(tab);
  const idx = all.findIndex((r) => r[0] === nick);
  const range = sh.getRange(idx + 2, 7);
  range.setValue(value);
  vm.runInContext('onEdit', ctx)({ range });
}
editWritten(NEW, 'anna', 'Да');
check('«Написали? = Да» разошлось по всем строкам ника',
  rowsOf('anna').every((x) => x.r[6] === 'Да' && x.tab === NEW));
check('реестр согласий от «Написали?» не меняется', !dumpConsent().some((r) => r[0] === 'anna'));

// Правка в чужой колонке триггер не будит.
const other = SS.getSheetByName(NEW).getRange(2, 6);
other.setValue('какое-то описание');
vm.runInContext('onEdit', ctx)({ range: other });
check('правка другой колонки ничего не разносит',
  rowsOf('anna').every((x) => x.r[7] === 'нет ответа'));

console.log('\n13. Миграция старой единой вкладки «CRM»');
SS._sheets.length = 0;
const old = makeSheet('CRM', 1000, 10);
old.appendRow(['Ник', 'Ссылка', 'Канал', 'Категория', 'Дата', 'Описание',
               'Написали?', 'Присутствие', 'На сайте', 'Тип продавца']);
old.appendRow(['petr', 'https://t.me/o/1', 'Барахолка', 'Электроника', '2026-07-01', 'Телефон', 'Да', '', 'В каталоге', 'частник']);
old.appendRow(['maria', 'https://t.me/o/2', 'Барахолка', 'Мебель', '2026-07-02', 'Стол', 'Нет', 'согласен', 'Не вышло', 'частник']);
old.appendRow(['sergey', 'https://t.me/o/3', 'Барахолка', 'Авто', '2026-07-03', 'Байк', 'Премиум', 'отказ', 'Удалено', 'бизнес']);
old.appendRow(['', 'https://t.me/o/4', 'Барахолка', 'Мебель', '2026-07-04', 'Диван', 'Нет', '', '', 'частник']);
old.appendRow(['zina', 'https://t.me/o/5', 'Барахолка', 'Спорт', '2026-07-05', 'Мяч', 'Нет', 'зарегистрирован', '', 'частник']);
old.appendRow(['klim', 'https://t.me/o/6', 'Барахолка', 'Спорт', '2026-07-06', 'Ролики', 'Да', 'нет ответа', '', 'частник']);
SS._sheets.push(old);

const mig = vm.runInContext('migrateTabs', ctx)();
check('перенесено шесть строк', mig.moved === 6, JSON.stringify(mig));
check('пустое «Присутствие» → «Новые»', tabOf('https://t.me/o/1') === NEW);
check('«согласен» → «Согласен»', tabOf('https://t.me/o/2') === AGREED);
check('«отказ» → «Отказ»', tabOf('https://t.me/o/3') === REFUSED);
check('без ника → «Без ника»', tabOf('https://t.me/o/4') === NONICK);
check('«зарегистрирован» → «Зарегистрирован»', tabOf('https://t.me/o/5') === REGISTERED);
check('«нет ответа» → «Новые»', tabOf('https://t.me/o/6') === NEW);
check('«В каталоге» стало «На сайте»', row('https://t.me/o/1')[8] === 'На сайте');
check('«Удалено» стало «Снято»', row('https://t.me/o/3')[8] === 'Снято');
check('«Не вышло» стало пустым полем', row('https://t.me/o/2')[8] === '');
check('но причина осталась в примечании',
  noteOf(AGREED, 'https://t.me/o/2').indexOf('Не вышло') !== -1,
  noteOf(AGREED, 'https://t.me/o/2'));
check('строка с бывшим «Не вышло» в очередь не встаёт',
  get({ action: 'todo', token: 'T' }).rows.every((r) => r.link !== 'https://t.me/o/2'));
check('колонка «Тип продавца» не перенесена',
  dump(NEW).every((r) => r.length === 9));
check('«Написали?» сохранено', row('https://t.me/o/1')[6] === 'Да' && row('https://t.me/o/3')[6] === 'Премиум');
check('старая вкладка переименована в архив',
  !SS.getSheetByName('CRM') && !!SS.getSheetByName('архив_CRM'));

console.log('\n14. Миграция повторно — ничего не задваивает');
SS.getSheetByName('архив_CRM').setName('CRM');
const mig2 = vm.runInContext('migrateTabs', ctx)();
check('второй прогон переносит ноль строк', mig2.moved === 0, JSON.stringify(mig2));
check('строк по-прежнему шесть',
  dump(NEW).length + dump(AGREED).length + dump(REFUSED).length +
  dump(REGISTERED).length + dump(NONICK).length === 6);

console.log('\n15. Удаление архивных вкладок');
SS._sheets.push(makeSheet('архив_Барахолка Паттайя', 100, 6));
SS._sheets.push(makeSheet('архив_Паттайя объявления', 100, 6));
const drop = vm.runInContext('dropArchiveTabs', ctx)();
check('удалены все три архива (CRM + две по группам)', drop.deleted === 3, JSON.stringify(drop));
check('рабочие вкладки на месте',
  !!SS.getSheetByName(NEW) && !!SS.getSheetByName(AGREED) && !!SS.getSheetByName(NONICK) &&
  !!SS.getSheetByName(CONSENT));
check('повторный запуск ничего не находит',
  vm.runInContext('dropArchiveTabs', ctx)().deleted === 0);

console.log('\n16. Пересчёт по реестру + ручная раскладка');
SS.getSheetByName(CONSENT).appendRow(['petr', 'согласен', '2026-08-19', 'выгрузка из базы']);
const sync = vm.runInContext('syncConsents', ctx)();
check('пересчёт нашёл людей и увёз Петра', sync.people >= 1 && tabOf('https://t.me/o/1') === AGREED,
  JSON.stringify(sync));
check('повторный пересчёт ничего не меняет',
  vm.runInContext('syncConsents', ctx)().touched === 0);
check('ручная раскладка тоже говорит «переезжать некому»',
  vm.runInContext('resortTabs', ctx)().moved === 0);

console.log(failed === 0 ? '\n🏁 ВСЁ ЗЕЛЁНОЕ\n' : `\n⛔ ПРОВАЛЕНО ПРОВЕРОК: ${failed}\n`);
process.exit(failed === 0 ? 0 : 1);
