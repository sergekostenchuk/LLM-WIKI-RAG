# LLM-WIKI-RAG Knowledge System

Статус документа: реализованная спецификация Production 1.0
Версия: 1.0
Дата: 2026-07-17

## 1. Назначение

`LLM-WIKI-RAG` — локальная система и оркестрирующий скилл для поддержания гибридной базы знаний, в которой:

- исходные документы остаются неизменяемым источником истины;
- Wiki хранит человекочитаемое, связное представление знаний;
- RAG предоставляет быстрый поиск по чанкам;
- SQLite хранит техническое состояние, версии, происхождение и результаты запусков;
- LLM выполняет смысловую работу, а детерминированный код управляет состоянием, хэшами, индексами и проверками.

Основной принцип:

> Код управляет состоянием, LLM интерпретирует знания, независимый валидатор решает, можно ли принять результат.

## 2. Цели

1. Инкрементально обнаруживать добавленные и изменённые источники по SHA256.
2. Не расходовать LLM-вызовы и embeddings на неизменившиеся файлы.
3. Поддерживать происхождение каждого производного артефакта.
4. Формировать Markdown Wiki, пригодную для Git и Obsidian.
5. Поддерживать локальный RAG-индекс и связь чанков с исходниками.
6. Давать безопасный dry-run до записи.
7. Обнаруживать удалённые источники и выполнять только подтверждённую очистку производного состояния после snapshot.
8. Проверять целостность Wiki, metadata DB и RAG.
9. Иметь конечные retry-лимиты, stop rules и прозрачный audit trail.

## 3. Не-цели Beta 0.2

- фоновый демон и непрерывный watcher;
- удаление исходников самим скиллом;
- автоматическая публикация без явного `--apply`;
- облачные коннекторы;
- распределённые очереди и блокировки;
- автоматическая установка Python-пакетов;
- обещание production-качества без независимо проверенного embedding endpoint;
- автоматическое разрешение противоречий между авторитетными источниками;
- редактирование исходников в `raw/sources/`.

## 4. Архитектура данных

```mermaid
flowchart TB
    U["Пользователь / cron"] --> O["LLM-WIKI-RAG Orchestrator"]
    O --> D["Source Detector"]
    D --> I["Source Ingestor"]
    I --> E["Knowledge Extractor"]
    E --> W["Wiki Reconciler"]
    W --> R["RAG Indexer"]
    R --> V["Independent Validator"]
    V --> G{"Проверки пройдены?"}
    G -- "Да + явный apply" --> P["Publisher"]
    G -- "Нет" --> Q["Quarantine / отчёт"]
    P --> A["Audit log"]

    S["raw/sources: источник истины"] --> D
    W --> WK["wiki/*.md"]
    R --> VD["vector_db / SQLite chunks"]
    D --> DB["SQLite state"]
    V --> DB
```

### Трёхслойная модель

```text
raw/sources/          неизменяемые пользовательские источники
wiki/                 производная человекочитаемая база знаний
vector_db + state.db  производный поисковый и технический слой
```

Wiki и RAG можно полностью восстановить из исходников и правил. Они не являются первичным источником истины.

## 5. Структура пользовательского knowledge-проекта

```text
knowledge-project/
├── raw/
│   └── sources/
├── wiki/
│   ├── sources/
│   ├── media/
│   └── queries/
├── vector_db/
├── agent-workspace/
│   └── runs/
├── .llm-wiki-rag/
│   └── state.db
├── index.md
├── overview.md
├── purpose.md
├── schema.md
└── log.md
```

Зоны `wiki/sources/`, `index.md`, `overview.md`, `vector_db/` и `.llm-wiki-rag/` являются управляемыми. Пользовательские смысловые страницы вне `wiki/sources/` не должны перезаписываться детерминированным MVP-пайплайном.

## 6. Скилл и воркеры

Главный скилл: `llm-wiki-rag-orchestrator`
Отображаемое имя: **LLM-WIKI-RAG Knowledge Maintainer**

