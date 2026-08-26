/**
 * Скрипт-приёмник таблицы «Фаранг — Недвижимость» (25.08.2026).
 *
 * Это ОТДЕЛЬНАЯ таблица, не та, в которой живёт разведка барахолок. Сюда
 * пишет только realty_parser.py. Рассылка и авто-подготовка объявлений сюда
 * не ходят — по замыслу: агентствам мы не пишем и их объявления не публикуем.
 *
 * Две вкладки:
 *   «Объявления» — строка = пост. Дубли по ссылке отсекаются здесь же.
 *   «Счётчик»    — строка = ник автора: тип продавца, название конторы,
 *                  сколько объявлений за 7 дней, за 30 дней и за всё время,
 *                  первый и последний пост, в каких группах, доля от всех
 *                  объявлений. Считаются только предложения; «спрос»
 *                  (сниму/ищу) в счётчик не идёт. Тип продавца и название
 *                  конторы берутся у ника по большинству его постов: ИИ
 *                  решает по каждому посту отдельно и иногда ошибается.
 *
 * Что принимает (POST, JSON):
 *   {token, action:'append',  rows:[{author,link,channel,date,kind,deal,
 *        prop_type,price,currency,period,price_max,bedrooms,area,district,
 *        seller,agency,project,parsed_by,snippet}]}
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
              'Спальни', 'Площадь', 'Район', 'Тип продавца', 'Агентство',
              'Проект', 'Разбор', 'Описание'];
var NICK_COL = 1;     // A
var LINK_COL = 2;     // B — ключ дубля
var CHAN_COL = 3;     // C
var DATE_COL = 4;     // D
var KIND_COL = 5;     // E — предложение / спрос
var SELLER_COL = 15;  // O — агентство / частник (ставит ИИ)
var AGENCY_COL = 16;  // P — название конторы, если ИИ его нашёл
var LAST_READ_COL = AGENCY_COL;  // докуда читает счётчик

var COUNTER_HEADER = ['Ник', 'Тип продавца', 'Агентство', 'За 7 дней',
                      'За 30 дней', 'Всего', 'Первый пост', 'Последний пост',
                      'Групп', 'Группы', 'Доля, %'];

var KIND_OFFER = 'предложение';
var NO_NICK = '— без ника —';
var SELLER_AGENCY = 'агентство';

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
  _fixHeader(list, HEADER);
  _fixHeader(counter, COUNTER_HEADER);
  return { list: list, counter: counter };
}

/**
 * Приводит шапку к нынешнему набору колонок. Осторожно: если в листе уже есть
 * строки, порядок колонок менять НЕЛЬЗЯ — старые данные разъедутся. Поэтому
 * переписываем шапку только у пустого листа, а у заполненного лишь дописываем
 * недостающие названия справа.
 */
function _fixHeader(sheet, header) {
  var width = Math.max(sheet.getLastColumn(), header.length);
  var now = sheet.getRange(1, 1, 1, width).getValues()[0];
  var same = true;
  for (var i = 0; i < header.length; i++) {
    if (String(now[i] || '') !== header[i]) { same = false; break; }
  }
  if (same) return;
  if (sheet.getLastRow() > 1) {
    // Лист не пустой: дописываем только пустые ячейки шапки справа.
    for (var j = 0; j < header.length; j++) {
      if (!String(now[j] || '')) sheet.getRange(1, j + 1, 1, 1).setValue(header[j]);
    }
    return;
  }
  _writeHeader(sheet, header);
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
      it.seller || '',
      it.agency || '',
      it.project || '',
      it.parsed_by || '',
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

  var data = sheet.getRange(2, 1, last - 1, LAST_READ_COL).getValues();
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

    var seller = String(data[i][SELLER_COL - 1] || '').trim();
    var agency = String(data[i][AGENCY_COL - 1] || '').trim();

    var rec = map[nick];
    if (!rec) {
      rec = map[nick] = { all: 0, w: 0, m: 0, first: null, last: null,
                          chans: {}, agencies: {}, business: 0 };
    }
    rec.all++;
    total++;
    if (chan) rec.chans[chan] = true;
    // Тип продавца и название конторы ИИ определяет по каждому посту отдельно,
    // и у одного ника они могут разойтись. Берём то, что встречается чаще:
    // одна ошибка модели не должна переименовать агентство целиком.
    if (seller === SELLER_AGENCY) rec.business++;
    if (agency) rec.agencies[agency] = (rec.agencies[agency] || 0) + 1;
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
    // Название конторы — самое частое из встреченных у этого ника.
    var agency = '', best = 0;
    for (var a in r.agencies) {
      if (r.agencies[a] > best) { best = r.agencies[a]; agency = a; }
    }
    // Тип продавца: агентство, если так решил ИИ хотя бы у половины постов.
    var seller = r.business * 2 >= r.all ? SELLER_AGENCY : 'частник';
    out.push([key, seller, agency, r.w, r.m, r.all, r.first || '', r.last || '',
              names.length, names.join(', '),
              total ? Math.round(r.all * 1000 / total) / 10 : 0]);
  }
  // Сортировка: сначала самые активные за всё время, при равенстве — за месяц.
  out.sort(function (a, b) { return (b[5] - a[5]) || (b[4] - a[4]); });

  if (out.length) {
    counter.getRange(2, 1, out.length, COUNTER_HEADER.length).setValues(out);
    // Формат задаём ЯВНО каждый раз. Иначе ячейка помнит прежний формат: после
    // того как в этом столбце когда-то стояла дата, число 52 показывается как
    // «1900-02-21». Это уже случалось при смене набора колонок.
    counter.getRange(2, 4, out.length, 3).setNumberFormat('0');       // счётчики
    counter.getRange(2, 9, out.length, 1).setNumberFormat('0');       // групп
    counter.getRange(2, 11, out.length, 1).setNumberFormat('0.0');    // доля, %
    counter.getRange(2, 7, out.length, 2).setNumberFormat('yyyy-mm-dd');
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
