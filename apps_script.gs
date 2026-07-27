/**
 * Скрипт-приёмник для Google-таблицы «Фаранг — Разведка рынка» (режим CRM).
 *
 * НОВОЕ (CRM для обзвона): все авторы со ВСЕХ каналов сводятся в ОДНУ вкладку
 * «CRM». Один ник = одна строка НАВСЕГДА (дедуп по нику). У каждой строки есть
 * колонка «Написали?» (выпадашка Да/Нет, по умолчанию «Нет»). Когда там «Да» —
 * вся строка автоматически зеленеет. Так таблица становится общим списком для
 * ручного обзвона агентами И одновременно источником правды для авто-рассылки
 * (outreach.py): бот перед письмом спрашивает статус, а после отправки сам
 * ставит «Да» — значит один человек не получит два обращения.
 *
 * Действия (что умеет скрипт):
 *   POST {action:"append", rows:[{author,link,channel,category,date,snippet}]}
 *        — дописать новых авторов в CRM (дубли по нику отсекаются здесь же);
 *   POST {action:"mark",   author:"ник"}  — пометить автора «Написали?»=Да;
 *   GET  ?action=statuses                 — отдать карту {ник: "Да"|"Нет"};
 *   GET                                   — проверка «живой ли» (alive).
 * Во всех запросах обязателен общий пароль-токен (token), кроме простого alive.
 *
 * РАЗОВАЯ МИГРАЦИЯ старого формата: функция migrateBacklog() (запустить кнопкой
 * ▶ Run прямо в редакторе Apps Script) — сольёт существующие повкладочные строки
 * в «CRM» (дедуп по нику, всем «Нет»), а старые вкладки переименует в «архив_…».
 *
 * Как обновить (после правок этого файла):
 *   1. Таблица → «Расширения» → «Apps Script» → заменить весь код этим файлом.
 *   2. Вписать TOKEN ниже (тот же, что в .env → SHEET_TOKEN).
 *   3. Сохранить (дискета) → «Развернуть» → «Управление развёртываниями» →
 *      карандаш → «Версия: Создать» → «Развернуть». URL (…/exec) НЕ меняется.
 */
var TOKEN = 'PASTE_YOUR_TOKEN_HERE'; // тот же, что в .env (SHEET_TOKEN)

var CRM_TAB = 'CRM';
var HEADER = ['Ник', 'Ссылка', 'Канал', 'Категория', 'Дата', 'Описание', 'Написали?'];
var NICK_COL = 1;      // колонка «Ник» (A)
var WRITTEN_COL = 7;   // колонка «Написали?» (G)
var GREEN = '#b7e1cd'; // фон строки при «Да»

// ─────────────────────────── ПРИЁМ (POST) ───────────────────────────
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var action = String(body.action || 'append');
    var sh = _ensureCrmSheet();

    if (action === 'mark') {
      var found = _markWritten(sh, body.author);
      return _json({ ok: true, found: found });
    }

    // action === 'append' (по умолчанию)
    var rows = body.rows;
    if (!rows) {
      rows = [{
        author: body.author, link: body.link, channel: body.channel,
        category: body.category, date: body.date, snippet: body.snippet,
      }];
    }
    var written = _appendDedup(sh, rows);
    return _json({ ok: true, written: written });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// ─────────────────────────── ОТДАЧА (GET) ───────────────────────────
function doGet(e) {
  var params = (e && e.parameter) || {};
  var action = String(params.action || '');

  if (action === 'statuses') {
    if (params.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var sh = _ensureCrmSheet();
    return _json({ ok: true, statuses: _readStatuses(sh) });
  }

  return _json({ ok: true, alive: true });
}

// ─────────────────────────── ЯДРО CRM ───────────────────────────
/** Возвращает вкладку CRM, создавая её (с шапкой, дропдауном и подсветкой) при
 *  первом обращении. */
function _ensureCrmSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(CRM_TAB);
  if (!sh) {
    sh = ss.insertSheet(CRM_TAB, 0); // первой вкладкой
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
  } else if (sh.getLastColumn() === 0) {
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
  }
  _ensureValidation(sh);
  _ensureGreenRule(sh);
  return sh;
}

/** Выпадашка Да/Нет на всю колонку «Написали?». */
function _ensureValidation(sh) {
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Да', 'Нет'], true)
    .setAllowInvalid(false)
    .build();
  var maxRows = sh.getMaxRows();
  if (maxRows >= 2) {
    sh.getRange(2, WRITTEN_COL, maxRows - 1, 1).setDataValidation(rule);
  }
}