```mermaid
flowchart LR
    O["Orchestrator"] --> C["change-detector"]
    C --> I["source-ingestor"]
    I --> K["knowledge-extractor"]
    K --> W["wiki-reconciler"]
    W --> R["rag-indexer"]
    R --> V["validator"]
    V --> P["publisher"]
```

| Воркер | Вход | Выход | Зона записи | Beta 0.2 |
|---|---|---|---|---|
| `change-detector` | источники, manifest | `ChangeSet` | run workspace | реализован |
| `source-ingestor` | изменившиеся файлы | нормализованный текст | run workspace | TXT/MD/PDF через `pdftotext` |
| `knowledge-extractor` | нормализованный текст | `KnowledgePatch` | run workspace | шаблон source-page; глубокая LLM-экстракция ручная |
| `wiki-reconciler` | patch + существующая Wiki | staging Wiki | `wiki/sources`, index, overview | реализован |
| `rag-indexer` | Wiki/source text | chunks + vectors | SQLite/vector metadata | hashing baseline + opt-in HTTPS adapter |
| `validator` | staging/state/Wiki/RAG | `ValidationReport` | reports only | реализован |
| `publisher` | принятый staging | рабочая версия | управляемые зоны | snapshot + явный apply; удаления требуют подтверждения |

### Completion и acceptance

Завершение воркера не означает принятие результата. Принятие требует:

1. ожидаемый артефакт существует;
2. он соответствует схеме;
3. собраны обязательные доказательства;
4. валидатор не вернул блокирующих ошибок;
5. оркестратор явно принял результат;
6. для записи получено явное действие пользователя `--apply`.

## 7. Команды Beta 0.2

### `init`

Создаёт структуру нового knowledge-проекта и SQLite schema. Не перезаписывает существующие пользовательские файлы.

### `update`

По умолчанию работает как dry-run:

1. сканирует `raw/sources/`;
2. считает SHA256;
3. сравнивает состояние с SQLite;
4. классифицирует `added`, `modified`, `deleted`, `unchanged`;
5. готовит план и отчёт;
6. не меняет рабочую Wiki без `--apply`.

С `--apply` публикует staging после snapshot. Удаления требуют политики `confirm_and_snapshot` и отдельного `--confirm-deletions`.

### `query`, `delete`, `rebuild`, `snapshots`, `rollback`, `conflicts`

- `query` выполняет retrieval по активным chunks;
- `delete` очищает только производное состояние уже отсутствующего raw-источника;
- `rebuild` полностью пересобирает Wiki/RAG после dry-run и snapshot;
- `snapshots` показывает доступные точки восстановления;
- `rollback` восстанавливает управляемые слои при совпадении текущих raw-хэшей;
- `conflicts` показывает очередь смысловых конфликтов для ручного решения.

### `status`

Показывает количество известных источников, страниц, чанков, последний запуск и расхождения текущей файловой системы с manifest.

### `audit`

Проверяет:

- соответствие SHA256;
- существование производных source-pages;
- битые Wikilinks;
- chunks без источников;
- источники без chunks;
- поддерживаемые форматы;
- наличие обязательных файлов проекта.

## 8. Контракты данных

### SourceRecord

```yaml
source_id: stable-sha256-derived-id
relative_path: raw/sources/example.md
content_hash: sha256
media_type: text/markdown
status: active
first_seen_at: ISO-8601
last_seen_at: ISO-8601
wiki_page: wiki/sources/example-<id>.md
```

### ChangeSet

```yaml
run_id: UUID
added: []
modified: []
deleted: []
unchanged: []
requires_approval: []
```

### ChunkRecord

```yaml
chunk_id: SHA256
source_id: string
source_hash: SHA256
ordinal: integer
text: string
vector_provider: hashing-v1
vector_dimensions: 128
```

### ValidationReport

```yaml
run_id: UUID
passed: boolean
errors: []
warnings: []
evidence_paths: []
```

