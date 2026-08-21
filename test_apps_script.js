/**
 * Подставное окружение Google Apps Script — чтобы прогнать apps_script.gs
 * обычным node и убедиться, что логика верна ДО заливки в таблицу.
 * Запуск:  node test_apps_script.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// ─────────────── заглушки Google ───────────────
function makeSheet(name, maxRows, maxCols) {
  const grid = [];
  const sheet = {
    _name: name,
    _grid: grid,
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
    deleteRow(row) { grid.splice(row - 1, 1); },
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
function dump(tab) {
  const sh = SS.getSheetByName(tab);
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, 10).getValues();
}
const CRM = 'CRM';
const AG = 'Недвижимость — агентства';

// ─────────────── сценарии ───────────────
console.log('\n1. Первая запись: строка на объявление, вкладки, тип продавца');
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
check('у Ивана ДВЕ строки (раньше была бы одна)', dump(CRM).filter((r) => r[0] === 'ivan').length === 2);
check('объявление без ника записано', dump(CRM).some((r) => r[0] === '' && r[1] === 'https://t.me/g/3'));
check('агентство недвижимости — на своей вкладке', dump(AG).length === 1 && dump(AG)[0][0] === 'pattaya_realty');
check('частник с недвижимостью остался в CRM', dump(CRM).some((r) => r[0] === 'oleg'));
check('тип продавца записан', dump(AG)[0][9] === 'бизнес');
check('«Написали?» по умолчанию Нет', dump(CRM).every((r) => r[6] === 'Нет'));
check('«Присутствие» и «На сайте» пустые', dump(CRM).every((r) => r[7] === '' && r[8] === ''));

console.log('\n2. Дубль по ссылке не проходит');
res = post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/1', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-18 09:00', snippet: 'Айфон снова', seller_type: 'частник' },
  { author: 'ivan', link: 'https://t.me/g/6', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-18 09:01', snippet: 'Наушники', seller_type: 'частник' },
] });
check('добавилась только новая ссылка', res.written === 1, JSON.stringify(res));
check('у Ивана стало три строки', dump(CRM).filter((r) => r[0] === 'ivan').length === 3);

console.log('\n3. «Написали?» ставится ВСЕМ строкам человека');
res = post({ token: 'T', action: 'mark', author: '@Ivan', value: 'Да' });
check('поправлено три строки', res.found === 3, JSON.stringify(res));
check('у всех строк Ивана «Да»', dump(CRM).filter((r) => r[0] === 'ivan').every((r) => r[6] === 'Да'));
check('чужие строки не тронуты', dump(CRM).filter((r) => r[0] === 'oleg').every((r) => r[6] === 'Нет'));

console.log('\n4. Новое объявление написанного человека рождается с «Да»');
post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/7', channel: 'Барахолка', category: 'Спорт', category_slug: 'sport', date: '2026-08-19 09:00', snippet: 'Велосипед', seller_type: 'частник' },
] });
const ivanNew = dump(CRM).find((r) => r[1] === 'https://t.me/g/7');
check('новая строка унаследовала «Да» — второго письма не будет', ivanNew[6] === 'Да', JSON.stringify(ivanNew));

console.log('\n5. Наследование работает и через вкладку агентств');
post({ token: 'T', action: 'mark', author: 'pattaya_realty', value: 'Премиум' });
post({ token: 'T', action: 'append', rows: [
  { author: 'pattaya_realty', link: 'https://t.me/g/8', channel: 'Аренда', category: 'Недвижимость', category_slug: 'realty', date: '2026-08-19 10:00', snippet: 'Вилла', seller_type: 'бизнес' },
] });
check('вторая строка агентства унаследовала «Премиум»',
  dump(AG).find((r) => r[1] === 'https://t.me/g/8')[6] === 'Премиум');

console.log('\n6. «Присутствие» — отдельная колонка, бот её не задевает');
res = post({ token: 'T', action: 'presence', author: 'ivan', value: 'согласен' });
check('присутствие проставлено всем строкам Ивана', res.found === 4, JSON.stringify(res));
check('«Написали?» при этом осталось «Да»', dump(CRM).filter((r) => r[0] === 'ivan').every((r) => r[6] === 'Да' && r[7] === 'согласен'));
res = post({ token: 'T', action: 'presence', author: 'oleg', value: 'ерунда' });
check('мусорное значение присутствия не пишется', dump(CRM).find((r) => r[0] === 'oleg')[7] === '');

console.log('\n7. «На сайте» — только у конкретного объявления');
res = post({ token: 'T', action: 'nosite', link: 'https://t.me/g/2', value: 'Не вышло' });
check('покрашено одно объявление', res.found === 1, JSON.stringify(res));
check('пометка стоит там, где надо', dump(CRM).find((r) => r[1] === 'https://t.me/g/2')[8] === 'Не вышло');
check('у соседнего объявления Ивана пусто', dump(CRM).find((r) => r[1] === 'https://t.me/g/1')[8] === '');
res = post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'Ждёт модератора' });
check('успех пишется отдельным значением', dump(CRM).find((r) => r[1] === 'https://t.me/g/1')[8] === 'Ждёт модератора', JSON.stringify(res));
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: 'что-то своё' });
check('мусорное значение = «Не вышло»', dump(CRM).find((r) => r[1] === 'https://t.me/g/1')[8] === 'Не вышло');

console.log('\n7а. Очередь авто-подготовки (todo)');
// У Ивана «согласен» и 4 строки; две мы только что пометили, значит остаются 2.
let todo = get({ action: 'todo', token: 'T' }).rows;
check('в очередь попали только непомеченные строки согласного',
  todo.length === 2 && todo.every((r) => r.nick === 'ivan'), JSON.stringify(todo));
check('помеченные строки в очередь не попали',
  todo.every((r) => r.link !== 'https://t.me/g/1' && r.link !== 'https://t.me/g/2'));
check('todo с чужим токеном', get({ action: 'todo', token: 'X' }).ok === false);
check('limit урезает очередь', get({ action: 'todo', token: 'T', limit: '1' }).rows.length === 1);
// Вернём поле в исходное состояние, чтобы дальнейшие проверки не поехали.
post({ token: 'T', action: 'site', link: 'https://t.me/g/1', value: '' });
post({ token: 'T', action: 'site', link: 'https://t.me/g/2', value: '' });

console.log('\n8. Статусы для рассылки: «сильный» статус побеждает');
const st = get({ action: 'statuses', token: 'T' }).statuses;
check('ivan → Да', st.ivan === 'Да', JSON.stringify(st));
check('oleg → Нет', st.oleg === 'Нет');
check('агентство с другой вкладки тоже видно', st.pattaya_realty === 'Премиум');
check('пустой ник в карту не попал', !('' in st));

console.log('\n9. Чужой токен отбивается');
check('append с чужим токеном', post({ token: 'X', action: 'append', rows: [] }).ok === false);
check('statuses с чужим токеном', get({ action: 'statuses', token: 'X' }).ok === false);
check('alive работает без токена', get({}).alive === true);

console.log('\n10. Миграция старой таблицы (7 колонок, строка = человек)');
SS._sheets.length = 0;
const old = makeSheet(CRM, 1000, 7);
old.appendRow(['Ник', 'Ссылка', 'Канал', 'Категория', 'Дата', 'Описание', 'Написали?']);
old.appendRow(['petr', 'https://t.me/g/100', 'Барахолка', 'Электроника', '2026-07-01', 'Телефон', 'Да']);
old.appendRow(['maria', 'https://t.me/g/101', 'Барахолка', 'Мебель', '2026-07-02', 'Стол', 'Нет']);
old.appendRow(['sergey', 'https://t.me/g/102', 'Барахолка', 'Авто', '2026-07-03', 'Байк', 'Премиум']);
SS._sheets.push(old);
const mig = vm.runInContext('migrateAddColumns', ctx)();
const head = old.getRange(1, 1, 1, 10).getValues()[0];
check('шапка расширена до 10 колонок', head[7] === 'Присутствие' && head[8] === 'На сайте' && head[9] === 'Тип продавца', JSON.stringify(head));
check('лист расширен физически', old.getMaxColumns() >= 10);
check('вкладка агентств создана', !!SS.getSheetByName(AG));
check('«Да» → «нет ответа» (второго письма не будет)', dump(CRM).find((r) => r[0] === 'petr')[7] === 'нет ответа');
check('«Нет» → присутствие пустое', dump(CRM).find((r) => r[0] === 'maria')[7] === '');
check('«Премиум» → присутствие пустое', dump(CRM).find((r) => r[0] === 'sergey')[7] === '');
check('старые данные на месте', dump(CRM).length === 3 && dump(CRM)[0][5] === 'Телефон');
check('счётчик миграции верный', mig.filled === 1, JSON.stringify(mig));

console.log('\n11. Миграция повторно — ничего не ломает');
post({ token: 'T', action: 'presence', author: 'maria', value: 'отказ' });
const mig2 = vm.runInContext('migrateAddColumns', ctx)();
check('второй прогон не трогает уже заполненное', mig2.filled === 0 && dump(CRM).find((r) => r[0] === 'maria')[7] === 'отказ');

console.log('\n12. Дозапись в мигрированную таблицу');
res = post({ token: 'T', action: 'append', rows: [
  { author: 'petr', link: 'https://t.me/g/200', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-17', snippet: 'Ноут', seller_type: 'частник' },
  { author: 'petr', link: 'https://t.me/g/100', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-17', snippet: 'Телефон', seller_type: 'частник' },
] });
const petrNew = dump(CRM).find((r) => r[1] === 'https://t.me/g/200');
check('добавилась одна строка (вторая — дубль ссылки)', res.written === 1, JSON.stringify(res));
check('унаследованы и «Да», и «нет ответа»', petrNew[6] === 'Да' && petrNew[7] === 'нет ответа', JSON.stringify(petrNew));

const CONSENT = 'Согласия';
function dumpConsent() {
  const sh = SS.getSheetByName(CONSENT);
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, 4).getValues();
}

console.log('\n13. Реестр согласий: сайт сообщает «согласен»');
SS._sheets.length = 0;
post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/1', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-17 10:00', snippet: 'Айфон', seller_type: 'частник' },
  { author: 'ivan', link: 'https://t.me/g/2', channel: 'Барахолка', category: 'Мебель', category_slug: 'home', date: '2026-08-17 10:05', snippet: 'Стол', seller_type: 'частник' },
  { author: 'maria', link: 'https://t.me/g/3', channel: 'Барахолка', category: 'Спорт', category_slug: 'sport', date: '2026-08-17 10:10', snippet: 'Велосипед', seller_type: 'частник' },
] });
res = post({ token: 'T', action: 'consent', nick: '@Ivan', status: 'согласен', reason: 'опубликовано объявление за автора' });
check('строка в реестре появилась', dumpConsent().length === 1 && dumpConsent()[0][0] === 'ivan', JSON.stringify(dumpConsent()));
check('основание записано', dumpConsent()[0][3] === 'опубликовано объявление за автора');
check('дата проставлена', /^\d{4}-\d{2}-\d{2}$/.test(String(dumpConsent()[0][2])), String(dumpConsent()[0][2]));
check('«Присутствие» проставлено обеим строкам Ивана', res.found === 2, JSON.stringify(res));
check('в таблице статус виден', dump(CRM).filter((r) => r[0] === 'ivan').every((r) => r[7] === 'согласен'));
check('чужие строки не тронуты', dump(CRM).find((r) => r[0] === 'maria')[7] === '');

console.log('\n14. Новое объявление согласившегося сразу рождается со статусом');
post({ token: 'T', action: 'append', rows: [
  { author: 'ivan', link: 'https://t.me/g/4', channel: 'Барахолка', category: 'Спорт', category_slug: 'sport', date: '2026-08-19 08:00', snippet: 'Лыжи', seller_type: 'частник' },
] });
check('унаследован «согласен» из реестра', dump(CRM).find((r) => r[1] === 'https://t.me/g/4')[7] === 'согласен');

console.log('\n15. Сильный статус не понижается слабым');
post({ token: 'T', action: 'consent', nick: 'ivan', status: 'зарегистрирован', reason: 'вошёл через Telegram' });
check('«зарегистрирован» сильнее «согласен»', dumpConsent()[0][1] === 'зарегистрирован', JSON.stringify(dumpConsent()));
check('строк в реестре по-прежнему одна (человек = строка)', dumpConsent().length === 1);
post({ token: 'T', action: 'consent', nick: 'ivan', status: 'отказ', reason: 'попросил не писать' });
res = post({ token: 'T', action: 'consent', nick: 'ivan', status: 'согласен', reason: 'сайт опубликовал ещё одно' });
check('отказ автоматикой не снимается', dumpConsent()[0][1] === 'отказ' && res.kept === true, JSON.stringify(res));
check('в таблице у Ивана стоит «отказ»', dump(CRM).filter((r) => r[0] === 'ivan').every((r) => r[7] === 'отказ'));

console.log('\n16. Мусор, чужой токен и ручной пересчёт');
check('мусорный статус не принимается', post({ token: 'T', action: 'consent', nick: 'maria', status: 'ерунда' }).ok === false);
check('пустой ник не принимается', post({ token: 'T', action: 'consent', nick: '', status: 'согласен' }).ok === false);
check('consent с чужим токеном', post({ token: 'X', action: 'consent', nick: 'maria', status: 'согласен' }).ok === false);
check('в реестре по-прежнему один человек', dumpConsent().length === 1);
const cons = get({ action: 'consents', token: 'T' }).consents;
check('реестр отдаётся наружу', cons.ivan === 'отказ', JSON.stringify(cons));
check('consents с чужим токеном', get({ action: 'consents', token: 'X' }).ok === false);
// руками дописали строку в реестр (так Савелий ставит «отказ» и так зальются ники из базы)
SS.getSheetByName(CONSENT).appendRow(['maria', 'согласен', '2026-08-19', 'выгрузка из базы']);
const sync = vm.runInContext('syncConsents', ctx)();
check('пересчёт нашёл двоих', sync.people === 2, JSON.stringify(sync));
check('Марии проставлен статус из реестра', dump(CRM).find((r) => r[0] === 'maria')[7] === 'согласен');
check('повторный пересчёт ничего не меняет', vm.runInContext('syncConsents', ctx)().touched === 0);

console.log('\n17. Ночная сверка с сайтом');
// Готовим строку, которую «уже разместили».
post({ token: 'T', action: 'append', rows: [
  { author: 'petr', link: 'https://t.me/g/50', channel: 'Барахолка', category: 'Электроника', category_slug: 'electronics', date: '2026-08-20 10:00', snippet: 'Ноутбук', seller_type: 'частник' },
] });
post({ token: 'T', action: 'site', link: 'https://t.me/g/50', value: 'Ждёт модератора' });
let placed = get({ action: 'placed', token: 'T' }).rows;
check('размещённые отдаются со ссылкой и статусом',
  placed.length === 1 && placed[0].link === 'https://t.me/g/50' && placed[0].site === 'Ждёт модератора',
  JSON.stringify(placed));
// «Опубликовано» из первых версий отдельным состоянием больше не живёт
post({ token: 'T', action: 'site', link: 'https://t.me/g/50', value: 'Опубликовано' });
check('старое «Опубликовано» превращается в «Ждёт модератора»',
  dump(CRM).find((r) => r[1] === 'https://t.me/g/50')[8] === 'Ждёт модератора',
  JSON.stringify(dump(CRM).find((r) => r[1] === 'https://t.me/g/50')));
check('placed с чужим токеном', get({ action: 'placed', token: 'X' }).ok === false);

// Сверка сказала: объявление в каталоге.
res = post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/50', value: 'В каталоге' }] });
check('пакетная запись обновила строку', res.updated === 1, JSON.stringify(res));
check('в таблице новое состояние',
  dump(CRM).find((r) => r[1] === 'https://t.me/g/50')[8] === 'В каталоге');
check('повторная запись того же ничего не меняет',
  post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/50', value: 'В каталоге' }] }).updated === 0);

// «Удалено» — окончательное состояние: больше не сверяем.
post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/50', value: 'Удалено' }] });
check('удалённые из сверки выпадают', get({ action: 'placed', token: 'T' }).rows.length === 0);
check('мусорное значение превращается в «Не вышло»',
  post({ token: 'T', action: 'sitebulk', rows: [{ link: 'https://t.me/g/50', value: 'абракадабра' }] }).updated === 1 &&
  dump(CRM).find((r) => r[1] === 'https://t.me/g/50')[8] === 'Не вышло');

const nicks = get({ action: 'nicks', token: 'T' }).nicks;
check('ники отдаются без повторов',
  nicks.indexOf('petr') !== -1 && nicks.length === new Set(nicks).size, JSON.stringify(nicks));

// Пакет согласий: человек зарегистрировался сам — за него больше не публикуем.
res = post({ token: 'T', action: 'consentbulk', rows: [
  { nick: 'petr', status: 'зарегистрирован', reason: 'нашёлся при ночной сверке' },
] });
check('пакет согласий записался', res.changed === 1, JSON.stringify(res));
check('в строке появился статус «зарегистрирован»',
  dump(CRM).find((r) => r[0] === 'petr')[7] === 'зарегистрирован');
check('отказ пакетом не понижается',
  post({ token: 'T', action: 'consentbulk', rows: [{ nick: 'ivan', status: 'зарегистрирован' }] }).changed === 0 &&
  dumpConsent().find((r) => r[0] === 'ivan')[1] === 'отказ');

console.log('\n18. Ручная правка «Присутствия» разъезжается по всем строкам ника');
// Три объявления одного человека и одно чужое.
post({ token: 'T', action: 'append', rows: [
  { author: 'anna', link: 'https://t.me/g/60', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:00', snippet: 'Стол', seller_type: 'частник' },
  { author: 'anna', link: 'https://t.me/g/61', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:05', snippet: 'Стул', seller_type: 'частник' },
  { author: 'anna', link: 'https://t.me/g/62', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:10', snippet: 'Шкаф', seller_type: 'частник' },
  { author: 'boris', link: 'https://t.me/g/63', channel: 'Барахолка', category: 'Мебель', category_slug: 'furniture', date: '2026-08-20 10:15', snippet: 'Диван', seller_type: 'частник' },
] });

const crmSheet = SS.getSheetByName(CRM);
function rowsOf(nick) { return dump(CRM).filter((r) => r[0] === nick); }
function editPresence(nick, value) {
  // находим ПЕРВУЮ строку человека и правим её, как это сделал бы Савелий мышью
  const all = dump(CRM);
  const idx = all.findIndex((r) => r[0] === nick);
  const rowNo = idx + 2; // +1 шапка, +1 нумерация с единицы
  const range = crmSheet.getRange(rowNo, 8);
  range.setValue(value);
  vm.runInContext('onEdit', ctx)({ range });
}

editPresence('anna', 'согласен');
check('значение разошлось по всем строкам ника',
  rowsOf('anna').length === 3 && rowsOf('anna').every((r) => r[7] === 'согласен'),
  JSON.stringify(rowsOf('anna')));
check('чужие строки не тронуты', rowsOf('boris').every((r) => r[7] !== 'согласен'));
check('появилась запись в реестре',
  (dumpConsent().find((r) => r[0] === 'anna') || [])[1] === 'согласен', JSON.stringify(dumpConsent()));

// Ручная правка СИЛЬНЕЕ автоматики: сначала автоматика ставит «отказ»…
post({ token: 'T', action: 'consent', nick: 'anna', status: 'отказ', reason: 'сказала стоп' });
check('автоматика поставила отказ', rowsOf('anna').every((r) => r[7] === 'отказ'));
// …а человек руками возвращает «согласен» — и это должно победить
editPresence('anna', 'согласен');
check('ручная правка перебивает отказ',
  rowsOf('anna').every((r) => r[7] === 'согласен') &&
  (dumpConsent().find((r) => r[0] === 'anna') || [])[1] === 'согласен',
  JSON.stringify(dumpConsent()));

// Очистка ячейки = человек снова «чистый»
editPresence('anna', '');
check('пустое значение разошлось по строкам',
  rowsOf('anna').every((r) => String(r[7] || '') === ''), JSON.stringify(rowsOf('anna')));
check('запись из реестра удалена',
  !dumpConsent().some((r) => r[0] === 'anna'), JSON.stringify(dumpConsent()));

// Опечатку не разносим
editPresence('anna', 'сагласен');
check('мусорное значение остаётся в одной ячейке',
  rowsOf('anna').filter((r) => r[7] === 'сагласен').length === 1);
editPresence('anna', '');

// «Нет ответа» — про рассылку, реестр им не трогаем
editPresence('anna', 'согласен');
editPresence('anna', 'нет ответа');
check('«нет ответа» разошлось по строкам',
  rowsOf('anna').every((r) => r[7] === 'нет ответа'), JSON.stringify(rowsOf('anna')));
check('но согласие в реестре осталось',
  (dumpConsent().find((r) => r[0] === 'anna') || [])[1] === 'согласен', JSON.stringify(dumpConsent()));
editPresence('anna', '');

// Правка в чужой колонке триггер не будит
const before = JSON.stringify(dump(CRM));
const other = crmSheet.getRange(2, 6);
other.setValue('какое-то описание');
vm.runInContext('onEdit', ctx)({ range: other });
check('правка другой колонки ничего не разносит',
  dump(CRM).filter((r) => r[0] === 'anna').every((r) => String(r[7] || '') === ''));

console.log(failed === 0 ? '\n🏁 ВСЁ ЗЕЛЁНОЕ\n' : `\n⛔ ПРОВАЛЕНО ПРОВЕРОК: ${failed}\n`);
process.exit(failed === 0 ? 0 : 1);
