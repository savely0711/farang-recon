/**
 * Скрипт-приёмник для Google-таблицы «Фаранг — Разведка рынка»
 * (режим мини-CRM, редакция 01.09.2026 — вкладки-воронка).
 *
 * ЧТО ИЗМЕНИЛОСЬ ПРОТИВ ПРОШЛОЙ ВЕРСИИ (коротко, для человека):
 *   1. ВМЕСТО ОДНОЙ ВКЛАДКИ «CRM» — ЧЕТЫРЕ ПО СТАТУСУ ЧЕЛОВЕКА:
 *      «Новые» (новые и те, кто не ответил), «Согласен», «Отказ»,
 *      «Зарегистрирован». Строка ПЕРЕЕЗЖАЕТ сама, как только меняется статус
 *      в колонке «Присутствие» — руками, с сайта или ночной сверкой.
 *   2. Объявления БЕЗ НИКА автора уехали на отдельную вкладку «Без ника»:
 *      писать им некому, в воронке они только мешали. Оттуда строки никуда не
 *      переезжают.
 *   3. Вкладка «Недвижимость — агентства» осталась как была — это боковой
 *      список, а не воронка; её строки тоже не переезжают.
 *   4. Убрана колонка «Тип продавца» (решение Савелия 01.09.2026): агентствами
 *      теперь занимается отдельный контур недвижимости со своей таблицей.
 *   5. Колонка «На сайте» упрощена до трёх состояний: «На сайте» (было
 *      «В каталоге»), «Ждёт модератора», «Снято». «Удалено» слито со «Снято»,
 *      «Не вышло» упразднено — вместо него ячейка остаётся ПУСТОЙ, а причина
 *      прячется в примечании к ячейке (наведи мышь — увидишь).
 *
 * ПОЧЕМУ НЕУДАЧА — ПУСТАЯ ЯЧЕЙКА С ПРИМЕЧАНИЕМ, а не просто пустая.
 * Пустая ячейка означает «ещё не пробовали выложить», и авто-подготовка берёт
 * такие строки в работу. Если бы неудача была просто пустой, каждый ночной
 * прогон снова тратил бы деньги ИИ на пост, у которого, например, нет фото, —
 * и так до бесконечности. Примечание видно только при наведении, поле выглядит
 * пустым, а очередь такие строки пропускает. Захотел попробовать ещё раз —
 * меню «Фаранг» → «Очистить пометки неудач».
 *
 * КТО КАКОЙ КОЛОНКОЙ УПРАВЛЯЕТ:
 *   «Написали?»    — рассылка «первое касание». С 01.09.2026 она ОСТАНОВЛЕНА
 *                    (решение Савелия), колонка осталась как история.
 *                    Значения: Нет / Да / Премиум / Не доставлено.
 *   «Присутствие»  — воронка продавца, ОНА ЖЕ определяет вкладку.
 *                    Значения: пусто / нет ответа / согласен / зарегистрирован / отказ.
 *                    Пусто и «нет ответа» → вкладка «Новые».
 *   «На сайте»     — состояние объявления на сайте (ставит авто-подготовка,
 *                    уточняет ночная сверка): «На сайте» / «Ждёт модератора» /
 *                    «Снято». Пусто = ещё не пробовали (или неудача, тогда есть
 *                    примечание).
 *
 * Действия (что умеет скрипт):
 *   POST {action:"append", rows:[{author,link,channel,category,category_slug,
 *         date,snippet,seller_type}]} — дописать объявления (дубли по ссылке
 *         отсекаются здесь же, вкладка выбирается автоматически);
 *   POST {action:"mark", author:"ник", value:"Да"} — статус в «Написали?»
 *         ВСЕМ строкам этого ника;
 *   POST {action:"presence", author:"ник", value:"согласен"} — статус в
 *         «Присутствие» всем строкам ника + переезд строк на нужную вкладку;
 *   POST {action:"site", link:"…", value:"Ждёт модератора", note:"почему"} —
 *         итог авто-подготовки конкретного объявления. Пустое value + note =
 *         «не получилось, причина в примечании»;
 *   GET  ?action=todo&limit=30&days=30 — очередь авто-подготовки;
 *   POST {action:"consent", nick:"ник", status:"согласен", reason:"почему"} —
 *         запись в РЕЕСТР СОГЛАСИЙ (вкладка «Согласия») + «Присутствие» всем
 *         строкам ника + переезд;
 *   GET  ?action=statuses — карта {ник: статус «Написали?»};
 *   GET  ?action=consents — карта {ник: статус согласия};
 *   GET  ?action=placed — размещённые объявления для ночной сверки;
 *   GET  ?action=nicks — все ники таблицы;
 *   POST {action:"sitebulk", rows:[{link,value,note}]} — пакетная запись;
 *   POST {action:"consentbulk", rows:[{nick,status,reason}]} — пакет согласий;
 *   GET                   — проверка «живой ли» (alive).
 * Во всех запросах обязателен общий пароль-токен (token), кроме простого alive.
 *
 * РЕЕСТР СОГЛАСИЙ (вкладка «Согласия»):
 *   Одна строка на человека: Ник | Статус | Когда | Основание.
 *   Единственный источник правды о согласии — сервер разведки в базу сайта не
 *   ходит. Статусы по силе: отказ > зарегистрирован > согласен; слабый не
 *   перезаписывает сильный, поэтому автоматика не затрёт ручной отказ.
 *
 * МЕНЮ «ФАРАНГ» В САМОЙ ТАБЛИЦЕ (мышью, без редактора скрипта):
 *   «Пересчитать «Присутствие» по реестру» — syncConsents();
 *   «Разложить строки по вкладкам»          — resortTabs();
 *   «Перенести старую вкладку CRM»          — migrateTabs()  (разово);
 *   «Удалить архивные вкладки»              — dropArchiveTabs() (разово);
 *   «Очистить пометки неудач»               — clearFailNotes().
 *
 * Как обновить (после правок этого файла):
 *   1. Таблица → «Расширения» → «Apps Script» → заменить весь код этим файлом.
 *   2. Вписать TOKEN ниже (тот же, что в .env → SHEET_TOKEN).
 *   3. Сохранить (дискета) → «Развернуть» → «Управление развёртываниями» →
 *      карандаш → «Версия: Создать» → «Развернуть». URL (…/exec) НЕ меняется.
 *   4. Обновить страницу таблицы → меню «Фаранг» → «Перенести старую вкладку
 *      CRM» → убедиться, что строки разъехались → «Удалить архивные вкладки».
 */
