/**
 * Скрипт-приёмник для Google-таблицы «Фаранг — Разведка рынка»
 * (режим мини-CRM «Присутствие», редакция 19.08.2026 — реестр согласий).
 *
 * ЧТО ИЗМЕНИЛОСЬ ПРОТИВ ПРОШЛОЙ ВЕРСИИ (коротко, для человека):
 *   1. СТРОКА = ОБЪЯВЛЕНИЕ, а не человек. Раньше один ник давал одну строку
 *      навсегда, из-за чего таблица почти перестала расти. Теперь у продавца
 *      столько строк, сколько у него объявлений. Дубли отсекаем по ССЫЛКЕ на
 *      пост (одна ссылка = одна строка), а повторную публикацию того же текста
 *      отсеивает раньше сам парсер (dedup.py).
 *   2. Объявления БЕЗ НИКА тоже записываются — как рыночные данные (цены,
 *      спрос). Написать им некому, в рассылку они не идут.
 *   3. Новые колонки: «Присутствие», «На сайте», «Тип продавца».
 *   4. Новая вкладка «Недвижимость — агентства»: туда уходят объявления, где
 *      тип продавца = бизнес И категория = недвижимость. Колонки и правила —
 *      те же самые, отличается только лист.
 *   5. Статус «на человека»: «Написали?» и «Присутствие» проставляются СРАЗУ
 *      ВСЕМ строкам одного ника, а новая строка уже написанного человека
 *      рождается с «Да» — второго письма он не получит.
 *
 * КТО КАКОЙ КОЛОНКОЙ УПРАВЛЯЕТ (решение Савелия 16.08.2026):
 *   «Написали?»    — ТОЛЬКО бот-рассыльщик (outreach.py). Он же по ней решает,
 *                    писать человеку или нет: пишем, только если «Нет».
 *                    Значения: Нет / Да / Премиум / Не доставлено.
 *   «Присутствие»  — воронка продавца. Бот её НЕ читает и НЕ трогает. Ставит
 *                    сайт (этапы 3–4 плана) и Савелий руками («отказ»).
 *                    Значения: пусто / нет ответа / согласен / зарегистрирован / отказ.
 *   «На сайте»    — этап 4, итог авто-подготовки объявления «согласного»:
 *                  «Опубликовано» (зелёным, ушло на сайт и ждёт модератора)
 *                  или «Не вышло» (красным). Пусто = ещё не пробовали, строка
 *                  стоит в очереди GET ?action=todo.
 *                    Заполняется красным; пустая ячейка = всё в порядке.
 *   «Тип продавца» — частник / бизнес, ставит ИИ при разборе поста.
 *
 * Действия (что умеет скрипт):
 *   POST {action:"append", rows:[{author,link,channel,category,category_slug,
 *         date,snippet,seller_type}]} — дописать объявления (дубли по ссылке
 *         отсекаются здесь же, вкладка выбирается автоматически);
 *   POST {action:"mark", author:"ник", value:"Да"} — статус в «Написали?»
 *         ВСЕМ строкам этого ника («Да» по умолчанию; ещё «Премиум»,
 *         «Не доставлено», «Нет»);
 *   POST {action:"presence", author:"ник", value:"согласен"} — статус в
 *         «Присутствие» всем строкам ника (задел под этапы 3–4);
 *   POST {action:"site", link:"https://t.me/…", value:"Опубликовано"} —
 *         итог авто-подготовки конкретного объявления: «Опубликовано» /
 *         «Не вышло» / пусто (этап 4);
 *   GET  ?action=todo&limit=30&days=30 — очередь авто-подготовки: строки
 *         согласившихся, которые ещё не пробовали выложить на сайт;
 *   POST {action:"consent", nick:"ник", status:"согласен", reason:"почему"} —
 *         запись в РЕЕСТР СОГЛАСИЙ (вкладка «Согласия») + «Присутствие» всем
 *         строкам ника. Этим действием пользуется САЙТ: публикация объявления
 *         «за автора» → «согласен», первый вход автора через Telegram →
 *         «зарегистрирован». «Отказ» Савелий ставит руками в реестре;
 *   GET  ?action=statuses — отдать карту {ник: статус «Написали?»};
 *   GET  ?action=consents — отдать карту {ник: статус согласия};
 *   GET                   — проверка «живой ли» (alive).
 * Во всех запросах обязателен общий пароль-токен (token), кроме простого alive.
 *
 * РЕЕСТР СОГЛАСИЙ (вкладка «Согласия», этап 3 плана мини-CRM):
 *   Одна строка на человека: Ник | Статус | Когда | Основание.
 *   Это единственный источник правды о согласии — сервер разведки в базу сайта
 *   не ходит вообще. Статусы по силе: отказ > зарегистрирован > согласен;
 *   слабый не перезаписывает сильный, поэтому автоматика с сайта не затрёт
 *   ручной отказ. Лист защищён «мягко» (предупреждение при правке).
 *   Статус из реестра сильнее соседних строк: новое объявление человека сразу
 *   рождается с его настоящим статусом.
 *
 * ФУНКЦИИ ПОД КНОПКУ ▶ Run (запускать прямо в редакторе Apps Script):
 *   syncConsents()       — пересчитать «Присутствие» во всех строках по
 *      реестру. Нужен после разовой заливки ников из базы и после ручных
 *      правок реестра. Запускать можно сколько угодно раз.
 *
 * РАЗОВЫЕ МИГРАЦИИ (запускать кнопкой ▶ Run прямо в редакторе Apps Script):
 *   migrateAddColumns()  — ГЛАВНАЯ для этой версии: дописывает три новые
 *      колонки в существующую вкладку CRM, создаёт вкладку агентств и
 *      заполняет «Присутствие» у тех, кому уже писали («Да» → «нет ответа»).
 *      Данные не теряются, запускать можно повторно — лишнего не сделает.
 *   migrateBacklog()     — старая, для перехода с повкладочного формата.
 *
 * Как обновить (после правок этого файла):
 *   1. Таблица → «Расширения» → «Apps Script» → заменить весь код этим файлом.
 *   2. Вписать TOKEN ниже (тот же, что в .env → SHEET_TOKEN).
 *   3. Сохранить (дискета) → «Развернуть» → «Управление развёртываниями» →
 *      карандаш → «Версия: Создать» → «Развернуть». URL (…/exec) НЕ меняется.
 *   4. Выбрать в списке функций migrateAddColumns → ▶ Run (один раз).
 */
