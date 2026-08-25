/**
 * Прогон realty_apps_script.gs в подставном окружении (без Google).
 * Запуск: node test_realty_apps_script.js
 *
 * Гонять ПОСЛЕ любой правки скрипта таблицы: это дешевле, чем ловить ошибку
 * на живых данных, где каждая проверка стоит нового развёртывания.
 */
const fs = require('fs');
const path = require('path');

const failed = [];
function check(name, cond, extra) {
  if (cond) { console.log('  ✅ ' + name); }
  else { failed.push(name); console.log('  ❌ ' + name + (extra ? '\n       ' + extra : '')); }
}
function eq(name, got, want) {
  check(name + ': ' + JSON.stringify(want), JSON.stringify(got) === JSON.stringify(want),
        'получили ' + JSON.stringify(got));
}

// ─────────── подставной Google ───────────
class FakeRange {
  constructor(sheet, row, col, rows, cols) {
    Object.assign(this, { sheet, row, col, rows, cols });
  }
  getValues() {
    const out = [];
    for (let r = 0; r < this.rows; r++) {
      const line = [];
      for (let c = 0; c < this.cols; c++) {
        const rr = this.sheet.data[this.row - 1 + r] || [];
        line.push(rr[this.col - 1 + c] === undefined ? '' : rr[this.col - 1 + c]);
      }
      out.push(line);
    }
    return out;
  }
  setValues(vals) {
    for (let r = 0; r < vals.length; r++) {
      const rowIdx = this.row - 1 + r;
      if (!this.sheet.data[rowIdx]) this.sheet.data[rowIdx] = [];
      for (let c = 0; c < vals[r].length; c++) {
        this.sheet.data[rowIdx][this.col - 1 + c] = vals[r][c];
      }
    }
    return this;
  }
  setValue(v) { return this.setValues([[v]]); }
  clear() {
    for (let r = 0; r < this.rows; r++) {
      const rowIdx = this.row - 1 + r;
      if (this.sheet.data[rowIdx]) {
        for (let c = 0; c < this.cols; c++) this.sheet.data[rowIdx][this.col - 1 + c] = '';
      }
    }
    // Пустые хвостовые строки убираем, как это делает Google при clear+append.
    while (this.sheet.data.length && this.sheet.data[this.sheet.data.length - 1]
           .every(function (v) { return v === '' || v === undefined; })) {
      this.sheet.data.pop();
    }
    return this;
  }
  setNumberFormat() { return this; }
  setBackground() { return this; }
  setFontWeight() { return this; }
}

class FakeSheet {
  constructor(name) { this.name = name; this.data = []; }
  getName() { return this.name; }
  getLastRow() { return this.data.length; }
  getLastColumn() {
    return this.data.reduce((m, r) => Math.max(m, r ? r.length : 0), 0);
  }
  getRange(row, col, rows, cols) {
    return new FakeRange(this, row, col, rows === undefined ? 1 : rows,
                         cols === undefined ? 1 : cols);
  }
  setFrozenRows() { return this; }
}

const sheets = {};
global.SpreadsheetApp = {
  getActiveSpreadsheet: () => ({
    getSheetByName: (n) => sheets[n] || null,
    insertSheet: (n) => (sheets[n] = new FakeSheet(n)),
    deleteSheet: (s) => { delete sheets[s.getName()]; },
  }),
  getUi: () => ({ createMenu: () => ({ addItem() { return this; }, addToUi() {} }) }),
};
global.ContentService = {
  MimeType: { JSON: 'json' },
  createTextOutput: (s) => ({ _s: s, setMimeType() { return this; }, getContent() { return this._s; } }),
};
global.Utilities = { formatDate: (d) => d.toISOString().slice(0, 16).replace('T', ' ') };
global.ScriptApp = {
  getProjectTriggers: () => [],
  newTrigger: () => ({ timeBased: () => ({ atHour: () => ({ everyDays: () => ({ create() {} }) }) }) }),
  deleteTrigger: () => {},
};

// ─────────── грузим сам скрипт ───────────
const code = fs.readFileSync(path.join(__dirname, 'realty_apps_script.gs'), 'utf8');
eval(code);
TOKEN = 'test-token';