var TOKEN = 'PASTE_YOUR_TOKEN_HERE'; // тот же, что в .env (SHEET_TOKEN)

// ── вкладки-воронка (строка переезжает при смене «Присутствия») ──
var TAB_NEW = 'Новые';              // пусто или «нет ответа»
var TAB_AGREED = 'Согласен';
var TAB_REFUSED = 'Отказ';
var TAB_REGISTERED = 'Зарегистрирован';
// ── вкладки без переездов ──
var TAB_NONICK = 'Без ника';        // у поста скрыт автор — писать некому
var AGENCY_TAB = 'Недвижимость — агентства';
var CONSENT_TAB = 'Согласия';       // реестр согласий
// Старая единая вкладка — существует только до миграции.
var LEGACY_TAB = 'CRM';

var HEADER = ['Ник', 'Ссылка', 'Канал', 'Категория', 'Дата', 'Описание',
              'Написали?', 'Присутствие', 'На сайте'];
var NICK_COL = 1;       // A — ник автора
var LINK_COL = 2;       // B — ссылка на пост (ключ дубля)
var WRITTEN_COL = 7;    // G — «Написали?» (рассылка остановлена, колонка-история)
var PRESENCE_COL = 8;   // H — «Присутствие» (воронка; определяет вкладку)
var SITE_COL = 9;       // I — «На сайте»
var NOSITE_COL = SITE_COL; // старое имя — чтобы не ломать прежние вызовы

// ── значения колонки «Написали?» ──
var ST_DONE = 'Да';
var ST_TODO = 'Нет';
var ST_PREMIUM = 'Премиум';             // пишут только Premium
var ST_UNDELIVERABLE = 'Не доставлено'; // личка закрыта, ник исчез
var STATUSES = [ST_DONE, ST_TODO, ST_PREMIUM, ST_UNDELIVERABLE];

// ── значения колонки «Присутствие» (пусто = ещё не трогали) ──
var PR_NO_ANSWER = 'нет ответа';
var PR_AGREED = 'согласен';
var PR_REGISTERED = 'зарегистрирован';
var PR_REFUSED = 'отказ';
var PRESENCES = [PR_NO_ANSWER, PR_AGREED, PR_REGISTERED, PR_REFUSED];

// Какому статусу какая вкладка. Пусто и «нет ответа» — обе в «Новые»:
// «не ответил» это тот же новый, до которого просто не дошли руки.
var TAB_BY_PRESENCE = {};
TAB_BY_PRESENCE[''] = TAB_NEW;
TAB_BY_PRESENCE[PR_NO_ANSWER] = TAB_NEW;
TAB_BY_PRESENCE[PR_AGREED] = TAB_AGREED;
TAB_BY_PRESENCE[PR_REFUSED] = TAB_REFUSED;
TAB_BY_PRESENCE[PR_REGISTERED] = TAB_REGISTERED;

// Вкладки воронки — по ним строки ездят. Порядок = порядок в таблице.
var FUNNEL_TABS = [TAB_NEW, TAB_AGREED, TAB_REFUSED, TAB_REGISTERED];
// Вкладки, где строка живёт всегда (переезд их не касается).
var FIXED_TABS = [TAB_NONICK, AGENCY_TAB];
// Все вкладки с объявлениями (порядок важен: так они создаются в таблице).
var DATA_TABS = FUNNEL_TABS.concat(FIXED_TABS);

var REALTY_SLUG = 'realty'; // категория недвижимости (см. categories.py)

// ── значения колонки «На сайте» ──
// Пусто = ещё не пробовали выложить. Если пусто, НО есть примечание к ячейке —
// попытка была и не удалась, повторно её не берём (см. большой комментарий выше).
var SITE_LIVE = 'На сайте';          // одобрено, люди его видят
var SITE_REVIEW = 'Ждёт модератора'; // лежит в очереди на проверку
var SITE_OFF = 'Снято';              // снято или удалено — на сайте его нет
var SITE_VALUES = [SITE_LIVE, SITE_REVIEW, SITE_OFF];
// Старые значения, которые могли остаться в таблице: молча переводим в новые.
var SITE_LEGACY = {
  'Опубликовано': SITE_REVIEW,   // из самых первых версий
  'В каталоге': SITE_LIVE,       // переименовано 01.09.2026
  'Удалено': SITE_OFF,           // слито со «Снято» 01.09.2026
  'Не вышло': '',                // упразднено 01.09.2026 → пустая ячейка
  'Нет на сайте': ''             // самое старое имя колонки
};
// Пометка неудачи по умолчанию, если причину не передали.
var FAIL_NOTE = 'не удалось выложить на сайт';