var TOKEN = 'PASTE_YOUR_TOKEN_HERE'; // тот же, что в .env (SHEET_TOKEN)

var CRM_TAB = 'CRM';
var AGENCY_TAB = 'Недвижимость — агентства';
var CONSENT_TAB = 'Согласия';   // реестр согласий (этап 3 плана мини-CRM)

var HEADER = ['Ник', 'Ссылка', 'Канал', 'Категория', 'Дата', 'Описание',
              'Написали?', 'Присутствие', 'На сайте', 'Тип продавца'];
var NICK_COL = 1;       // A — ник автора (может быть пустым)
var LINK_COL = 2;       // B — ссылка на пост (ключ дубля)
var WRITTEN_COL = 7;    // G — «Написали?» (управляет бот-рассыльщик)
var PRESENCE_COL = 8;   // H — «Присутствие» (воронка; бот не трогает)
var SITE_COL = 9;       // I — «На сайте» (этап 4: результат авто-подготовки)
var NOSITE_COL = SITE_COL; // старое имя — чтобы не ломать прежние вызовы
var SELLER_COL = 10;    // J — «Тип продавца» (ставит ИИ)

// ── значения колонки «Написали?» ──
var ST_DONE = 'Да';
var ST_TODO = 'Нет';
var ST_PREMIUM = 'Премиум';             // пишут только Premium — вручную
var ST_UNDELIVERABLE = 'Не доставлено'; // личка закрыта, ник исчез
var STATUSES = [ST_DONE, ST_TODO, ST_PREMIUM, ST_UNDELIVERABLE];

// ── значения колонки «Присутствие» (пусто = ещё не трогали) ──
var PR_NO_ANSWER = 'нет ответа';
var PR_AGREED = 'согласен';
var PR_REGISTERED = 'зарегистрирован';
var PR_REFUSED = 'отказ';
var PRESENCES = [PR_NO_ANSWER, PR_AGREED, PR_REGISTERED, PR_REFUSED];

// ── значения колонки «Тип продавца» ──
var SELLER_PRIVATE = 'частник';
var SELLER_BUSINESS = 'бизнес';
var SELLERS = [SELLER_PRIVATE, SELLER_BUSINESS];

// Результат авто-подготовки объявления (этап 4). Пусто = ещё не пробовали.
var SITE_OK = 'Опубликовано';   // ушло на сайт, ждёт модератора
var SITE_FAIL = 'Не вышло';     // не получилось (нет фото, не разобрана цена…)
var SITE_VALUES = [SITE_OK, SITE_FAIL];
var NOSITE_MARK = SITE_FAIL;    // старое имя
var REALTY_SLUG = 'realty'; // категория недвижимости (см. categories.py)

