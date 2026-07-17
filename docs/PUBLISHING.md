# Publishing checklist

## Before the first release

1. Confirm ownership of the GitHub repository and npm package.
2. Enable GitHub private vulnerability reporting.
3. Enable npm two-factor authentication.
4. Configure npm trusted publishing for this repository and `release.yml`.
5. Create a protected GitHub environment named `npm`.
6. Review README claims, package contents, Apache-2.0 LICENSE, and NOTICE.

## Local acceptance

```bash
npm ci
npm run release:check
npm pack
npm run build:skill
```

Inspect `npm pack --dry-run`. The tarball must not contain workbench evidence, source documents, credentials, `.env`, caches, or local databases.

## Manual first publication

```bash
npm login
npm whoami
npm publish --access public --provenance
```

Verify from a clean directory:

```bash
npm view llm-wiki-rag version dist.integrity repository license
npx llm-wiki-rag@1.0.2 --version
```

## GitHub release

```bash
git tag -a v1.0.2 -m "LLM-WIKI-RAG 1.0.2"
git push origin v1.0.2
```

The workflow verifies, publishes to npm, builds `.skill`, and creates the GitHub release. Push a tag only after trusted publishing and the `npm` environment are configured.

## Recovery

- npm versions are immutable; publish a patch rather than replacing one.
- Deprecate a broken version with `npm deprecate llm-wiki-rag@<version> "reason"`.
- Avoid unpublish except for serious legal or security incidents permitted by npm policy.
- Rotate any credential exposed in history, logs, chat, commits, packages, or reports.