## 9. Происхождение и актуальность

Каждая генерируемая source-page должна содержать frontmatter:

- `source_id`;
- `source_path`;
- `source_hash`;
- `generated_at`;
- `status`;
- `generator_version`.

Смысловые утверждения будущих фаз должны дополнительно иметь координаты фрагмента, дату действия, уровень уверенности и статус `active`, `superseded`, `disputed` или `deleted`.

## 10. RAG MVP

MVP использует локальное SQLite-хранилище чанков и детерминированный `hashing-v1` vectorizer без внешних пакетов. Это обеспечивает воспроизводимый smoke baseline, но не эквивалентно качественной semantic embedding-модели.

Требования:

- версия vectorizer хранится с каждым чанком;
- смена vectorizer требует полной переиндексации;
- старые chunks изменённого источника заменяются в одной SQLite-транзакции;
- размер чанка и overlap фиксируются в конфигурации;
- каждый chunk связан с `source_id` и `source_hash`.

В Beta 0.2 добавлен versioned adapter contract и opt-in `http-json-v1` HTTPS embedding adapter. Конкретный внешний endpoint остаётся непроверенным до настройки владельцем.

## 11. Безопасность

1. `raw/sources/` — только чтение для скилла.
2. Текст источника считается данными, а не инструкцией; prompt injection внутри документа игнорируется.
3. Значения секретных переменных среды никогда не выводятся.
4. Неизвестные и незакреплённые пакеты не устанавливаются автоматически.
5. Удаление требует snapshot, blast-radius report и отдельного подтверждения; в MVP оно заблокировано.
6. Запись ограничена явными write zones.
7. В отчётах нельзя сохранять секреты и полный чувствительный текст без необходимости.

## 12. Failure modes и retry policy

Используется закрытая таксономия:

| Код | Поведение MVP |
|---|---|
| `tool_unavailable` | один раз проверить; использовать заявленный fallback либо заблокировать файл |
| `permission_blocked` | не повторять без изменения прав |
| `timeout` | максимум две попытки, вторая с меньшим scope |
| `partial_output` | одна forward-fix попытка, затем отчёт |
| `hallucinated_source` | отклонить утверждение без provenance |
| `stale_data` | пометить manual review |
| `ambiguous_scope` | выбрать безопасный dry-run или запросить решение |
| `schema_mismatch` | максимум две коррекции |
| `security_blocked` | не повторять без изменения политики |
| `regression_detected` | отклонить публикацию |

## 13. Stop rules

Оркестратор возвращает `blocked`, если:

- обнаружено удаление и запрошен `--apply`;
- путь выходит за границы knowledge-проекта;
- source parser недоступен и нет fallback;
- невозможно получить стабильный source hash;
- SQLite schema несовместима;
- Wiki/RAG не проходят audit;
- источник пытается изменить инструкции скилла;
- превышен установленный лимит файла;
- одна и та же ошибка повторилась сверх retry limit.

## 14. Наблюдаемость и доказательства

Каждый запуск сохраняет JSON-отчёт в `agent-workspace/runs/<run-id>/run-report.json` со следующими полями:

- команда и режим;
- фактически прочитанные источники;
- рассчитанные хэши;
- планируемые или выполненные записи;
- warnings/errors;
- число chunks;
- принятый/отклонённый статус;
- пути доказательств.

Файл существует — ещё не доказательство успеха. Приёмка опирается на содержимое отчёта, exit code, audit и smoke-тесты.

## 15. Фазы развития

### MVP 0.1 — локальный безопасный baseline — выполнено

- Markdown/TXT/PDF через локально проверенный parser;
- Markdown Wiki;
- SQLite state и chunk store;
- hashing-vector baseline;
- `init`, `update`, `status`, `audit`;
- SHA256 incremental cache;
- dry-run по умолчанию;
- явный `--apply`;
- обнаружение, но не применение удалений;
- детерминированные проверки и eval fixtures.