// ── РЕЕСТР СОГЛАСИЙ (вкладка «Согласия»), этап 3 плана мини-CRM ──
// Одна строка на человека. Это ЕДИНСТВЕННЫЙ источник правды о том, кто нам
// разрешил (или запретил) работать с его объявлениями: сервер разведки в базу
// сайта не ходит, сайт сам сообщает сюда о событиях.
var CONSENT_HEADER = ['Ник', 'Статус', 'Когда', 'Основание'];
var C_NICK_COL = 1;    // A — ник без @, нижним регистром
var C_STATUS_COL = 2;  // B — согласен / зарегистрирован / отказ
var C_WHEN_COL = 3;    // C — дата события (ГГГГ-ММ-ДД)
var C_REASON_COL = 4;  // D — основание («опубликовано объявление за автора» и т.п.)
var CONSENT_STATUSES = [PR_AGREED, PR_REGISTERED, PR_REFUSED];

// Сила статуса: больше — сильнее. Слабый НЕ перезаписывает сильный, чтобы
// сайт своим автоматическим «согласен» не затёр отказ, поставленный руками.
// Снять «отказ» может только человек — правкой ячейки в реестре.
var CONSENT_RANK = {};
CONSENT_RANK[PR_AGREED] = 1;
CONSENT_RANK[PR_REGISTERED] = 2;
CONSENT_RANK[PR_REFUSED] = 3;

// ── цвета ──
var GREEN = '#b7e1cd';   // строка целиком: «Написали?» = Да
var YELLOW = '#ffe599';  // строка целиком: «Премиум»
var GREY = '#d9d9d9';    // строка целиком: «Не доставлено»
var PR_YELLOW = '#fff2cc'; // ячейка «Присутствие»: нет ответа
var PR_GREEN = '#a8d08d';  // ячейка «Присутствие»: согласен
var PR_BLUE = '#9fc5e8';   // ячейка «Присутствие»: зарегистрирован
var PR_RED = '#f4cccc';    // ячейка «Присутствие»: отказ
var RED = '#e06666';       // ячейка «На сайте» = «Не вышло»

// ─────────────────────────── ПРИЁМ (POST) ───────────────────────────
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var action = String(body.action || 'append');
    var tabs = _ensureTabs();

    if (action === 'mark') {
      var found = _setForNick(tabs, body.author, WRITTEN_COL,
                              _safeStatus(body.value));
      return _json({ ok: true, found: found });
    }

    if (action === 'presence') {
      var foundP = _setForNick(tabs, body.author, PRESENCE_COL,
                               _safePresence(body.value));
      return _json({ ok: true, found: foundP });
    }

    if (action === 'consent') {
      return _json(_setConsent(tabs, body.nick || body.author,
                               body.status || body.value, body.reason));
    }

    if (action === 'nosite' || action === 'site') {
      var foundN = _setForLink(tabs, body.link, SITE_COL, _safeSite(body.value));
      return _json({ ok: true, found: foundN });
    }

    // action === 'append' (по умолчанию)
    var rows = body.rows;
    if (!rows) {
      rows = [{
        author: body.author, link: body.link, channel: body.channel,
        category: body.category, category_slug: body.category_slug,
        date: body.date, snippet: body.snippet, seller_type: body.seller_type,
      }];
    }
    var written = _appendDedup(tabs, rows);
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
    return _json({ ok: true, statuses: _readStatuses(_ensureTabs()) });
  }

  if (action === 'consents') {
    if (params.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var map = _readConsents(_ensureTabs().consent);
    var out = {};
    for (var nick in map) {
      if (map.hasOwnProperty(nick)) out[nick] = map[nick].status;
    }
    return _json({ ok: true, consents: out });
  }

  if (action === 'todo') {
    if (params.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    var limit = parseInt(params.limit, 10);
    if (!limit || limit < 1) limit = 50;
    var days = parseInt(params.days, 10);
    if (!days || days < 1) days = 0; // 0 = без ограничения по возрасту
    return _json({ ok: true, rows: _readTodo(_ensureTabs(), limit, days) });
  }

  return _json({ ok: true, alive: true });
}

/**
 * Очередь авто-подготовки (этап 4): объявления продавцов, давших согласие,
 * которые мы ещё не пробовали выложить на сайт.
 *
 * Условия строки: есть ник, «Присутствие» = «согласен», колонка «На сайте»
 * пуста. Сортировка — от свежих к старым (мы публикуем актуальное, а не
 * позапрошлогоднее). `days` > 0 отсекает посты старше указанного числа дней.
 */
function _readTodo(tabs, limit, days) {
  var sheets = [tabs.crm, tabs.agency];
  var out = [];
  var minTime = 0;
  if (days > 0) minTime = new Date().getTime() - days * 24 * 60 * 60 * 1000;

  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var vals = sh.getRange(2, 1, last - 1, HEADER.length).getValues();
    for (var i = 0; i < vals.length; i++) {
      var row = vals[i];
      var nick = _normNick(row[NICK_COL - 1]);
      if (!nick) continue;
      if (_safePresence(row[PRESENCE_COL - 1]) !== PR_AGREED) continue;
      if (String(row[SITE_COL - 1] || '').trim() !== '') continue;
      var link = String(row[LINK_COL - 1] || '').trim();
      if (!link) continue;

      var when = row[4]; // E — «Дата»
      var time = 0;
      if (when instanceof Date) time = when.getTime();
      else if (when) {
        var parsed = new Date(String(when).replace(' ', 'T'));
        if (!isNaN(parsed.getTime())) time = parsed.getTime();
      }
      if (minTime && time && time < minTime) continue;

      out.push({ nick: nick, link: link, time: time });
    }
  }

  out.sort(function (a, b) { return b.time - a.time; });
  return out.slice(0, limit);
}

