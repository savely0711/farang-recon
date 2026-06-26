/**
 * Скрипт-приёмник для Google-таблицы «Фаранг — Разведка рынка».
 *
 * Что делает: принимает от парсера одну строку-объявление (POST с JSON)
 * и дописывает её в нужную вкладку. Если вкладки канала ещё нет — создаёт
 * её с шапкой. Доступ защищён общим паролём-токеном.
 *
 * Как развернуть (один раз):
 *   1. Открыть таблицу → меню «Расширения» → «Apps Script».
 *   2. Удалить пример кода, вставить этот файл целиком.
 *   3. В строке TOKEN ниже вписать свой пароль (тот же, что в .env → SHEET_TOKEN).
 *   4. Сохранить (значок дискеты).
 *   5. «Развернуть» → «Новое развёртывание» → шестерёнка → тип «Веб-приложение».
 *      • «Запуск от имени»: Я
 *      • «У кого есть доступ»: Все (Anyone)
 *      → «Развернуть» → разрешить доступ к своему аккаунту.
 *   6. Скопировать «URL веб-приложения» (…/exec) → это SHEET_WEBHOOK_URL в .env.
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
    sh.appendRow([
      body.date || '',
      body.category || '',
      body.price || '',
      body.link || '',
      body.snippet || ''
    ]);
    return _json({ ok: true });
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