// ── РЕЕСТР СОГЛАСИЙ (вкладка «Согласия») ──
var CONSENT_HEADER = ['Ник', 'Статус', 'Когда', 'Основание'];
var C_NICK_COL = 1;    // A — ник без @, нижним регистром
var C_STATUS_COL = 2;  // B — согласен / зарегистрирован / отказ
var C_WHEN_COL = 3;    // C — дата события (ГГГГ-ММ-ДД)
var C_REASON_COL = 4;  // D — основание
var CONSENT_STATUSES = [PR_AGREED, PR_REGISTERED, PR_REFUSED];

// Сила статуса: больше — сильнее. Слабый НЕ перезаписывает сильный, чтобы
// сайт своим автоматическим «согласен» не затёр отказ, поставленный руками.
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
      var value = _safePresence(body.value);
      var foundP = _setForNick(tabs, body.author, PRESENCE_COL, value);
      var movedP = _resort(tabs);
      return _json({ ok: true, found: foundP, moved: movedP });
    }

    if (action === 'consent') {
      var out = _setConsent(tabs, body.nick || body.author,
                            body.status || body.value, body.reason);
      out.moved = _resort(tabs);
      return _json(out);
    }

    // Ночная сверка пишет пачкой: поштучный обход 500 строк не укладывается
    // в лимит времени Apps Script.
    if (action === 'sitebulk') {
      return _json(_setSiteBulk(tabs, body.rows));
    }

    if (action === 'consentbulk') {
      var list = body.rows || [];
      var changed = 0;
      for (var ci = 0; ci < list.length; ci++) {
        var it = list[ci] || {};
        var r = _setConsent(tabs, it.nick, it.status, it.reason || '');
        if (r.ok && !r.kept) changed++;
      }
      // Переезд делаем ОДИН раз в конце: полный проход по вкладкам на каждую
      // строку пакета не уложился бы в лимит времени Apps Script.
      var movedB = _resort(tabs);
      return _json({ ok: true, changed: changed, moved: movedB });
    }

    if (action === 'nosite' || action === 'site') {
      var foundN = _setSite(tabs, body.link, body.value, body.note);
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

  // Ночная сверка: что мы уже разместили (нужны ссылки) и кто вообще есть в
  // таблице (нужны ники). Оба списка отдаём целиком — их тысячи, не миллионы.
  if (action === 'placed') {
    if (params.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    return _json({ ok: true, rows: _readPlaced(_ensureTabs()) });
  }

  if (action === 'nicks') {
    if (params.token !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }
    return _json({ ok: true, nicks: _readNicks(_ensureTabs()) });
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
 * Размещённые объявления — для ночной сверки с сайтом: строки, у которых
 * колонка «На сайте» заполнена. Их состояние ещё может измениться (снятое
 * модератор может вернуть), поэтому переспрашиваем у сайта все три состояния.
 * Пустые ячейки не берём: за ними объявления на сайте нет.
 */
function _readPlaced(tabs) {
  var out = [];
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var vals = sh.getRange(2, 1, last - 1, HEADER.length).getValues();
    for (var i = 0; i < vals.length; i++) {
      var site = String(vals[i][SITE_COL - 1] || '').trim();
      if (!site) continue;
      var link = String(vals[i][LINK_COL - 1] || '').trim();
      if (!link) continue;
      out.push({ link: link, site: site });
    }
  }
  return out;
}

/** Все ники из всех вкладок с объявлениями, без повторов. */
function _readNicks(tabs) {
  var seen = {};
  var out = [];
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var vals = sh.getRange(2, NICK_COL, last - 1, 1).getValues();
    for (var i = 0; i < vals.length; i++) {
      var nick = _normNick(vals[i][0]);
      if (!nick || seen[nick]) continue;
      seen[nick] = true;
      out.push(nick);
    }
  }
  return out;
}

/**
 * Пакетная запись колонки «На сайте»: {link: {value, note}}. Читаем каждый лист
 * один раз, меняем в памяти и пишем одним setValues — так 500 строк
 * обновляются за секунды, а не за минуты.
 */
function _setSiteBulk(tabs, rowsIn) {
  var wanted = {};
  var list = rowsIn || [];
  for (var i = 0; i < list.length; i++) {
    var it = list[i] || {};
    var key = _normLink(it.link);
    if (!key) continue;
    wanted[key] = _siteCell(it.value, it.note);
  }

  var updated = 0;
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var n = last - 1;
    var links = sh.getRange(2, LINK_COL, n, 1).getValues();
    var rng = sh.getRange(2, SITE_COL, n, 1);
    var cur = rng.getValues();
    var notes = rng.getNotes();
    var changed = false;
    for (var r = 0; r < n; r++) {
      var k = _normLink(links[r][0]);
      if (!k || !wanted.hasOwnProperty(k)) continue;
      var want = wanted[k];
      if (String(cur[r][0]).trim() === want.value &&
          String(notes[r][0] || '') === want.note) continue;
      cur[r][0] = want.value;
      notes[r][0] = want.note;
      changed = true;
      updated++;
    }
    if (changed) { rng.setValues(cur); rng.setNotes(notes); }
  }
  return { ok: true, updated: updated };
}