// ─────────────────────────── ВКЛАДКИ ───────────────────────────
/** Обе рабочие вкладки: основная CRM и «Недвижимость — агентства».
 *  Создаёт их при первом обращении (шапка, дропдауны, подсветка). */
function _ensureTabs() {
  return {
    crm: _ensureSheet(CRM_TAB, 0),
    agency: _ensureSheet(AGENCY_TAB, 1),
    consent: _ensureConsentSheet(),
  };
}

/** Вкладка «Согласия» — реестр (этап 3). Создаётся при первом обращении:
 *  шапка, выпадающий список статусов, подсветка и мягкая защита листа
 *  (предупреждение при попытке править — чтобы реестр не стёрли случайно). */
function _ensureConsentSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(CONSENT_TAB);
  if (!sh) {
    sh = ss.insertSheet(CONSENT_TAB, 2);
    sh.appendRow(CONSENT_HEADER);
    sh.setFrozenRows(1);
  } else if (sh.getLastColumn() === 0) {
    sh.appendRow(CONSENT_HEADER);
    sh.setFrozenRows(1);
  }
  var cur = sh.getRange(1, 1, 1, CONSENT_HEADER.length).getValues()[0];
  var changed = false;
  for (var i = 0; i < CONSENT_HEADER.length; i++) {
    if (String(cur[i] || '').trim() === '') { cur[i] = CONSENT_HEADER[i]; changed = true; }
  }
  if (changed) {
    sh.getRange(1, 1, 1, CONSENT_HEADER.length).setValues([cur]);
    sh.setFrozenRows(1);
  }
  var rows = sh.getMaxRows() - 1;
  if (rows > 0) {
    sh.getRange(2, C_STATUS_COL, rows, 1)
      .setDataValidation(_listRule(CONSENT_STATUSES, true));
    var pairs = [[PR_AGREED, PR_GREEN], [PR_REGISTERED, PR_BLUE], [PR_REFUSED, PR_RED]];
    var rng = sh.getRange(2, 1, rows, CONSENT_HEADER.length);
    var rules = [];
    for (var j = 0; j < pairs.length; j++) {
      rules.push(SpreadsheetApp.newConditionalFormatRule()
        .whenFormulaSatisfied('=$B2="' + pairs[j][0] + '"')
        .setBackground(pairs[j][1])
        .setRanges([rng])
        .build());
    }
    sh.setConditionalFormatRules(rules);
  }
  _protectConsent(sh);
  return sh;
}

/** Мягкая защита реестра: Google предупредит перед правкой, но не запретит.
 *  Реестр — единственный источник правды; потеряем его — люди получат
 *  повторные письма (раздел 5 плана мини-CRM). */
function _protectConsent(sh) {
  try {
    var existing = sh.getProtections(SpreadsheetApp.ProtectionType.SHEET);
    if (existing && existing.length) return;
    sh.protect()
      .setDescription('Реестр согласий — единственный источник правды. Правьте осознанно.')
      .setWarningOnly(true);
  } catch (err) {
    // В тестовой среде (или без прав) защиты нет — это не повод падать.
  }
}

function _ensureSheet(name, position) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name, position);
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
  } else if (sh.getLastColumn() === 0) {
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
  }
  _ensureWidth(sh);
  _ensureHeader(sh);
  _ensureValidation(sh);
  _ensureColorRules(sh);
  return sh;
}

