# StarBridge 1.0 — Adaptive Recursive Rare-Interest Relay (A-RIR)

**Версия:** 1.0.0  
**Python:** 3.11+  
**Зависимости:** только стандартная библиотека Python  
**AI / embeddings / keyword dorking:** не используются  
**Хранилище:** SQLite  
**Отчёт:** локальный HTML

---

# 1. Что это

StarBridge 1.0 — локальная детерминированная программа для поиска людей со схожими GitHub-интересами и новых малозаметных репозиториев через публичный граф GitHub.

Она не пытается восстановить закрытый GitHub-список stargazers и не использует `/repos/{owner}/{repo}/stargazers` как источник данных.

Основной путь:

```text
твои starred repositories
        ↓
редкие и характерные seed repositories
        ↓
публичные участники этих repositories
        ↓
их публичные starred repositories
        ↓
редкие пересечения интересов
        ↓
сильные люди
        ↓
их новые/редкие repositories
        ↓
лучшие найденные repositories становятся новыми seeds
        ↓
новые люди
        ↓
новые stars
        ↓
...
```

Это A-RIR — **Adaptive Recursive Rare-Interest Relay**.

---

# 2. Что реализовано из paper

В версии 1.0 реально присутствуют:

- recursive multi-hop expansion;
- automatic seed promotion;
- Seed Portfolio Optimizer;
- public actor sources:
  - owner/maintainer;
  - contributors;
  - fork owners;
  - issue authors;
  - pull-request authors;
  - issue/PR commenters;
  - PR review commenters;
  - commit authors/committers;
  - release authors;
- actor expansion через:
  - starred repositories;
  - public repositories;
  - public recent events;
- repository expansion;
- адаптивная глубина star-листов;
- режимы historical sampling:
  - `recent`;
  - `stratified`;
  - `exhaustive`;
- полный собственный star-profile через `/user/starred` при совпадении токена и `--user`;
- публичный fallback `/users/{username}/starred`;
- REST + GraphQL hybrid transport;
- GraphQL batching первого star-page нескольких пользователей;
- автоматический fallback GraphQL → REST;
- `starred_at` timestamps;
- persistent SQLite graph;
- ETag conditional cache;
- persistent frontier;
- `resume` без начала с нуля;
- adaptive request priority:

```text
ExpectedYield × Novelty × Relevance × Confidence / Cost
```

- EMA yield model;
- global rarity;
- local IDF rarity;
- Similarity 2.0:
  - rare overlap;
  - weighted Jaccard;
  - containment;
  - temporal similarity;
  - seed affinity;
  - structural affinity;
- repository scoring:
  - support strength;
  - supporter diversity;
  - global rarity;
  - local rarity;
  - temporal velocity;
  - activity recency;
  - no-topics signal;
  - discovery-path diversity;
- early-signal detector;
- deterministic diversity pressure;
- deterministic community discovery;
- complete discovery paths;
- positive/negative memory;
- decaying suppression memory;
- pattern suppression по language/topics без AI;
- local feedback 1–5;
- deterministic weight calibration через coordinate search;
- temporal holdout benchmark;
- leakage-safe `--owner-cutoff`;
- Wide / Deep / Adaptive modes;
- локальный HTML с:
  - Early Signals;
  - Recent discoveries;
  - Repositories;
  - People;
  - Communities;
  - Discovery paths;
  - API/transport metrics.

---

# 3. Что StarBridge НЕ делает

Он намеренно не:

- скрапит скрытый stargazers UI;
- обходит authorization;
- восстанавливает закрытый `/stargazers`;
- использует GitHub dorks;
- использует semantic embeddings;
- вызывает LLM/AI API;
- массово угадывает usernames;
- делает write-запросы к GitHub;
- ставит/снимает stars;
- меняет repositories или профиль.

Программа — read-only исследователь публичного графа.

---

# 4. Файлы

```text
StarBridge_1_0/
├── starbridge.py               # вся рабочая программа
├── test_starbridge.py          # offline unit/integration tests
├── README_RU.md                # эта инструкция
├── ARCHITECTURE.md             # архитектура A-RIR
├── IMPLEMENTATION_MATRIX.md    # paper → реализация
├── StarBridge_Future_Improvements_Paper_RU.md
├── Start-StarBridge.ps1        # необязательный PowerShell helper
├── requirements.txt            # внешних зависимостей нет
└── TEST_REPORT.txt             # результат сборочных тестов
```

