# Архитектура

LLM-WIKI-RAG разделяет авторитетные входные данные, детерминированное управление состоянием, опциональное семантическое рассуждение и опубликованные знания.

## Слои

1. **Source layer** — пользовательские `.md`, `.markdown`, `.txt` и опциональные PDF.
2. **Control plane** — scanning, SHA256, идентичность источников, locks, budgets, security-gates, snapshots, staging, validation и transactions.
3. **Wiki layer** — проверяемые Markdown-страницы, index, overview и provenance.
4. **Retrieval layer** — chunks, vectors, source IDs, версии векторов и запросы в SQLite.
5. **Operations layer** — reports, metrics, healthcheck, migrations, watcher/cron, incidents и rollback.

![Архитектура](assets/architecture.svg)

## Модель доверия

Raw-источники авторитетны. Детерминированный код отвечает за все долговременные изменения состояния. Опциональные LLM workers могут предлагать семантическую структуру, но результат должен сохранять связь с источниками и пройти validation до публикации.

Стандартный адаптер `hashing-v1` обеспечивает детерминированный offline retrieval. Адаптер `http-json-v1` нельзя считать production-ready до проверки endpoint, credentials, модели, dimensions, response schema, надёжности и retrieval-качества в конкретной среде.

## Модель согласованности

Wiki-страницы и retrieval-чанки строятся из одной changeset. Изменения выполняются под эксклюзивной блокировкой, создают snapshot, собираются в staging, валидируются и публикуются вместе. SQLite хранит состояние, а raw-файлы остаются вне зоны записи runtime.

## Поведение при ошибках

- Ошибка parser или validation предотвращает публикацию.
- Нарушение budget или security блокирует durable mutation.
- Неподтверждённое удаление остаётся планом и не очищает derived state.
- Rollback требует snapshot и совпадающих хэшей raw-источников.
- Reports сохраняют причину и failure mode для оператора.

Подробные worker contracts, runbooks, SLO, migrations, security boundaries и failure modes находятся в `references/` внутри скилла.