/** Лист должен вмещать все наши колонки (у старых вкладок их было 7). */
function _ensureWidth(sh) {
  var need = HEADER.length;
  if (sh.getMaxColumns() < need) {
    sh.insertColumnsAfter(sh.getMaxColumns(), need - sh.getMaxColumns());
  }
}

/** Дописывает недостающие заголовки, не трогая уже существующие. */
function _ensureHeader(sh) {
  var cur = sh.getRange(1, 1, 1, HEADER.length).getValues()[0];
  var changed = false;
  for (var i = 0; i < HEADER.length; i++) {
    var was = String(cur[i] || '').trim();
    if (was === '') { cur[i] = HEADER[i]; changed = true; }
    // Переименование колонки I со старого названия (до этапа 4).
    else if (i === SITE_COL - 1 && was === 'Нет на сайте') {
      cur[i] = HEADER[i]; changed = true;
    }
  }
  if (changed) {
    sh.getRange(1, 1, 1, HEADER.length).setValues([cur]);
    sh.setFrozenRows(1);
  }
}

/** Выпадашки: «Написали?», «Присутствие», «Тип продавца». */
function _ensureValidation(sh) {
  var maxRows = sh.getMaxRows();
  if (maxRows < 2) return;
  var n = maxRows - 1;
  sh.getRange(2, WRITTEN_COL, n, 1).setDataValidation(_listRule(STATUSES, false));
  // «Присутствие» и «Тип продавца» — allowInvalid=true: пустая ячейка это
  // нормальное состояние, ругаться на неё не нужно.
  sh.getRange(2, PRESENCE_COL, n, 1).setDataValidation(_listRule(PRESENCES, true));
  sh.getRange(2, SELLER_COL, n, 1).setDataValidation(_listRule(SELLERS, true));
  sh.getRange(2, SITE_COL, n, 1).setDataValidation(_listRule(SITE_VALUES, true));
}

function _listRule(values, allowInvalid) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(allowInvalid)
    .build();
}

/**
 * Подсветка. Порядок важен: Google применяет ПЕРВОЕ подошедшее правило,
 * поэтому сначала идут точечные правила по отдельным ячейкам («Присутствие»,
 * «На сайте»), и только потом — заливка всей строки по «Написали?».
 * Иначе строка перекрасила бы ячейку воронки и её не было бы видно.
 */
function _ensureColorRules(sh) {
  var rows = Math.max(1, sh.getMaxRows() - 1);
  var presenceRng = sh.getRange(2, PRESENCE_COL, rows, 1);
  var nositeRng = sh.getRange(2, NOSITE_COL, rows, 1);
  var rowRng = sh.getRange(2, 1, rows, HEADER.length);
  var rules = [];

  var prPairs = [
    [PR_NO_ANSWER, PR_YELLOW], [PR_AGREED, PR_GREEN],
    [PR_REGISTERED, PR_BLUE], [PR_REFUSED, PR_RED],
  ];
  for (var i = 0; i < prPairs.length; i++) {
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$H2="' + prPairs[i][0] + '"')
      .setBackground(prPairs[i][1])
      .setRanges([presenceRng])
      .build());
  }

  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$I2="' + SITE_OK + '"')
    .setBackground(PR_GREEN)
    .setRanges([nositeRng])
    .build());
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=LEN($I2)>0')
    .setBackground(RED)
    .setFontColor('#ffffff')
    .setRanges([nositeRng])
    .build());

  var stPairs = [[ST_DONE, GREEN], [ST_PREMIUM, YELLOW], [ST_UNDELIVERABLE, GREY]];
  for (var j = 0; j < stPairs.length; j++) {
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$G2="' + stPairs[j][0] + '"')
      .setBackground(stPairs[j][1])
      .setRanges([rowRng])
      .build());
  }

  sh.setConditionalFormatRules(rules);
}

// ─────────────────────────── ЯДРО ───────────────────────────
/** Нормализованный ник: без @, нижний регистр, без пробелов по краям. */
function _normNick(v) {
  return String(v == null ? '' : v).replace(/^@+/, '').trim().toLowerCase();
}

/** Нормализованная ссылка (ключ дубля объявления). */
function _normLink(v) {
  return String(v == null ? '' : v).trim().toLowerCase().replace(/\/+$/, '');
}

function _safeStatus(v) {
  var s = String(v == null ? '' : v).trim();
  return STATUSES.indexOf(s) === -1 ? ST_DONE : s;
}

function _safePresence(v) {
  var s = String(v == null ? '' : v).trim().toLowerCase();
  if (s === '') return '';
  return PRESENCES.indexOf(s) === -1 ? '' : s;
}