Во время работы появятся:

```text
starbridge_1_0.db
starbridge_1_0.db-wal
starbridge_1_0.db-shm
starbridge_scan_<ID>.html
```

`*.db` — твоя долговременная карта интересов. Не удаляй её между запусками, если хочешь накопительную память.

---

# 5. Установка Python на Windows

Нужен Python **3.11 или новее**.

После установки открой PowerShell и проверь:

```powershell
py --version
```

или:

```powershell
python --version
```

Ожидается что-то вроде:

```text
Python 3.11.x
Python 3.12.x
Python 3.13.x
```

Если `py` работает — используй команды из этой инструкции как есть.

Если работает только `python`, просто замени в командах:

```text
py
```

на:

```text
python
```

---

# 6. Распаковка

Рекомендуемый путь:

```text
C:\StarBridge_1_0
```

После распаковки:

```powershell
cd C:\StarBridge_1_0
```

Проверь:

```powershell
dir
```

Ты должен увидеть `starbridge.py`.

---

# 7. Сначала запусти OFFLINE selftest

Этот тест не требует GitHub и токена.

```powershell
py .\starbridge.py selftest
```

Ожидаемый результат:

```text
Selftest: PASS
```

Затем полный test suite:

```powershell
py -m unittest -v .\test_starbridge.py
```

Ожидается:

```text
Ran 4 tests ...
OK
```

Если уже здесь ошибка — не начинай большой GitHub scan. Сначала сохрани полный текст ошибки.

---

# 8. GitHub token

Для маленького public scan программа может читать public endpoints без токена, но это сильно ограничивает rate limit.

Для нормального StarBridge 1.0 нужен token.

Рекомендуется **Fine-grained personal access token**.

Путь в GitHub UI:

```text
GitHub
→ Settings
→ Developer settings
→ Personal access tokens
→ Fine-grained tokens
→ Generate new token
```

Минимально важное account permission:

```text
Starring → Read-only
```

Для public repositories fine-grained token всё равно имеет read-only access к public repositories. StarBridge не требует write permissions.

Если ты хочешь, чтобы собственный authenticated star-profile включал доступные токену private repositories в local-only режиме, тогда Repository access токена должен включать эти private repositories. По умолчанию лучше оставить:

```text
--private-policy ignore
```

Никогда не вставляй token в исходный код.

---

# 9. Передача token в PowerShell

В текущем PowerShell окне:

```powershell
$env:GITHUB_TOKEN = "github_pat_ТВОЙ_ТОКЕН"
```

Не отправляй token в чат и не публикуй его.

После закрытия этого PowerShell окна переменная исчезнет.

Проверить только факт наличия, не выводя сам token:

```powershell
if ($env:GITHUB_TOKEN) { "TOKEN OK" } else { "TOKEN MISSING" }
```

---

# 10. LIVE doctor — обязательная первая проверка

Заменить `YOUR_GITHUB_LOGIN` на логин без `@`:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db doctor --user YOUR_GITHUB_LOGIN
```

Doctor проверяет:

1. GitHub `/user` при наличии token;
2. public repository API;
3. первый public star-page пользователя;
4. rate-limit status;
5. GraphQL starredRepositories при наличии token.

Нормальный вывод примерно:

```text
StarBridge 1.0.0 doctor
Database: ...\starbridge_1_0.db
Token: present
Authenticated viewer: @YOUR_GITHUB_LOGIN
Public repository API: OK (...)
Public stars for @YOUR_GITHUB_LOGIN: OK (... items on first page)
REST core: remaining ... / ...
GraphQL starredRepositories: OK (... items)
Doctor result: OK
```

Если GraphQL недоступен, но REST работает, StarBridge всё равно способен работать в REST mode.

---

# 11. Самый маленький реальный тест

Перед massive scan сделай короткий тест с малым бюджетом.

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive `
  --user YOUR_GITHUB_LOGIN `
  --mode wide `
  --budget 150 `
  --auto-seeds 5 `
  --max-depth 1 `
  --source-pages 1 `
  --actor-star-pages 2 `
  --carry-people 0 `
  --repo-promotions-per-actor 1 `
  --transport auto `
  --report .\starbridge_test.html `
  --open
```