/** Запись «На сайте» одной строке по ссылке (значение + примечание-причина). */
function _setSite(tabs, link, value, note) {
  var target = _normLink(link);
  if (!target) return 0;
  var want = _siteCell(value, note);
  var touched = 0;
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var n = last - 1;
    var links = sh.getRange(2, LINK_COL, n, 1).getValues();
    var rng = sh.getRange(2, SITE_COL, n, 1);
    var cur = rng.getValues();
    var notes = rng.getNotes();
    var changed = false;
    for (var i = 0; i < n; i++) {
      if (_normLink(links[i][0]) !== target) continue;
      if (String(cur[i][0]) === want.value &&
          String(notes[i][0] || '') === want.note) continue;
      cur[i][0] = want.value;
      notes[i][0] = want.note;
      changed = true;
      touched++;
    }
    if (changed) { rng.setValues(cur); rng.setNotes(notes); }
  }
  return touched;
}

/**
 * Что положить в ячейку «На сайте» и в её примечание.
 * Пустое значение + причина = неудача: поле остаётся пустым, причина живёт в
 * примечании и не даёт очереди взять строку снова.
 */
function _siteCell(value, note) {
  var v = _safeSite(value);
  var n = String(note == null ? '' : note).trim();
  if (!v) return { value: '', note: n };
  return { value: v, note: '' }; // получилось — старую причину убираем
}

/**
 * Очередь авто-подготовки: объявления продавцов, давших согласие, которые мы
 * ещё не пробовали выложить на сайт.
 *
 * Условия строки: есть ник, «Присутствие» = «согласен», «На сайте» пусто И БЕЗ
 * ПРИМЕЧАНИЯ (примечание = прошлая попытка провалилась, второй раз не берём).
 * Сортировка — от свежих к старым. `days` > 0 отсекает посты старше N дней.
 */
