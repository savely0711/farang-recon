/**
 * Скрипт-приёмник таблицы «Фаранг — Недвижимость» (25.08.2026).
 *
 * Это ОТДЕЛЬНАЯ таблица, не та, в которой живёт разведка барахолок. Сюда
 * пишет только realty_parser.py. Рассылка и авто-подготовка объявлений сюда
 * не ходят — по замыслу: агентствам мы не пишем и их объявления не публикуем.
 *
 * Две вкладки:
 *   «Объявления» — строка = пост. Дубли по ссылке отсекаются здесь же.
 *   «Счётчик»    — строка = ник автора: сколько объявлений за 7 дней, за 30
 *                  дней и за всё время, первый и последний пост, в каких
 *                  группах, доля от всех объявлений. Считаются только
 *                  предложения; «спрос» (сниму/ищу) в счётчик не идёт.
 *
 * Что принимает (POST, JSON):
 *   {token, action:'append',  rows:[{author,link,channel,date,kind,deal,
 *        prop_type,price,currency,period,price_max,bedrooms,area,district,snippet}]}
 *   {token, action:'counter'} — пересчитать вкладку «Счётчик»
 *   {token, action:'ping'}    — проверка связи
 *
 * Как поставить:
 *   1. Новая Google-таблица → «Расширения» → «Apps Script» → вставить этот код.
 *   2. Вписать TOKEN ниже (та же строка, что в .env → REALTY_SHEET_TOKEN).
 *   3. Сохранить → «Развернуть» → «Новое развёртывание» → тип «Веб-приложение»,
 *      выполнять «от моего имени», доступ «Все» → «Развернуть».
 *      Полученный URL (…/exec) → в .env → REALTY_SHEET_WEBHOOK_URL.
 *   4. В таблице появится меню «Фаранг»: «Настроить таблицу» (создаёт вкладки
 *      и ежедневный пересчёт) и «Пересчитать счётчик» (вручную).
 *
 * ВАЖНО: после ЛЮБОЙ правки этого кода мало нажать «Сохранить» — нужно
 * «Управление развёртываниями» → карандаш → «Версия: Создать» → «Развернуть».
 * Иначе веб-приложение продолжит работать по старому коду.
 */
var TOKEN = 'PASTE_YOUR_TOKEN_HERE'; // тот же, что в .env (REALTY_SHEET_TOKEN)

var LIST_TAB = 'Объявления';
var COUNTER_TAB = 'Счётчик';

var HEADER = ['Ник', 'Ссылка', 'Группа', 'Дата', 'Что это', 'Сделка',
              'Тип жилья', 'Цена', 'Валюта', 'Период', 'Цена макс',
              'Спальни', 'Площадь', 'Район', 'Описание'];
var NICK_COL = 1;     // A
var LINK_COL = 2;     // B — ключ дубля
var CHAN_COL = 3;     // C
var DATE_COL = 4;     // D
var KIND_COL = 5;     // E — предложение / спрос

var COUNTER_HEADER = ['Ник', 'За 7 дней', 'За 30 дней', 'Всего',
                      'Первый пост', 'Последний пост', 'Групп', 'Группы',
                      'Доля, %'];

var KIND_OFFER = 'предложение';
var NO_NICK = '— без ника —';

var HEAD_BG = '#d9ead3';   // шапка вкладок
var TOP_BG = '#fff2cc';    // первая тройка счётчика

// ─────────────────────────── ПРИЁМ (POST) ───────────────────────────
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var action = String(body.action || 'append');
    var tabs = _ensureTabs();

    if (action === 'ping') {
      return _json({ ok: true, rows: Math.max(0, tabs.list.getLastRow() - 1) });
    }
    if (action === 'counter') {
      return _json({ ok: true, nicks: rebuildCounter() });
    }

    var rows = body.rows;
    if (!rows) {
      rows = [body];
    }
    var written = _appendDedup(tabs, rows);
    return _json({ ok: true, written: written });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

function doGet() {
  return _json({ ok: true, note: 'Фаранг — Недвижимость: приёмник жив' });
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);
}

// ─────────────────────────── ВКЛАДКИ ───────────────────────────
function _ensureTabs() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var list = ss.getSheetByName(LIST_TAB);
  if (!list) {
    list = ss.insertSheet(LIST_TAB);
    _writeHeader(list, HEADER);
    list.setFrozenRows(1);
    // Первый лист новой таблицы называется «Лист1» и мешается — убираем,
    // если он пустой.
    var first = ss.getSheetByName('Лист1') || ss.getSheetByName('Sheet1');
    if (first && first.getLastRow() === 0) ss.deleteSheet(first);
  }
  var counter = ss.getSheetByName(COUNTER_TAB);
  if (!counter) {
    counter = ss.insertSheet(COUNTER_TAB);
    _writeHeader(counter, COUNTER_HEADER);
    counter.setFrozenRows(1);
  }
  return { list: list, counter: counter };
}

function _writeHeader(sheet, header) {
  sheet.getRange(1, 1, 1, header.length).setValues([header])
      .setFontWeight('bold').setBackground(HEAD_BG);
}

// ─────────────────────────── ЗАПИСЬ ОБЪЯВЛЕНИЙ ───────────────────────────
/**
 * Дописывает строки, пропуская те, чья ссылка уже есть в таблице.
 * Ссылка — надёжный ключ: один пост в Telegram = один адрес.
 */