/** Значение колонки «На сайте»: только «Опубликовано», «Не вышло» или пусто. */
function _safeSite(v) {
  var s = String(v == null ? '' : v).trim();
  if (s === '') return '';
  if (s === SITE_OK || s === SITE_FAIL) return s;
  // Любое другое непустое значение (в т.ч. старое «Нет на сайте») = неудача.
  return SITE_FAIL;
}

function _safeSeller(v) {
  var s = String(v == null ? '' : v).trim().toLowerCase();
  return SELLERS.indexOf(s) === -1 ? '' : s;
}

function _safeConsent(v) {
  var s = String(v == null ? '' : v).trim().toLowerCase();
  return CONSENT_STATUSES.indexOf(s) === -1 ? '' : s;
}

/** Сегодняшняя дата как ГГГГ-ММ-ДД (пишем её в колонку «Когда»). */
function _today() {
  var d = new Date();
  var pad = function (n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

/** Реестр целиком: {ник: {status, when, reason, row}}. */
function _readConsents(sh) {
  var out = {};
  if (!sh) return out;
  var last = sh.getLastRow();
  if (last < 2) return out;
  var vals = sh.getRange(2, 1, last - 1, CONSENT_HEADER.length).getValues();
  for (var i = 0; i < vals.length; i++) {
    var nick = _normNick(vals[i][C_NICK_COL - 1]);
    if (!nick) continue;
    var status = _safeConsent(vals[i][C_STATUS_COL - 1]);
    if (!status) continue;
    var prev = out[nick];
    // Если ник случайно попал в реестр дважды — оставляем сильный статус.
    if (prev && CONSENT_RANK[prev.status] >= CONSENT_RANK[status]) continue;
    out[nick] = {
      status: status,
      when: String(vals[i][C_WHEN_COL - 1] || ''),
      reason: String(vals[i][C_REASON_COL - 1] || ''),
      row: i + 2,
    };
  }
  return out;
}

/**
 * Записывает событие в реестр и сразу проставляет «Присутствие» во ВСЕХ
 * строках этого ника (обе рабочие вкладки).
 * Слабый статус не перезаписывает сильный: «отказ» > «зарегистрирован» >
 * «согласен». Так автоматическое сообщение с сайта не затрёт ручной отказ.
 */
function _setConsent(tabs, nickRaw, statusRaw, reason) {
  var nick = _normNick(nickRaw);
  var status = _safeConsent(statusRaw);
  if (!nick) return { ok: false, error: 'empty nick' };
  if (!status) return { ok: false, error: 'bad status' };

  var sh = tabs.consent;
  var map = _readConsents(sh);
  var cur = map[nick];

  if (cur && CONSENT_RANK[cur.status] > CONSENT_RANK[status]) {
    // Сильнее того, что пришло, — ничего не меняем, но статус в строках
    // на всякий случай подравниваем под реестр.
    return {
      ok: true, nick: nick, status: cur.status, kept: true,
      found: _setForNick(tabs, nick, PRESENCE_COL, cur.status),
    };
  }

  var when = _today();
  var note = String(reason == null ? '' : reason);
  if (cur) {
    sh.getRange(cur.row, C_STATUS_COL, 1, 3).setValues([[status, when, note]]);
  } else {
    sh.appendRow([nick, status, when, note]);
  }
  return {
    ok: true, nick: nick, status: status, kept: false,
    found: _setForNick(tabs, nick, PRESENCE_COL, status),
  };
}

/** Читает лист один раз и отдаёт: ссылки (для дедупа) и статусы по никам. */
function _scan(sh, links, byNick) {
  var last = sh.getLastRow();
  if (last < 2) return;
  var vals = sh.getRange(2, 1, last - 1, PRESENCE_COL).getValues();
  for (var i = 0; i < vals.length; i++) {
    var link = _normLink(vals[i][LINK_COL - 1]);
    if (link) links[link] = true;
    var nick = _normNick(vals[i][NICK_COL - 1]);
    if (!nick) continue;
    var written = String(vals[i][WRITTEN_COL - 1] || '').trim();
    var presence = String(vals[i][PRESENCE_COL - 1] || '').trim().toLowerCase();
    var cur = byNick[nick] || { written: ST_TODO, presence: '' };
    // «Сильный» статус побеждает: если человеку уже писали хоть по одной
    // строке, новая строка не должна вернуть его в очередь на письмо.
    if (written && written !== ST_TODO) cur.written = written;
    if (presence) cur.presence = presence;
    byNick[nick] = cur;
  }
}

/** На какую вкладку кладём объявление: агентства недвижимости — отдельно. */
function _pickTab(row) {
  var slug = String(row.category_slug || '').trim().toLowerCase();
  var seller = _safeSeller(row.seller_type);
  if (slug === REALTY_SLUG && seller === SELLER_BUSINESS) return AGENCY_TAB;
  return CRM_TAB;
}

/**
 * Дописывает объявления. Дубль = ТА ЖЕ ССЫЛКА (уже в таблице или в этой же
 * пачке). Объявления без ника записываем — это рыночные данные.
 * Новая строка наследует «Написали?» и «Присутствие» своего ника.
 * Возвращает число реально добавленных строк.
 */
function _appendDedup(tabs, rows) {
  var links = {};
  var byNick = {};
  _scan(tabs.crm, links, byNick);
  _scan(tabs.agency, links, byNick);
  // Реестр согласий важнее соседних строк: если человек уже согласился или
  // отказался, его новое объявление сразу получает правильный статус.
  var consents = _readConsents(tabs.consent);

  var buckets = {};
  buckets[CRM_TAB] = [];
  buckets[AGENCY_TAB] = [];
  var total = 0;

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var link = _normLink(r.link);
    if (!link || links[link]) continue; // без ссылки или дубль — пропускаем
    links[link] = true;

    var nick = _normNick(r.author);
    var st = (nick && byNick[nick]) ? byNick[nick] : { written: ST_TODO, presence: '' };
    var presence = (nick && consents[nick]) ? consents[nick].status : st.presence;

    buckets[_pickTab(r)].push([
      r.author || '', r.link || '', r.channel || '', r.category || '',
      r.date || '', r.snippet || '', st.written, presence, '',
      _safeSeller(r.seller_type),
    ]);
    total++;
  }

  _writeBucket(tabs.crm, buckets[CRM_TAB]);
  _writeBucket(tabs.agency, buckets[AGENCY_TAB]);
  return total;
}

function _writeBucket(sh, values) {
  if (!values || values.length === 0) return;
  var startRow = sh.getLastRow() + 1;
  sh.getRange(startRow, 1, values.length, HEADER.length).setValues(values);
  _ensureValidation(sh);
  _ensureColorRules(sh);
}

/** Ставит значение в колонку ВСЕМ строкам одного ника (обе вкладки).
 *  Возвращает, сколько строк поправили. */
function _setForNick(tabs, author, col, value) {
  var target = _normNick(author);
  if (!target) return 0;
  return _setWhere(tabs, NICK_COL, _normNick, target, col, value);
}

/** Ставит значение в колонку строке с конкретной ссылкой (обе вкладки). */
function _setForLink(tabs, link, col, value) {
  var target = _normLink(link);
  if (!target) return 0;
  return _setWhere(tabs, LINK_COL, _normLink, target, col, value);
}

function _setWhere(tabs, keyCol, normFn, target, col, value) {
  var sheets = [tabs.crm, tabs.agency];
  var touched = 0;
  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var keys = sh.getRange(2, keyCol, last - 1, 1).getValues();
    var target_ = sh.getRange(2, col, last - 1, 1);
    var cur = target_.getValues();
    var changed = false;
    for (var i = 0; i < keys.length; i++) {
      if (normFn(keys[i][0]) === target && String(cur[i][0]) !== String(value)) {
        cur[i][0] = value;
        changed = true;
        touched++;
      }
    }
    if (changed) target_.setValues(cur);
  }
  return touched;
}

