/**
 * Скрипт-приёмник для Google-таблицы «Фаранг — Разведка рынка».
 *
 * Что делает: принимает от парсера объявления (POST с JSON) и дописывает их
 * в нужную вкладку. Принимает как ПАЧКУ строк (поле rows — массив), так и одну
 * строку (старый формат). Если вкладки канала ещё нет — создаёт её с шапкой.
 * Доступ защищён общим паролём-токеном.
 *
 * Как развернуть/обновить:
 *   1. Открыть таблицу → меню «Расширения» → «Apps Script».
 *   2. Заменить весь код этим файлом.
 *   3. В строке TOKEN ниже вписать свой пароль (тот же, что в .env → SHEET_TOKEN).
 *   4. Сохранить (значок дискеты).
 *   5. ОБНОВЛЕНИЕ существующего: «Развернуть» → «Управление развёртываниями» →
 *      карандаш (изменить) → «Версия: Создать» → «Развернуть». URL НЕ меняется.
 *      ПЕРВЫЙ раз: «Развернуть» → «Новое развёртывание» → тип «Веб-приложение»,
 *      «Запуск от имени»: Я, «У кого есть доступ»: Все → «Развернуть».
 *   6. URL веб-приложения (…/exec) → это SHEET_WEBHOOK_URL в .env.
 */
var TOKEN = 'PASTE_YOUR_TOKEN_HERE'; // тот же, что в .env (SHEET_TOKEN)
var HEADER = ['Дата', 'Категория', 'Цена (฿)', 'Ссылка', 'Автор (ник)', 'Краткое описание'];
var AUTHOR_COL = 5; // позиция колонки «Автор (ник)» (после «Ссылки»)

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var tab = String(body.tab || 'Разное');
    var sh = ss.getSheetByName(tab);
    if (!sh) {
      sh = ss.insertSheet(tab);
      sh.appendRow(HEADER);
    } else {
      _ensureAuthorColumn(sh); // старые вкладки (5 колонок) — добавить «Автор (ник)»
    }

    // Пачка строк (новый формат) или одна строка (старый) — приводим к массиву.
    var rows = body.rows;
    if (!rows) {
      rows = [{
        date: body.date, category: body.category, price: body.price,
        link: body.link, author: body.author, snippet: body.snippet
      }];
    }

    if (rows.length > 0) {
      var values = rows.map(function (r) {
        return [r.date || '', r.category || '', r.price || '', r.link || '', r.author || '', r.snippet || ''];
      });
      // Один блочный setValues — быстро и без упора в лимиты (не по строке).
      var startRow = sh.getLastRow() + 1;
      sh.getRange(startRow, 1, values.length, HEADER.length).setValues(values);
    }
    return _json({ ok: true, written: rows.length });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

/**
 * Достраивает колонку «Автор (ник)» в СТАРЫХ вкладках (сделанных до 13.07,
 * когда было 5 колонок). Вставляет пустую колонку на позицию 5 — старые строки
 * при этом остаются выровненными (описание аккуратно сдвигается в 6-ю колонку),
 * и переписывает шапку. Если колонка уже есть — ничего не делает.
 */
function _ensureAuthorColumn(sh) {
  var lastCol = sh.getLastColumn();
  if (lastCol === 0) { sh.appendRow(HEADER); return; }
  var hdr = sh.getRange(1, 1, 1, lastCol).getValues()[0];
  if (hdr.indexOf('Автор (ник)') !== -1) return; // уже мигрировали
  if (lastCol >= AUTHOR_COL) {
    sh.insertColumnBefore(AUTHOR_COL); // сдвигаем «Краткое описание» вправо
  }
  sh.getRange(1, 1, 1, HEADER.length).setValues([HEADER]);
}

// Удобно для проверки в браузере: открыть /exec — ответит, что живой.
function doGet() {
  return _json({ ok: true, alive: true });
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