function _readTodo(tabs, limit, days) {
  var out = [];
  var minTime = 0;
  if (days > 0) minTime = new Date().getTime() - days * 24 * 60 * 60 * 1000;

  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var vals = sh.getRange(2, 1, last - 1, HEADER.length).getValues();
    var notes = sh.getRange(2, SITE_COL, last - 1, 1).getNotes();
    for (var i = 0; i < vals.length; i++) {
      var row = vals[i];
      var nick = _normNick(row[NICK_COL - 1]);
      if (!nick) continue;
      if (_safePresence(row[PRESENCE_COL - 1]) !== PR_AGREED) continue;
      if (String(row[SITE_COL - 1] || '').trim() !== '') continue;
      if (String(notes[i][0] || '').trim() !== '') continue; // была неудача
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

// ───────────── РУЧНАЯ ПРАВКА «ПРИСУТСТВИЯ» (простой триггер) ─────────────
/**
 * Савелий поменял «Присутствие» или «Написали?» в одной строке — значение
 * разъезжается по ВСЕМ строкам этого ника, а строки переезжают на вкладку,
 * которая соответствует новому статусу.
 *
 * Зачем. Строка = объявление, поэтому у активного продавца их десятки. Оба
 * статуса — про ЧЕЛОВЕКА, а не про отдельное объявление: написали ему один раз,
 * согласие он даёт один раз.
 *
 * РУЧНАЯ ПРАВКА СИЛЬНЕЕ ВСЕГО: она перебивает реестр даже «вниз» — можно снять
 * «отказ» или вернуть «согласен». Автоматика сильный статус слабым не понижает,
 * это правило только для человека. Очистили ячейку — очищается у всего ника,
 * запись из реестра удаляется, строки уезжают в «Новые».
 *
 * Это ПРОСТОЙ триггер: работает сразу после сохранения кода, новая версия
 * развёртывания для него не нужна (она нужна только веб-приложению `/exec`).
 * На правки, сделанные скриптом, он не реагирует — размножение не зацикливается.
 */
function onEdit(e) {
  try {
    if (!e || !e.range) return;
    var sh = e.range.getSheet();
    var name = sh.getName();
    if (DATA_TABS.indexOf(name) === -1) return;

    // Правка может быть и диапазоном (вставили сразу в несколько ячеек).
    var c1 = e.range.getColumn();
    var c2 = e.range.getLastColumn();
    var touchedPresence = c1 <= PRESENCE_COL && PRESENCE_COL <= c2;
    var touchedWritten = c1 <= WRITTEN_COL && WRITTEN_COL <= c2;
    if (!touchedPresence && !touchedWritten) return;

    var first = Math.max(2, e.range.getRow());
    var last = e.range.getLastRow();
    if (last < first) return;

    var tabs = _tabsLight();
    if (!tabs) return;
    var seen = {};
    var needResort = false;
    for (var r = first; r <= last; r++) {
      var nick = _normNick(sh.getRange(r, NICK_COL).getValue());
      if (!nick || seen[nick]) continue;
      seen[nick] = true;

      if (touchedPresence) {
        var raw = String(sh.getRange(r, PRESENCE_COL).getValue() || '').trim();
        var value = _safePresence(raw);
        // Опечатку не разносим — пусть висит в одной ячейке и бросается в глаза.
        if (raw === '' || value) {
          _setForNick(tabs, nick, PRESENCE_COL, value);
          _forceConsent(tabs, nick, value);
          needResort = true;
        }
      }

      if (touchedWritten) {
        // «Написали?» — тоже про человека. Реестр согласий эта колонка не
        // трогает, и на вкладку строки не влияет.
        var rawW = String(sh.getRange(r, WRITTEN_COL).getValue() || '').trim();
        if (rawW === '' || STATUSES.indexOf(rawW) !== -1) {
          _setForNick(tabs, nick, WRITTEN_COL, rawW);
        }
      }
    }
    // Переезд — один раз в конце, даже если правили десять строк сразу.
    if (needResort) _resort(tabs);
  } catch (err) {
    // Триггер не должен мешать человеку работать с таблицей: молчим.
  }
}

/** Вкладки без создания и переоформления — для триггера, который должен быть быстрым. */
function _tabsLight() {
  var ss = SpreadsheetApp.getActive();
  var all = [];
  var byName = {};
  for (var i = 0; i < DATA_TABS.length; i++) {
    var sh = ss.getSheetByName(DATA_TABS[i]);
    if (!sh) continue;
    all.push(sh);
    byName[DATA_TABS[i]] = sh;
  }
  if (!all.length) return null;
  return { all: all, byName: byName, consent: ss.getSheetByName(CONSENT_TAB) };
}

/**
 * Записать статус в реестр СИЛОЙ, не глядя на «силу» прежнего: так работает
 * только ручная правка. Пустое значение = удалить человека из реестра.
 *
 * «Нет ответа» — про рассылку, а не про согласие, поэтому реестр от него не
 * меняется: человек, который однажды согласился, согласившимся и остаётся.
 */
function _forceConsent(tabs, nick, status) {
  var sh = tabs.consent;
  if (!sh) return;
  if (status && CONSENT_STATUSES.indexOf(status) === -1) return;

  var map = _readConsents(sh);
  var cur = map[nick];

  if (!status) {
    if (cur) sh.deleteRow(cur.row);
    return;
  }
  var row = [status, _today(), 'правка руками в таблице'];
  if (cur) sh.getRange(cur.row, C_STATUS_COL, 1, 3).setValues([row]);
  else sh.appendRow([nick].concat(row));
}

// ─────────────────────────── ВКЛАДКИ ───────────────────────────
/** Все вкладки с объявлениями + реестр. Создаёт недостающие при первом
 *  обращении (шапка, выпадашки, подсветка). */
function _ensureTabs() {
  var all = [];
  var byName = {};
  for (var i = 0; i < DATA_TABS.length; i++) {
    var sh = _ensureSheet(DATA_TABS[i], i);
    all.push(sh);
    byName[DATA_TABS[i]] = sh;
  }
  return { all: all, byName: byName, consent: _ensureConsentSheet() };
}

/** Вкладка «Согласия» — реестр. Создаётся при первом обращении: шапка,
 *  выпадающий список статусов, подсветка и мягкая защита листа. */
function _ensureConsentSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(CONSENT_TAB);
  if (!sh) {
    sh = ss.insertSheet(CONSENT_TAB, DATA_TABS.length);
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
 *  Реестр — единственный источник правды о согласии. */
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

/** Лист должен вмещать все наши колонки. */
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
    // Переименования колонки «На сайте» из прошлых редакций.
    else if (i === SITE_COL - 1 && was === 'Нет на сайте') {
      cur[i] = HEADER[i]; changed = true;
    }
  }
  if (changed) {
    sh.getRange(1, 1, 1, HEADER.length).setValues([cur]);
    sh.setFrozenRows(1);
  }
}

/** Выпадашки: «Написали?», «Присутствие», «На сайте». */
function _ensureValidation(sh) {
  var maxRows = sh.getMaxRows();
  if (maxRows < 2) return;
  var n = maxRows - 1;
  sh.getRange(2, WRITTEN_COL, n, 1).setDataValidation(_listRule(STATUSES, false));
  // «Присутствие» и «На сайте» — allowInvalid=true: пустая ячейка это
  // нормальное состояние, ругаться на неё не нужно.
  sh.getRange(2, PRESENCE_COL, n, 1).setDataValidation(_listRule(PRESENCES, true));
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
 */
function _ensureColorRules(sh) {
  var rows = Math.max(1, sh.getMaxRows() - 1);
  var presenceRng = sh.getRange(2, PRESENCE_COL, rows, 1);
  var siteRng = sh.getRange(2, SITE_COL, rows, 1);
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

  // «На сайте»: зелёное — живёт в каталоге, синее — ждёт человека,
  // жёлтое — снято. Пустая ячейка не красится вовсе.
  var sitePairs = [
    [SITE_LIVE, PR_GREEN], [SITE_REVIEW, PR_BLUE], [SITE_OFF, PR_YELLOW],
  ];
  for (var k = 0; k < sitePairs.length; k++) {
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$I2="' + sitePairs[k][0] + '"')
      .setBackground(sitePairs[k][1])
      .setRanges([siteRng])
      .build());
  }

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

/** Значение колонки «На сайте»: одно из трёх состояний или пусто.
 *  Старые названия переводим молча, всё незнакомое считаем пустым. */
function _safeSite(v) {
  var s = String(v == null ? '' : v).trim();
  if (s === '') return '';
  if (SITE_VALUES.indexOf(s) !== -1) return s;
  if (SITE_LEGACY.hasOwnProperty(s)) return SITE_LEGACY[s];
  return '';
}

function _safeSeller(v) {
  var s = String(v == null ? '' : v).trim().toLowerCase();
  return (s === 'бизнес' || s === 'частник') ? s : '';
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
 * строках этого ника. Слабый статус не перезаписывает сильный:
 * «отказ» > «зарегистрирован» > «согласен».
 * Переезд строк по вкладкам делает вызывающий (_resort) — чтобы в пакете
 * пройтись по вкладкам один раз, а не на каждую строку.
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

/**
 * На какую вкладку кладём НОВОЕ объявление.
 * Порядок проверок важен: сперва агентства недвижимости (у них свой боковой
 * список), потом «без ника» (писать некому), и только потом воронка по статусу.
 */
function _pickTab(row, presence) {
  var slug = String(row.category_slug || '').trim().toLowerCase();
  if (slug === REALTY_SLUG && _safeSeller(row.seller_type) === 'бизнес') {
    return AGENCY_TAB;
  }
  if (!_normNick(row.author)) return TAB_NONICK;
  return _tabForPresence(presence);
}

function _tabForPresence(presence) {
  var p = _safePresence(presence);
  return TAB_BY_PRESENCE.hasOwnProperty(p) ? TAB_BY_PRESENCE[p] : TAB_NEW;
}

/**
 * Дописывает объявления. Дубль = ТА ЖЕ ССЫЛКА (уже в таблице или в этой же
 * пачке). Объявления без ника записываем на свою вкладку — это рыночные данные.
 * Новая строка наследует «Написали?» и «Присутствие» своего ника и сразу
 * ложится на правильную вкладку. Возвращает число добавленных строк.
 */
function _appendDedup(tabs, rows) {
  var links = {};
  var byNick = {};
  for (var t = 0; t < tabs.all.length; t++) _scan(tabs.all[t], links, byNick);
  // Реестр согласий важнее соседних строк: если человек уже согласился или
  // отказался, его новое объявление сразу получает правильный статус.
  var consents = _readConsents(tabs.consent);

  var buckets = {};
  for (var b = 0; b < DATA_TABS.length; b++) buckets[DATA_TABS[b]] = [];
  var total = 0;

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var link = _normLink(r.link);
    if (!link || links[link]) continue; // без ссылки или дубль — пропускаем
    links[link] = true;

    var nick = _normNick(r.author);
    var st = (nick && byNick[nick]) ? byNick[nick] : { written: ST_TODO, presence: '' };
    var presence = (nick && consents[nick]) ? consents[nick].status : st.presence;

    buckets[_pickTab(r, presence)].push([
      r.author || '', r.link || '', r.channel || '', r.category || '',
      r.date || '', r.snippet || '', st.written, presence, '',
    ]);
    total++;
  }

  for (var k = 0; k < DATA_TABS.length; k++) {
    _writeBucket(tabs.byName[DATA_TABS[k]], buckets[DATA_TABS[k]]);
  }
  return total;
}

function _writeBucket(sh, values) {
  if (!sh || !values || values.length === 0) return;
  var startRow = sh.getLastRow() + 1;
  sh.getRange(startRow, 1, values.length, HEADER.length).setValues(values);
  _ensureValidation(sh);
  _ensureColorRules(sh);
}

// ─────────── ПЕРЕЕЗД СТРОК ПО ВКЛАДКАМ ───────────
/**
 * Раскладывает строки воронки по вкладкам согласно колонке «Присутствие».
 *
 * Как работает: читает ВСЕ строки вкладок воронки разом (вместе с примечаниями
 * к «На сайте»), считает каждой правильный дом и, если хоть одна строка
 * переезжает, переписывает вкладки целиком одним setValues на лист. Поштучное
 * «вставить строку — удалить строку» на сотнях строк не укладывается в лимит
 * времени Apps Script, поэтому именно так.
 *
 * Вкладки «Без ника» и «Недвижимость — агентства» не трогаются вовсе: это
 * боковые списки, их строки никуда не ездят.
 *
 * Возвращает число переехавших строк. Безопасен: запускать можно сколько угодно.
 */
function _resort(tabs) {
  var items = [];   // {vals: [...], note: '', from: 'Новые'}
  for (var i = 0; i < FUNNEL_TABS.length; i++) {
    var name = FUNNEL_TABS[i];
    var sh = tabs.byName[name];
    if (!sh) continue;
    var last = sh.getLastRow();
    if (last < 2) continue;
    var n = last - 1;
    var vals = sh.getRange(2, 1, n, HEADER.length).getValues();
    var notes = sh.getRange(2, SITE_COL, n, 1).getNotes();
    for (var r = 0; r < n; r++) {
      // Пустые строки (например, после ручного удаления) не тащим.
      if (!String(vals[r][LINK_COL - 1] || '').trim() &&
          !String(vals[r][NICK_COL - 1] || '').trim()) continue;
      items.push({ vals: vals[r], note: String(notes[r][0] || ''), from: name });
    }
  }

  var groups = {};
  for (var g = 0; g < FUNNEL_TABS.length; g++) groups[FUNNEL_TABS[g]] = [];
  var moved = 0;
  for (var k = 0; k < items.length; k++) {
    var it = items[k];
    var home = _tabForPresence(it.vals[PRESENCE_COL - 1]);
    if (home !== it.from) moved++;
    groups[home].push(it);
  }

  if (moved === 0) return 0;
  for (var t = 0; t < FUNNEL_TABS.length; t++) {
    _rewriteTab(tabs.byName[FUNNEL_TABS[t]], groups[FUNNEL_TABS[t]]);
  }
  return moved;
}

/** Переписывает вкладку целиком: шапка остаётся, строки — новые. */
function _rewriteTab(sh, items) {
  if (!sh) return;
  var last = sh.getLastRow();
  if (last > 1) {
    var old = sh.getRange(2, 1, last - 1, HEADER.length);
    old.clearContent();
    old.clearNote();
  }
  if (!items.length) return;
  var vals = [];
  var notes = [];
  for (var i = 0; i < items.length; i++) {
    vals.push(items[i].vals);
    notes.push([items[i].note]);
  }
  sh.getRange(2, 1, vals.length, HEADER.length).setValues(vals);
  sh.getRange(2, SITE_COL, notes.length, 1).setNotes(notes);
  _ensureValidation(sh);
  _ensureColorRules(sh);
}

/** Ставит значение в колонку ВСЕМ строкам одного ника (все вкладки).
 *  Возвращает, сколько строк поправили. */
function _setForNick(tabs, author, col, value) {
  var target = _normNick(author);
  if (!target) return 0;
  return _setWhere(tabs, NICK_COL, _normNick, target, col, value);
}

/** Ставит значение в колонку строке с конкретной ссылкой (все вкладки). */
function _setForLink(tabs, link, col, value) {
  var target = _normLink(link);
  if (!target) return 0;
  return _setWhere(tabs, LINK_COL, _normLink, target, col, value);
}

function _setWhere(tabs, keyCol, normFn, target, col, value) {
  var touched = 0;
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var keys = sh.getRange(2, keyCol, last - 1, 1).getValues();
    var rng = sh.getRange(2, col, last - 1, 1);
    var cur = rng.getValues();
    var changed = false;
    for (var i = 0; i < keys.length; i++) {
      if (normFn(keys[i][0]) === target && String(cur[i][0]) !== String(value)) {
        cur[i][0] = value;
        changed = true;
        touched++;
      }
    }
    if (changed) rng.setValues(cur);
  }
  return touched;
}

/** Карта {ник: статус «Написали?»} по всем вкладкам.
 *  У человека много строк — берём «сильный» статус (любой, кроме «Нет»). */
function _readStatuses(tabs) {
  var links = {};
  var byNick = {};
  for (var t = 0; t < tabs.all.length; t++) _scan(tabs.all[t], links, byNick);
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
 * Меню «Фаранг» при открытии таблицы: всё, что запускается руками, — мышью,
 * без захода в редактор скрипта (там выбрать функцию для ▶ Run бывает неудобно).
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Фаранг')
    .addItem('Пересчитать «Присутствие» по реестру', 'syncConsents')
    .addItem('Разложить строки по вкладкам', 'resortTabs')
    .addSeparator()
    .addItem('Перенести старую вкладку CRM', 'migrateTabs')
    .addItem('Удалить архивные вкладки', 'dropArchiveTabs')
    .addItem('Очистить пометки неудач', 'clearFailNotes')
    .addToUi();
}

/** Пункт меню: разложить строки по вкладкам прямо сейчас. */
function resortTabs() {
  var tabs = _ensureTabs();
  var moved = _resort(tabs);
  SpreadsheetApp.getActive().toast('Переехало строк: ' + moved, 'Вкладки', 10);
  return { moved: moved };
}

// ─────────── ПЕРЕСЧЁТ ПО РЕЕСТРУ (меню «Фаранг») ───────────
/**
 * Проходит по вкладке «Согласия» и проставляет «Присутствие» всем строкам
 * каждого ника, после чего раскладывает строки по вкладкам.
 * Безопасен: запускать можно сколько угодно раз.
 */
function syncConsents() {
  var tabs = _ensureTabs();
  var map = _readConsents(tabs.consent);
  var people = 0;
  for (var nick in map) { if (map.hasOwnProperty(nick)) people++; }

  // Один проход по каждому листу: читаем ники и «Присутствие» разом, считаем
  // новые значения в памяти и пишем одним setValues. Поштучный обход для 200+
  // человек не укладывался в лимит времени Apps Script.
  var touched = 0;
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
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
  var moved = _resort(tabs);
  SpreadsheetApp.getActive().toast(
    'Реестр: людей ' + people + ', поправлено строк: ' + touched +
    ', переехало: ' + moved,
    'Согласия', 10);
  return { people: people, touched: touched, moved: moved };
}

// ─────────── РАЗОВЫЕ ДЕЙСТВИЯ (меню «Фаранг») ───────────
/**
 * Переносит строки из старой единой вкладки «CRM» в новые вкладки-воронку.
 *   - выбрасывает колонку «Тип продавца» (J);
 *   - переводит старые значения «На сайте»: «В каталоге» → «На сайте»,
 *     «Удалено» → «Снято», «Не вышло» → пусто + примечание с прежней пометкой;
 *   - раскладывает строки по вкладкам: без ника → «Без ника», остальные —
 *     по статусу в «Присутствии»;
 *   - старую вкладку переименовывает в «архив_CRM», НЕ удаляя её.
 * Убедился, что всё на месте, — «Удалить архивные вкладки».
 * Запускать можно повторно: перенесённые строки отсекаются по ссылке.
 */
function migrateTabs() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var tabs = _ensureTabs();
  var old = ss.getSheetByName(LEGACY_TAB);
  if (!old) {
    SpreadsheetApp.getActive().toast(
      'Вкладки «' + LEGACY_TAB + '» нет — переносить нечего.', 'Миграция', 10);
    return { moved: 0 };
  }

  var last = old.getLastRow();
  var rows = [];
  if (last >= 2) {
    var width = Math.max(HEADER.length, Math.min(old.getLastColumn(), 10));
    var vals = old.getRange(2, 1, last - 1, width).getValues();
    for (var i = 0; i < vals.length; i++) {
      if (!String(vals[i][LINK_COL - 1] || '').trim()) continue;
      rows.push(vals[i]);
    }
  }

  // Что уже лежит в новых вкладках — чтобы повторный запуск не задваивал.
  var known = {};
  for (var t = 0; t < tabs.all.length; t++) {
    var sh = tabs.all[t];
    var l = sh.getLastRow();
    if (l < 2) continue;
    var links = sh.getRange(2, LINK_COL, l - 1, 1).getValues();
    for (var q = 0; q < links.length; q++) {
      var key = _normLink(links[q][0]);
      if (key) known[key] = true;
    }
  }

  var buckets = {};
  var noteBuckets = {};
  for (var b = 0; b < DATA_TABS.length; b++) {
    buckets[DATA_TABS[b]] = [];
    noteBuckets[DATA_TABS[b]] = [];
  }

  var moved = 0;
  for (var r = 0; r < rows.length; r++) {
    var row = rows[r];
    var link = _normLink(row[LINK_COL - 1]);
    if (!link || known[link]) continue;
    known[link] = true;

    var wasSite = String(row[SITE_COL - 1] || '').trim();
    var site = _safeSite(wasSite);
    // «Не вышло» и прочие неудачи превращаются в пустое поле с примечанием —
    // иначе очередь взяла бы эти посты снова и снова.
    var note = (!site && wasSite) ? ('прежняя пометка: ' + wasSite) : '';

    var nick = _normNick(row[NICK_COL - 1]);
    var presence = _safePresence(row[PRESENCE_COL - 1]);
    var home = nick ? _tabForPresence(presence) : TAB_NONICK;

    buckets[home].push([
      row[0] || '', row[1] || '', row[2] || '', row[3] || '',
      row[4] || '', row[5] || '',
      String(row[WRITTEN_COL - 1] || '') || ST_TODO,
      presence, site,
    ]);
    noteBuckets[home].push([note]);
    moved++;
  }

  for (var k = 0; k < DATA_TABS.length; k++) {
    var name = DATA_TABS[k];
    var target = tabs.byName[name];
    var list = buckets[name];
    if (!list.length) continue;
    var start = target.getLastRow() + 1;
    target.getRange(start, 1, list.length, HEADER.length).setValues(list);
    target.getRange(start, SITE_COL, list.length, 1).setNotes(noteBuckets[name]);
    _ensureValidation(target);
    _ensureColorRules(target);
  }

  try { old.setName('архив_' + LEGACY_TAB); } catch (err) { /* имя занято */ }

  SpreadsheetApp.getActive().toast(
    'Перенесено строк: ' + moved + '. Старая вкладка переименована в ' +
    '«архив_' + LEGACY_TAB + '» — проверьте и удалите её пунктом ' +
    '«Удалить архивные вкладки».',
    'Миграция', 15);
  return { moved: moved };
}