Важно: PowerShell backtick `` ` `` должен быть **последним символом строки**. После него не должно быть пробела.

Та же команда одной строкой:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode wide --budget 150 --auto-seeds 5 --max-depth 1 --source-pages 1 --actor-star-pages 2 --carry-people 0 --repo-promotions-per-actor 1 --transport auto --report .\starbridge_test.html --open
```

Что должно произойти:

```text
[1/6] Loading owner star profile ...
[2/6] Selected ... initial seeds ...
[3/6] Adaptive recursive crawl ...
[4/6] Scoring people and repositories ...
[5/6] Building HTML report ...
[6/6] Done ...
```

После этого должен открыться `starbridge_test.html`.

---

# 12. Рекомендуемый полноценный ADAPTIVE запуск

После успешного doctor и маленького теста:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive `
  --user YOUR_GITHUB_LOGIN `
  --mode adaptive `
  --budget 4200 `
  --max-depth 4 `
  --auto-seeds 30 `
  --seed-pool 110 `
  --actor-beam 1100 `
  --repo-beam 5500 `
  --source-pages 2 `
  --actor-star-pages 20 `
  --owner-star-pages 0 `
  --min-overlap 1 `
  --recent-days 365 `
  --history-sampling stratified `
  --transport auto `
  --graphql-batch 8 `
  --repo-promotions-per-actor 5 `
  --event-pages 1 `
  --public-repo-pages 1 `
  --min-page-yield 5 `
  --pause 0.12 `
  --report .\starbridge_1_0.html `
  --top-people 1000 `
  --top-repos 20000 `
  --open
```

Одна строка:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode adaptive --budget 4200 --max-depth 4 --auto-seeds 30 --seed-pool 110 --actor-beam 1100 --repo-beam 5500 --source-pages 2 --actor-star-pages 20 --owner-star-pages 0 --min-overlap 1 --recent-days 365 --history-sampling stratified --transport auto --graphql-batch 8 --repo-promotions-per-actor 5 --event-pages 1 --public-repo-pages 1 --min-page-yield 5 --pause 0.12 --report .\starbridge_1_0.html --top-people 1000 --top-repos 20000 --open
```

`4200` оставляет запас относительно стандартного authenticated REST core limit. StarBridge дополнительно читает rate-limit headers и умеет корректно останавливаться/возобновляться.

---

# 13. Что делает ADAPTIVE crawl

Очередь frontier содержит задачи типа:

```text
repo_source
actor_stars
actor_events
actor_repos
repo_detail
```

Каждой задаче назначается priority:

```text
ExpectedYield
× Novelty
× Relevance
× Confidence
÷ Cost
```

Поэтому программа не просто делает BFS.

Плохие ветви быстро теряют приоритет.

Сильные ветви углубляются.

Новый редкий repository может стать seed и открыть новую область графа.

---

# 14. Wide / Deep / Adaptive

## Wide

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode wide --budget 4200 --report .\wide.html --open
```

Для:

- большего количества людей;
- большого количества независимых микросообществ;
- меньшей глубины каждого профиля.

## Deep

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode deep --budget 4200 --report .\deep.html --open
```

Для:

- меньшего числа кандидатов;
- более глубоких star profiles;
- recursive depth до 5;
- большего числа страниц источников.

## Adaptive

Рекомендуемый общий режим.

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode adaptive --budget 4200 --report .\adaptive.html --open
```

---

# 15. REST / GraphQL

## auto — рекомендовано

```text
--transport auto
```

StarBridge использует GraphQL для batching первых star-pages нескольких пользователей, а затем при необходимости продолжает REST pagination.

Если GraphQL query для текущего аккаунта/схемы не проходит, `auto` отключает GraphQL на остаток scan и продолжает REST.

## только REST

```text
--transport rest
```

Самый консервативный режим.

## GraphQL обязателен

```text
--transport graphql
```

Если GraphQL падает, scan выдаёт ошибку вместо fallback.

Для обычной работы используй `auto`.

---

# 16. Historical sampling

## recent

```text
--history-sampling recent
```

Упор на последние страницы stars.

## stratified — рекомендуется

```text
--history-sampling stratified
```

Кроме свежего участка, для перспективных профилей выбираются дополнительные средние/старые страницы, чтобы получить long-term interest signal без полного чтения тысяч stars каждого человека.

## exhaustive

```text
--history-sampling exhaustive
```

Продолжает глубже независимо от падения yield, пока не достигнут `--actor-star-pages` или конец pagination.