/** Карта {ник: статус «Написали?»} по обеим вкладкам (для outreach.py).
 *  У человека много строк — берём «сильный» статус (любой, кроме «Нет»). */
function _readStatuses(tabs) {
  var links = {};
  var byNick = {};
  _scan(tabs.crm, links, byNick);
  _scan(tabs.agency, links, byNick);
  var out = {};
  for (var nick in byNick) {
    if (!byNick.hasOwnProperty(nick)) continue;
    var st = byNick[nick].written;
    out[nick] = (STATUSES.indexOf(st) === -1) ? ST_TODO : st;
  }
  return out;
}

// ─────────── МЕНЮ В САМОЙ ТАБЛИЦЕ ───────────
/**
 * Добавляет в таблицу меню «Фаранг» при её открытии. Нужно, чтобы пересчёт по
 * реестру можно было запустить мышью из таблицы, не заходя в редактор скрипта
 * (в редакторе выбрать функцию для ▶ Run бывает неудобно).
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Фаранг')
    .addItem('Пересчитать «Присутствие» по реестру', 'syncConsents')
    .addToUi();
}

// ─────────── ПЕРЕСЧЁТ ПО РЕЕСТРУ (кнопка ▶ или меню «Фаранг») ───────────
/**
 * Проходит по вкладке «Согласия» и проставляет «Присутствие» всем строкам
 * каждого ника на обеих рабочих вкладках. Нужен после разовой заливки ников
 * из базы сайта и вообще всякий раз, когда реестр правили руками.
 * Безопасен: запускать можно сколько угодно раз.
 */