/**
 * Удаляет все вкладки, чьё имя начинается на «архив_» — старые повкладочные
 * архивы по группам и архив старой CRM. Савелий 01.09.2026: они не актуальны.
 * Рабочие вкладки и реестр согласий не трогает никогда.
 */
function dropArchiveTabs() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = ss.getSheets();
  var killed = [];
  for (var i = 0; i < sheets.length; i++) {
    var sh = sheets[i];
    var name = sh.getName();
    if (name.indexOf('архив_') !== 0) continue;
    if (DATA_TABS.indexOf(name) !== -1 || name === CONSENT_TAB) continue;
    ss.deleteSheet(sh);
    killed.push(name);
  }
  SpreadsheetApp.getActive().toast(
    killed.length ? ('Удалено вкладок: ' + killed.length + ' (' + killed.join(', ') + ')')
                  : 'Архивных вкладок не нашлось.',
    'Архивы', 15);
  return { deleted: killed.length, names: killed };
}

/**
 * Снимает примечания-причины в колонке «На сайте» — то есть возвращает
 * неудавшиеся объявления в очередь авто-подготовки. Нужен, когда причина
 * устранена (например, починили разбор услуг) и хочется попробовать заново.
 */
function clearFailNotes() {
  var tabs = _ensureTabs();
  var cleared = 0;
  for (var s = 0; s < tabs.all.length; s++) {
    var sh = tabs.all[s];
    var last = sh.getLastRow();
    if (last < 2) continue;
    var rng = sh.getRange(2, SITE_COL, last - 1, 1);
    var notes = rng.getNotes();
    var changed = false;
    for (var i = 0; i < notes.length; i++) {
      if (String(notes[i][0] || '') === '') continue;
      notes[i][0] = '';
      cleared++;
      changed = true;
    }
    if (changed) rng.setNotes(notes);
  }
  SpreadsheetApp.getActive().toast(
    'Снято пометок: ' + cleared + '. Эти объявления снова встанут в очередь.',
    'Неудачи', 10);
  return { cleared: cleared };
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