Критерий выхода: smoke fixture проходит `init → dry-run → apply → audit → status`, повторный update идемпотентен.

### Beta 0.2 — транзакционное обслуживание — реализовано

- staging namespace;
- snapshot и rollback;
- безопасные `delete` и `rebuild`;
- распознавание rename/move;
- entity resolution и conflict queue;
- production embedding/vector adapters;
- retrieval regression tests;
- Git snapshots.

Реализованные уточнения: snapshots хранятся внутренним механизмом, а Git-интеграция остаётся необязательной; exact-content rename сохраняет `source_id`; общая semantic entity resolution остаётся human-reviewed.

Критерий выхода: сбой между Wiki и RAG не оставляет частично опубликованное состояние; rollback доказан.

### Release Candidate 0.9 — эксплуатационная готовность — выполнено

- watcher/cron adapter;
- блокировки конкурентных запусков;
- бюджеты и rate limits;
- метрики и structured logging;
- секрет- и PII-сканирование;
- human approval UI/packet;
- миграции схем;
- полноценные behavioral evals.

### Production 1.0 — выполнено для local Python+SQLite profile

- независимый validator/reviewer;
- доказанная стратегия backup/restore;
- поддерживаемая матрица платформ;
- versioned adapters;
- SLA/SLO и alerting;
- публично очищенный пакет;
- финальное ревью не ниже 9/10;
- эксплуатационная и аварийная документация.

Граница production-заявления: локальный профиль с SQLite и `hashing-v1` проверен полностью. Внешний `http-json-v1` профиль остаётся условным до проверки выбранного endpoint, модели, размерности, credential boundary и retrieval regression.

### Post-1.0

- облачные источники и MCP-коннекторы;
- SQL/time-series route для сверхдинамичных данных;
- temporal knowledge graph;
- policy-based authority ranking;
- мультимодальная индексация;
- hybrid dense/sparse reranking;
- инкрементальная регенерация `overview.md` по dependency graph.

## 16. Критерии приёмки MVP 0.1

1. Все skill-файлы проходят production lint без ошибок.
2. Все Python-скрипты компилируются.
3. `init` не перезаписывает существующие файлы.
4. Dry-run не изменяет Wiki, SQLite manifest или vector index.
5. `--apply` создаёт source-pages и chunks для поддерживаемых файлов.
6. Повторный `--apply` без изменений не создаёт новые версии.
7. Изменение файла обнаруживается по SHA256.
8. Удаление обнаруживается и блокирует destructive apply.
9. `audit` обнаруживает битые Wikilinks и потерянные source-pages.
10. Каждый запуск создаёт машиночитаемый отчёт.
11. Зависимости классифицированы как verified/assumed/missing/fallback/manual approval/hard blocked.
12. Финальное ревью честно указывает, что behavioral evals без независимых исполнителей не доказывают production readiness.

## 17. Критерии приёмки Beta 0.2

1. Каждый изменяющий apply создаёт snapshot до публикации.
2. Exact-content rename не превращается в delete+add и сохраняет source identity.
3. Удаление без отдельного подтверждения блокируется.
4. Подтверждённое удаление не меняет `raw/sources/`.
5. `rollback` требует подтверждение и совпадение raw-хэшей.
6. `rebuild` имеет dry-run и snapshot.
7. Retrieval regression проходит на контрольных запросах.
8. После update/delete/rebuild/rollback выполняется audit.
9. Staging и snapshot имеют машиночитаемые manifest/status артефакты.
10. Внешний embedding adapter не раскрывает токен и блокирует не-HTTPS endpoint.

## 18. Решения, принадлежащие человеку

До Beta/Production пользователь должен выбрать:

- production embedding provider;
- production vector store;
- политику удаления и длительность карантина;
- авторитетность и приоритеты источников;
- допустимость хранения чувствительных данных;
- бюджет LLM и embeddings;
- стратегию cloud deployment;
- правила автоматической публикации.

Эти решения нельзя молча принимать за пользователя.