function post(payload) {
  return JSON.parse(doPost({ postData: { contents: JSON.stringify(payload) } }).getContent());
}
function daysAgo(n) {
  const d = new Date(Date.now() - n * 24 * 3600 * 1000);
  const p = (x) => String(x).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
         ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

// ─────────── 1. Пароль ───────────
console.log('\n1. Чужой без пароля не пишет');
eq('чужой токен отбит', post({ token: 'nope', action: 'ping' }).ok, false);

// ─────────── 2. Запись и дубли ───────────
console.log('\n2. Запись объявлений и защита от дублей');
let res = post({
  token: TOKEN, action: 'append', rows: [
    { author: '@AgencyOne', link: 't.me/g/1', channel: 'Недвижимость Паттайя',
      date: daysAgo(1), kind: 'предложение', deal: 'аренда', prop_type: 'кондо',
      price: 25000, currency: 'THB', period: 'месяц', bedrooms: 1, area: 35,
      district: 'Джомтьен', seller: 'агентство', agency: 'Sunrise Estate',
      project: 'Riviera Wongamat', parsed_by: 'ИИ', snippet: 'Сдам кондо' },
    { author: 'agencyone', link: 't.me/g/2', channel: 'Недвижимость Паттайя',
      date: daysAgo(10), kind: 'предложение', deal: 'продажа', price: 4500000,
      currency: 'THB', period: 'всего', district: 'Наклуа', seller: 'агентство',
      agency: 'Sunrise Estate', parsed_by: 'ИИ+правила', snippet: 'Продам' },
    { author: 'petr', link: 't.me/g/3', channel: 'Недвижимость Паттайя',
      date: daysAgo(2), kind: 'спрос', deal: 'аренда', seller: 'частник',
      parsed_by: 'правила', snippet: 'Сниму студию' },
  ],
});
eq('записано строк', res.written, 3);
eq('повтор той же ссылки не пишется',
   post({ token: TOKEN, action: 'append',
          rows: [{ author: 'agencyone', link: 't.me/g/1', date: daysAgo(1),
                   kind: 'предложение' }] }).written, 0);
check('ник приведён к нижнему регистру без @',
      sheets['Объявления'].data[1][0] === 'agencyone',
      String(sheets['Объявления'].data[1][0]));
check('дата стала настоящей датой', sheets['Объявления'].data[1][3] instanceof Date);
check('пустая цена осталась пустой, а не нулём',
      sheets['Объявления'].data[3][7] === '',
      JSON.stringify(sheets['Объявления'].data[3][7]));
check('шапка знает про новые колонки',
      sheets['Объявления'].data[0].slice(14, 19).join('|') ===
      'Тип продавца|Агентство|Проект|Разбор|Описание',
      sheets['Объявления'].data[0].slice(14, 19).join('|'));
check('колонка «Разбор» заполнена',
      sheets['Объявления'].data[1][17] === 'ИИ',
      String(sheets['Объявления'].data[1][17]));

// ─────────── 3. Счётчик ───────────
console.log('\n3. Счётчик агентств');
const nicks = post({ token: TOKEN, action: 'counter' }).nicks;
eq('ников в счётчике (спрос не в счёт)', nicks, 1);
const row = sheets['Счётчик'].data[1];
eq('ник', row[0], 'agencyone');
eq('тип продавца', row[1], 'агентство');
eq('название конторы', row[2], 'Sunrise Estate');
eq('за 7 дней', row[3], 1);
eq('за 30 дней', row[4], 2);
eq('всего', row[5], 2);
eq('групп', row[8], 1);
eq('доля, %', row[10], 100);

console.log('\n4. Пересчёт не задваивает строки');
post({ token: TOKEN, action: 'counter' });
eq('строк в счётчике после второго пересчёта',
   sheets['Счётчик'].data.filter(function (r) { return r[0] && r[0] !== 'Ник'; }).length, 1);

console.log('\n5. Свежие цифры при новых постах');
post({ token: TOKEN, action: 'append', rows: [
  { author: 'AgencyTwo', link: 't.me/g/4', channel: 'Другая группа',
    date: daysAgo(3), kind: 'предложение', deal: 'аренда', price: 18000,
    currency: 'THB', period: 'месяц', seller: 'частник', snippet: 'Сдам студию' }] });
post({ token: TOKEN, action: 'counter' });
const rows = sheets['Счётчик'].data.slice(1).filter(function (r) { return r[0]; });
eq('ников стало', rows.length, 2);
eq('первым идёт самый активный', rows[0][0], 'agencyone');
eq('доля лидера, %', rows[0][10], 66.7);
eq('частник остался частником', rows[1][1], 'частник');

console.log('\n' + '='.repeat(60));
if (failed.length) {
  console.log('❌ провалено проверок: ' + failed.length);
  failed.forEach((n) => console.log('   - ' + n));
  process.exit(1);
}
console.log('✅ Все проверки пройдены.');