function _appendDedup(tabs, rows) {
  var sheet = tabs.list;
  var known = {};
  var last = sheet.getLastRow();
  if (last > 1) {
    var links = sheet.getRange(2, LINK_COL, last - 1, 1).getValues();
    for (var i = 0; i < links.length; i++) {
      var l = String(links[i][0] || '').trim();
      if (l) known[l] = true;
    }
  }

  var out = [];
  for (var r = 0; r < rows.length; r++) {
    var it = rows[r] || {};
    var link = String(it.link || '').trim();
    if (!link || known[link]) continue;
    known[link] = true;
    out.push([
      String(it.author || '').replace(/^@/, '').toLowerCase(),
      link,
      it.channel || '',
      _toDate(it.date),
      it.kind || '',
      it.deal || '',
      it.prop_type || '',
      _num(it.price),
      it.currency || '',
      it.period || '',
      _num(it.price_max),
      _num(it.bedrooms),
      _num(it.area),
      it.district || '',
      it.snippet || ''
    ]);
  }
  if (!out.length) return 0;

  var start = sheet.getLastRow() + 1;
  sheet.getRange(start, 1, out.length, HEADER.length).setValues(out);
  sheet.getRange(start, DATE_COL, out.length, 1).setNumberFormat('yyyy-mm-dd hh:mm');
  return out.length;
}

/** Пустое значение оставляем пустым, а не нулём: ноль в цене врёт. */
function _num(v) {
  if (v === null || v === undefined || v === '') return '';
  var n = Number(v);
  return isNaN(n) ? '' : n;
}

/** «2026-08-25 09:30» → настоящая дата (чтобы сортировка и счётчик работали). */
function _toDate(v) {
  if (v instanceof Date) return v;
  var s = String(v || '').trim();
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return s;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]),
                  Number(m[4]), Number(m[5]), 0);
}

// ─────────────────────────── СЧЁТЧИК АГЕНТСТВ ───────────────────────────
/**
 * Пересчитывает вкладку «Счётчик» с нуля по вкладке «Объявления».
 * Считаем только предложения: «спрос» (сниму/ищу) — это не работа агентства.
 * Возвращает число ников в счётчике.
 */
function rebuildCounter() {
  var tabs = _ensureTabs();
  var sheet = tabs.list;
  var last = sheet.getLastRow();
  var counter = tabs.counter;

  // Чистим прежние строки (шапку оставляем).
  if (counter.getLastRow() > 1) {
    counter.getRange(2, 1, counter.getLastRow() - 1, COUNTER_HEADER.length).clear();
  }
  if (last < 2) return 0;

  var data = sheet.getRange(2, 1, last - 1, KIND_COL).getValues();
  var now = new Date();
  var d7 = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
  var d30 = new Date(now.getTime() - 30 * 24 * 3600 * 1000);

  var map = {};
  var total = 0;
  for (var i = 0; i < data.length; i++) {
    var kind = String(data[i][KIND_COL - 1] || '').trim();
    if (kind && kind !== KIND_OFFER) continue;      // спрос не считаем
    var nick = String(data[i][NICK_COL - 1] || '').trim().toLowerCase() || NO_NICK;
    var chan = String(data[i][CHAN_COL - 1] || '').trim();
    var when = data[i][DATE_COL - 1];
    if (!(when instanceof Date)) when = _toDate(when);

    var rec = map[nick];
    if (!rec) {
      rec = map[nick] = { all: 0, w: 0, m: 0, first: null, last: null, chans: {} };
    }
    rec.all++;
    total++;
    if (chan) rec.chans[chan] = true;
    if (when instanceof Date && !isNaN(when.getTime())) {
      if (when >= d7) rec.w++;
      if (when >= d30) rec.m++;
      if (!rec.first || when < rec.first) rec.first = when;
      if (!rec.last || when > rec.last) rec.last = when;
    }
  }

  var out = [];
  for (var key in map) {
    var r = map[key];
    var names = [];
    for (var c in r.chans) names.push(c);
    out.push([key, r.w, r.m, r.all, r.first || '', r.last || '',
              names.length, names.join(', '),
              total ? Math.round(r.all * 1000 / total) / 10 : 0]);
  }
  // Сортировка: сначала самые активные за всё время, при равенстве — за месяц.
  out.sort(function (a, b) { return (b[3] - a[3]) || (b[2] - a[2]); });

  if (out.length) {
    counter.getRange(2, 1, out.length, COUNTER_HEADER.length).setValues(out);
    counter.getRange(2, 5, out.length, 2).setNumberFormat('yyyy-mm-dd');
    counter.getRange(2, 1, Math.min(3, out.length), COUNTER_HEADER.length)
        .setBackground(TOP_BG);
  }
  // Отметка времени пересчёта — чтобы было видно, свежие ли цифры.
  counter.getRange(1, COUNTER_HEADER.length + 2, 1, 1)
      .setValue('пересчитано: ' +
                Utilities.formatDate(now, 'Asia/Bangkok', 'yyyy-MM-dd HH:mm'));
  return out.length;
}

// ─────────────────────────── МЕНЮ И РАСПИСАНИЕ ───────────────────────────
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Фаранг')
      .addItem('Пересчитать счётчик', 'rebuildCounter')
      .addItem('Настроить таблицу', 'setupSheet')
      .addToUi();
}

/**
 * Разовая настройка: создаёт вкладки и ставит ежедневный пересчёт счётчика
 * (в 6 утра). Запускать можно сколько угодно раз — лишнего не сделает.
 */
function setupSheet() {
  _ensureTabs();
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'rebuildCounter') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger('rebuildCounter').timeBased().atHour(6).everyDays(1).create();
  rebuildCounter();
}