Используй только если хочешь более дорогой deep scan.

---

# 17. Полный собственный star profile

```text
--owner-star-pages 0
```

означает:

> читать страницы собственного star list до конца pagination.

Если хочешь вручную ограничить, например 30 страниц = максимум 3000 entries:

```text
--owner-star-pages 30
```

Для нормальной версии рекомендуется `0`, если профиль не аномально огромный.

---

# 18. Explicit seeds

Можно вручную указать особенно характерные repositories:

```powershell
--seed owner/repo
```

Несколько:

```powershell
--seed owner1/repo1 `
--seed owner2/repo2 `
--seed owner3/repo3
```

Они добавляются к автоматически выбранному seed portfolio.

---

# 19. Sources

По умолчанию:

```text
owner,contributors,forks,issues,pulls,comments,reviews,commits,releases
```

Можно сократить:

```powershell
--sources owner,contributors,forks,reviews
```

Для максимально широкого scan оставь default.

Public events и public repos сильных кандидатов запускаются как отдельный actor expansion layer.

---

# 20. Если scan остановился по budget/rate-limit

StarBridge не выбрасывает frontier.

Он сохраняет всё в SQLite.

Посмотри ID scan в консоли. Например:

```text
scan=3
```

Продолжить:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db resume `
  --scan-id 3 `
  --add-budget 3000 `
  --report .\starbridge_1_0_resume.html `
  --open
```

Одна строка:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db resume --scan-id 3 --add-budget 3000 --report .\starbridge_1_0_resume.html --open
```

Если причина — настоящий GitHub hourly rate-limit, дождись reset time, затем делай `resume`.

---

# 21. Ctrl+C

Если нужно остановить программу вручную:

```text
Ctrl+C
```

StarBridge сохраняет уже завершённые операции, оставляет frontier и переводит незавершённое исследование в resumable state.

После этого:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db resume --scan-id SCAN_ID --add-budget 1000 --open
```

---

# 22. Пересоздать HTML без GitHub API

Если scan уже есть, но хочешь больше строк в отчёте:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db report `
  --scan-id 3 `
  --top-people 2000 `
  --top-repos 50000 `
  --report .\starbridge_big_report.html `
  --open
```

Это не делает новых GitHub requests.

---

# 23. Как читать HTML

## Early Signals

Низкая/умеренная глобальная популярность + несколько независимых сильных supporters + свежий сигнал.

## Recent discoveries

Результаты с сильным temporal signal.

## Repositories

Главный ranking.

У каждого:

- score;
- stars;
- language;
- topics/no-topics;
- supporters;
- feature breakdown;
- discovery paths.

## People

Показывает:

- similarity score;
- сколько star entries уже известно локально;
- редкие overlap repositories;
- через какие public sources человек найден.

## Communities

Детерминированные группы людей, соединённых редкими общими starred repositories.

## Discovery paths

Например:

```text
YOU
→ seed/A
→ userX
→ rare/B
→ userY
→ new/C
```

---

# 24. Feedback

После просмотра результата можно сохранить оценку.

## Отлично

```powershell
py .\starbridge.py --db .\starbridge_1_0.db feedback --user YOUR_GITHUB_LOGIN --repo owner/repo --rating 5 --action saved
```

## Интересно

```powershell
py .\starbridge.py --db .\starbridge_1_0.db feedback --user YOUR_GITHUB_LOGIN --repo owner/repo --rating 4 --action interesting
```

## Мусор

```powershell
py .\starbridge.py --db .\starbridge_1_0.db feedback --user YOUR_GITHUB_LOGIN --repo owner/repo --rating 1 --action hide
```

## Просто игнор

```powershell
py .\starbridge.py --db .\starbridge_1_0.db feedback --user YOUR_GITHUB_LOGIN --repo owner/repo --action ignored
```

Negative memory постепенно decay-ится, поэтому старое отрицательное мнение не блокирует категорию навсегда.

---

# 25. Calibration без AI

После хотя бы 5 оценённых repositories:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db calibrate --user YOUR_GITHUB_LOGIN --min-feedback 5
```

StarBridge детерминированно изменит веса repository ranking и сохранит их в SQLite settings.

Чем больше feedback, тем полезнее персональная калибровка.

---

# 26. Leakage-safe benchmark

Чтобы объективно проверить способность находить будущие stars, нужен scan, который НЕ видел stars после cutoff.

Например cutoff:

```text
2026-06-01
```

Создай специальный scan:

```powershell
py .\starbridge.py --db .\benchmark.db massive `
  --user YOUR_GITHUB_LOGIN `
  --mode adaptive `
  --budget 4200 `
  --owner-cutoff 2026-06-01 `
  --report .\benchmark_scan.html
```

Затем, если локальная база содержит реальные поздние stars пользователя:

```powershell
py .\starbridge.py --db .\benchmark.db benchmark --scan-id SCAN_ID --cutoff 2026-06-01
```

Метрики:

```text
hits@100
recall@100
precision@100
hits@500
recall@500
precision@500
hits@1000
recall@1000
precision@1000
```

Без matching `--owner-cutoff` программа откажется выдавать benchmark как leakage-safe.

---

# 27. Что означает request budget

`--budget` — внутренний лимит сетевых обращений StarBridge для одного scan.

Это НЕ изменение GitHub rate-limit.

Пример:

```text
--budget 4200
```

означает: StarBridge остановит новый HTTP crawl около этого числа своих запросов и сохранит frontier.

GitHub rate limit может остановить scan раньше.

---

# 28. Что означают основные параметры

| Параметр | Смысл |
|---|---|
| `--budget` | максимальный сетевой budget текущего scan |
| `--max-depth` | глубина recursive seed expansion |
| `--auto-seeds` | число initial automatic seeds |
| `--seed-pool` | размер пула перед portfolio optimization |
| `--actor-beam` | сколько actor branches сохранять |
| `--repo-beam` | сколько repository branches сохранять |
| `--source-pages` | максимум страниц каждого repo actor-source |
| `--actor-star-pages` | максимум страниц stars одного actor |
| `--owner-star-pages` | 0 = owner profile до конца |
| `--min-overlap` | минимум общих stars для финального PersonScore |
| `--recent-days` | окно recent signal |
| `--history-sampling` | recent/stratified/exhaustive |
| `--transport` | REST/GraphQL стратегия |
| `--graphql-batch` | users на GraphQL batch первого star-page |
| `--repo-promotions-per-actor` | сколько repo человека могут стать next-hop seeds |
| `--event-pages` | public events pages сильного actor |
| `--public-repo-pages` | owned public repos pages сильного actor |
| `--min-page-yield` | когда ветвь star/source pagination считается иссякающей |
| `--max-repo-stars` | 0 = не фильтровать по популярности |
| `--include-forks` | разрешить forks в recommendations/seeds |
| `--include-archived` | разрешить archived repos |

---

# 29. Режим «максимум результатов»

После первого нормального adaptive scan можно расширить:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db massive `
  --user YOUR_GITHUB_LOGIN `
  --mode adaptive `
  --budget 4500 `
  --max-depth 5 `
  --auto-seeds 50 `
  --seed-pool 180 `
  --actor-beam 1800 `
  --repo-beam 10000 `
  --source-pages 3 `
  --actor-star-pages 30 `
  --history-sampling stratified `
  --repo-promotions-per-actor 7 `
  --event-pages 2 `
  --public-repo-pages 2 `
  --top-people 3000 `
  --top-repos 50000 `
  --report .\starbridge_massive.html `
  --open
```

Но сначала проверь стандартный adaptive preset. Больше запросов не всегда означает пропорционально больше полезных результатов — именно поэтому A-RIR измеряет yield и управляет frontier.

---

# 30. Если результатов мало

Проверять по порядку:

1. `doctor` успешен?
2. В owner profile вообще много stars?
3. `--min-overlap` не стоит 2–3 слишком рано?
4. `--budget` достаточен?
5. `--auto-seeds` достаточен?
6. `--max-depth` > 1?
7. Не слишком ли маленький `actor-beam`?
8. Не слишком ли маленький `repo-beam`?
9. Не отбрасываешь ли forks/archived, которые тебе нужны?
10. Сколько `pending` осталось в HTML?

Если `pending > 0` — нужен `resume`, а не новый scan.

---

# 31. Если слишком много мусора

Сначала НЕ уменьшай весь crawl.

Попробуй:

```text
--min-overlap 2
```

и добавляй feedback + calibration.

Также можно ограничить:

```text
--max-repo-stars 50000
```

или даже:

```text
--max-repo-stars 10000
```

если нужны именно obscure projects.

---

# 32. Ошибка 401

Причина обычно token.

Повторно:

```powershell
$env:GITHUB_TOKEN = "github_pat_..."
```

Затем:

```powershell
py .\starbridge.py --db .\starbridge_1_0.db doctor --user YOUR_GITHUB_LOGIN
```

---

# 33. Ошибка 403 / 429

Если это rate-limit, StarBridge сохраняет frontier.

Не запускай scan заново.

Дождись reset и используй `resume`.

---

# 34. GraphQL ошибка

В `--transport auto` программа сама отключит GraphQL для текущего scan и продолжит REST.

Если хочешь сразу убрать GraphQL:

```text
--transport rest
```

---

# 35. Network error / DNS

Проверь:

```powershell
Test-NetConnection api.github.com -Port 443
```

И:

```powershell
Invoke-WebRequest https://api.github.com/rate_limit
```

Если Windows/Firewall/VPN не может открыть `api.github.com`, StarBridge тоже не сможет.

---

# 36. База SQLite

Вся долговременная память находится в:

```text
starbridge_1_0.db
```

Она хранит:

- repositories;
- users;
- stars;
- scan snapshots;
- candidates;
- graph edges;
- frontier tasks;
- source yield;
- scoring;
- discovery paths;
- communities;
- feedback;
- personalized weights;
- request/API metrics.

Рекомендуется регулярно копировать `.db` как backup.

---

# 37. Повторные запуски становятся полезнее

StarBridge сохраняет ранее изученные user stars и результаты.

Следующий scan:

- использует накопленный corpus для local IDF;
- может carry forward лучших people прошлого scan;
- сравнивает new repositories с предыдущим finished scan;
- использует feedback memory;
- использует откалиброванные weights.

То есть `.db` — не cache-файл, а локальная исследовательская память.

---

# 38. Рекомендуемый рабочий цикл

```text
1. doctor
2. small test
3. adaptive 4200
4. открыть HTML
5. оценить 20–50 результатов
6. calibrate
7. через несколько дней новый adaptive scan
8. при необходимости deep/wide
9. не удалять SQLite
```

---

# 39. Быстрая команда после первой настройки

Когда всё проверено, ежедневная/периодическая команда может быть просто:

```powershell
$env:GITHUB_TOKEN = "github_pat_..."
cd C:\StarBridge_1_0
py .\starbridge.py --db .\starbridge_1_0.db massive --user YOUR_GITHUB_LOGIN --mode adaptive --budget 4200 --report .\starbridge_latest.html --open
```

---

# 40. Важное о тестировании этой сборки

Сборка проходит:

```text
python -m py_compile starbridge.py
python starbridge.py selftest
python -m unittest -v test_starbridge.py
```

Также есть полностью synthetic end-to-end integration test, который проходит путь:

```text
owner stars
→ seed portfolio
→ contributors
→ candidate stars
→ similarity
→ repository support
→ automatic seed promotion
→ multi-hop
→ scoring
→ HTML
```

В среде, где была собрана эта версия, исходящие DNS/Internet вызовы из Python-контейнера заблокированы, поэтому live GitHub authentication нельзя было выполнить из сборочного контейнера. Именно поэтому в программе есть отдельный `doctor`, который первым делом выполняет live API smoke-test уже на твоём Windows PC.

Это ограничение тестовой среды, а не замена live-проверки.

---

# 41. Официальные GitHub документы, под которые рассчитана версия

- REST starring: https://docs.github.com/en/rest/activity/starring
- REST rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- REST best practices: https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
- GraphQL users: https://docs.github.com/en/graphql/reference/users
- GraphQL repositories: https://docs.github.com/en/graphql/reference/repos
- GraphQL limits: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
- GitHub restriction changelog: https://github.blog/changelog/2026-06-30-upcoming-access-restrictions-to-public-api-endpoints-and-ui-views/

StarBridge отправляет REST header:

```text
X-GitHub-Api-Version: 2026-03-10
```

---

# 42. Самая первая команда, которую тебе нужно выполнить

После распаковки и установки token:

```powershell
cd C:\StarBridge_1_0
$env:GITHUB_TOKEN = "github_pat_ТВОЙ_ТОКЕН"
py .\starbridge.py selftest
py .\starbridge.py --db .\starbridge_1_0.db doctor --user YOUR_GITHUB_LOGIN
```

Если обе команды успешны — переходи к маленькому `--budget 150` scan.

После него — к полноценному adaptive scan.
