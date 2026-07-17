"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const pkg = require(path.join(root, "package.json"));
const required = [
  "README.md",
  "README.ru.md",
  "LICENSE",
  "NOTICE",
  "SECURITY.md",
  "bin/llm-wiki-rag.js",
  "docs/assets/architecture.svg",
  "docs/assets/update-lifecycle.svg",
  "source/llm-wiki-rag-orchestrator/SKILL.md",
  "source/llm-wiki-rag-orchestrator/scripts/llm_wiki_rag.py"
];

const missing = required.filter((relative) => !fs.existsSync(path.join(root, relative)));
if (missing.length) {
  process.stderr.write(`Missing publish files:\n${missing.map((item) => `- ${item}`).join("\n")}\n`);
  process.exit(1);
}
if (pkg.license !== "Apache-2.0") {
  process.stderr.write("package.json must declare Apache-2.0.\n");
  process.exit(1);
}
if (!/^\d+\.\d+\.\d+$/.test(pkg.version)) {
  process.stderr.write("package.json must contain a stable semantic version.\n");
  process.exit(1);
}
process.stdout.write(`Publish manifest verified for ${pkg.name}@${pkg.version}.\n`);
