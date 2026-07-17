# Checklist публикации

## Перед первым релизом

1. Подтвердить владельца GitHub-репозитория и npm-пакета.
2. Включить GitHub private vulnerability reporting.
3. Включить двухфакторную аутентификацию npm.
4. Настроить npm trusted publishing для репозитория и `release.yml`.
5. Создать защищённое GitHub environment `npm`.
6. Проверить README, содержимое пакета, Apache-2.0 LICENSE и NOTICE.

## Локальная приёмка

```bash
npm ci
npm run release:check
npm pack
npm run build:skill
```

Проверьте `npm pack --dry-run`. Tarball не должен содержать workbench, пользовательские документы, credentials, `.env`, caches или локальные БД.

## Первая ручная публикация

```bash
npm login
npm whoami
npm publish --access public --provenance
```

Проверка из чистого каталога:

```bash
npm view llm-wiki-rag version dist.integrity repository license
npx llm-wiki-rag@1.0.2 --version
```

## GitHub Release

```bash
git tag -a v1.0.2 -m "LLM-WIKI-RAG 1.0.2"
git push origin v1.0.2
```

Workflow повторяет проверки, публикует npm, собирает `.skill` и создаёт GitHub Release. Tag отправляется только после настройки trusted publishing и environment `npm`.

## Восстановление

- npm-версии неизменяемы: исправление выпускается новым patch-релизом.
- Проблемную версию можно пометить через `npm deprecate`.
- Unpublish допустим только при серьёзной legal/security-проблеме в рамках npm policy.
- Credential, попавший в history, logs, chat, commit, package или report, следует заменить.