/** Условное форматирование: вся строка зеленеет, если «Написали?»=Да. */
function _ensureGreenRule(sh) {
  var rng = sh.getRange(2, 1, Math.max(1, sh.getMaxRows() - 1), HEADER.length);
  var rule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$G2="Да"')
    .setBackground(GREEN)
    .setRanges([rng])
    .build();
  sh.setConditionalFormatRules([rule]);
}

/** Нормализованный ник: без @, нижний регистр, без пробелов по краям. */
function _normNick(v) {
  return String(v == null ? '' : v).replace(/^@+/, '').trim().toLowerCase();
}

/** Множество ников, которые уже есть в CRM (для дедупа). */
function _existingNicks(sh) {
  var last = sh.getLastRow();
  var set = {};
  if (last < 2) return set;
  var col = sh.getRange(2, NICK_COL, last - 1, 1).getValues();
  for (var i = 0; i < col.length; i++) {
    var n = _normNick(col[i][0]);
    if (n) set[n] = true;
  }
  return set;
}

/** Дописывает новых авторов, отсекая дубли по нику (уже в таблице ИЛИ в этой же
 *  пачке). Возвращает число реально добавленных строк. «Написали?»=Нет. */
function _appendDedup(sh, rows) {
  var seen = _existingNicks(sh);
  var values = [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var nick = _normNick(r.author);
    if (!nick || seen[nick]) continue; // без ника или дубль — пропускаем
    seen[nick] = true;
    values.push([
      r.author || '', r.link || '', r.channel || '',
      r.category || '', r.date || '', r.snippet || '', 'Нет',
    ]);
  }
  if (values.length === 0) return 0;
  var startRow = sh.getLastRow() + 1;
  sh.getRange(startRow, 1, values.length, HEADER.length).setValues(values);
  _ensureValidation(sh);
  _ensureGreenRule(sh);
  return values.length;
}

/** Ставит «Написали?»=Да у автора (по нику). Возвращает true, если нашли. */
function _markWritten(sh, author) {
  var target = _normNick(author);
  if (!target) return false;
  var last = sh.getLastRow();
  if (last < 2) return false;
  var nicks = sh.getRange(2, NICK_COL, last - 1, 1).getValues();
  for (var i = 0; i < nicks.length; i++) {
    if (_normNick(nicks[i][0]) === target) {
      sh.getRange(i + 2, WRITTEN_COL).setValue('Да');
      return true;
    }
  }
  return false;
}

/** Карта {ник: "Да"|"Нет"} по всей CRM (для outreach.py). */
function _readStatuses(sh) {
  var out = {};
  var last = sh.getLastRow();
  if (last < 2) return out;
  var vals = sh.getRange(2, 1, last - 1, HEADER.length).getValues();
  for (var i = 0; i < vals.length; i++) {
    var n = _normNick(vals[i][NICK_COL - 1]);
    if (!n) continue;
    var st = String(vals[i][WRITTEN_COL - 1] || '').trim();
    out[n] = (st === 'Да') ? 'Да' : 'Нет';
  }
  return out;
}

// ─────────────── РАЗОВАЯ МИГРАЦИЯ БЭКЛОГА (запуск кнопкой ▶) ───────────────
/**
 * Сливает старые повкладочные строки в «CRM» (дедуп по нику, всем «Нет») и
 * переименовывает старые вкладки в «архив_…». Старый формат вкладки:
 *   Дата | Категория | Цена (฿) | Ссылка | Автор (ник) | Краткое описание
 * Запускать ОДИН раз из редактора Apps Script (выбрать migrateBacklog → ▶ Run).
 */
function migrateBacklog() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var crm = _ensureCrmSheet();
  var sheets = ss.getSheets();
  var collected = [];
  var toArchive = [];

  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var name = sh.getName();
    if (name === CRM_TAB) continue;
    if (name.indexOf('архив_') === 0) continue; // уже в архиве
    var last = sh.getLastRow();
    if (last >= 2) {
      var data = sh.getRange(2, 1, last - 1, 6).getValues(); // старые 6 колонок
      for (var i = 0; i < data.length; i++) {
        var row = data[i];
        // старый порядок: 0 дата, 1 категория, 2 цена, 3 ссылка, 4 автор, 5 описание
        collected.push({
          author: row[4], link: row[3], channel: name,
          category: row[1], date: row[0], snippet: row[5],
        });
      }
    }
    toArchive.push(sh);
  }

  var added = _appendDedup(crm, collected); // дедуп по нику сделает сам
  for (var a = 0; a < toArchive.length; a++) {
    var old = toArchive[a];
    var newName = 'архив_' + old.getName();
    try { old.setName(newName); } catch (err) { /* имя занято — оставляем */ }
  }
  SpreadsheetApp.getActive().toast(
    'Миграция: перенесено ' + added + ' авторов, архивировано вкладок: ' + toArchive.length,
    'CRM', 10);
  return { added: added, archived: toArchive.length };
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
