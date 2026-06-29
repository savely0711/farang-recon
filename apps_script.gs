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
var HEADER = ['Дата', 'Категория', 'Цена (฿)', 'Ссылка', 'Краткое описание'];

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
    }

    // Пачка строк (новый формат) или одна строка (старый) — приводим к массиву.
    var rows = body.rows;
    if (!rows) {
      rows = [{
        date: body.date, category: body.category, price: body.price,
        link: body.link, snippet: body.snippet
      }];
    }

    if (rows.length > 0) {
      var values = rows.map(function (r) {
        return [r.date || '', r.category || '', r.price || '', r.link || '', r.snippet || ''];
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

// Удобно для проверки в браузере: открыть /exec — ответит, что живой.
function doGet() {
  return _json({ ok: true, alive: true });
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