function syncConsents() {
  var tabs = _ensureTabs();
  var map = _readConsents(tabs.consent);
  var people = 0;
  for (var nick in map) { if (map.hasOwnProperty(nick)) people++; }

  // Один проход по каждому листу: читаем ники и «Присутствие» разом, считаем
  // новые значения в памяти и пишем одним setValues. Поштучный обход (по ника
  // на каждый лист) для 200+ человек не укладывался в лимит времени Apps Script.
  var touched = 0;
  var sheets = [tabs.crm, tabs.agency];
  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var n = last - 1;
    var nicks = sh.getRange(2, NICK_COL, n, 1).getValues();
    var rng = sh.getRange(2, PRESENCE_COL, n, 1);
    var cur = rng.getValues();
    var changed = false;
    for (var i = 0; i < n; i++) {
      var key = _normNick(nicks[i][0]);
      if (!key || !map[key]) continue;
      var want = map[key].status;
      if (String(cur[i][0]) === String(want)) continue;
      cur[i][0] = want;
      changed = true;
      touched++;
    }
    if (changed) rng.setValues(cur);
  }
  SpreadsheetApp.getActive().toast(
    'Реестр: людей ' + people + ', поправлено строк: ' + touched,
    'Согласия', 10);
  return { people: people, touched: touched };
}

// ─────────── МИГРАЦИЯ ПОД НОВЫЕ КОЛОНКИ (запуск кнопкой ▶) ───────────
/**
 * Готовит существующую таблицу к режиму мини-CRM:
 *   - расширяет вкладку CRM до 10 колонок и дописывает новые заголовки;
 *   - создаёт вкладку «Недвижимость — агентства» с той же шапкой;
 *   - у строк, где «Написали?» = «Да», проставляет «Присутствие» = «нет ответа»
 *     (мы написали, ответа не было) — чтобы воронка не начиналась с чистого
 *     листа. Остальным «Присутствие» остаётся пустым.
 * Ничего не удаляет. Запускать можно повторно — лишнего не сделает.
 */
function migrateAddColumns() {
  var tabs = _ensureTabs();
  var filled = 0;
  var sheets = [tabs.crm, tabs.agency];
  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var written = sh.getRange(2, WRITTEN_COL, last - 1, 1).getValues();
    var presRng = sh.getRange(2, PRESENCE_COL, last - 1, 1);
    var pres = presRng.getValues();
    var changed = false;
    for (var i = 0; i < written.length; i++) {
      var cur = String(pres[i][0] || '').trim();
      if (cur) continue; // уже заполнено руками — не трогаем
      if (String(written[i][0] || '').trim() === ST_DONE) {
        pres[i][0] = PR_NO_ANSWER;
        filled++;
        changed = true;
      }
    }
    if (changed) presRng.setValues(pres);
  }
  SpreadsheetApp.getActive().toast(
    'Готово. Колонки на месте, вкладка агентств создана. ' +
    '«Присутствие» = «нет ответа» проставлено строкам: ' + filled,
    'мини-CRM «Присутствие»', 10);
  return { filled: filled };
}

// ─────────────── СТАРАЯ МИГРАЦИЯ БЭКЛОГА (запуск кнопкой ▶) ───────────────
/**
 * Сливает старые повкладочные строки в «CRM» и переименовывает старые вкладки
 * в «архив_…». Старый формат вкладки:
 *   Дата | Категория | Цена (฿) | Ссылка | Автор (ник) | Краткое описание
 * Нужна была ОДИН раз при переходе на CRM; оставлена для истории.
 */
function migrateBacklog() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var tabs = _ensureTabs();
  var sheets = ss.getSheets();
  var collected = [];
  var toArchive = [];

  for (var s = 0; s < sheets.length; s++) {
    var sh = sheets[s];
    var name = sh.getName();
    if (name === CRM_TAB || name === AGENCY_TAB) continue;
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

  var added = _appendDedup(tabs, collected);
  for (var a = 0; a < toArchive.length; a++) {
    var old = toArchive[a];
    try { old.setName('архив_' + old.getName()); } catch (err) { /* имя занято */ }
  }
  SpreadsheetApp.getActive().toast(
    'Миграция: перенесено строк ' + added + ', архивировано вкладок: ' + toArchive.length,
    'CRM', 10);
  return { added: added, archived: toArchive.length };
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
