"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const cli = path.join(root, "bin", "llm-wiki-rag.js");
const project = fs.mkdtempSync(path.join(os.tmpdir(), "llm-wiki-rag-npm-smoke-"));

function run(args, expected = 0) {
  const result = spawnSync(process.execPath, [cli, ...args], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" }
  });
  assert.equal(result.status, expected, result.stderr || result.stdout);
  return result.stdout.trim() ? JSON.parse(result.stdout) : null;
}

const version = spawnSync(process.execPath, [cli, "--version"], { encoding: "utf8" });
assert.equal(version.status, 0);
assert.match(version.stdout, /^1\.0\.1\s*$/);

run(["init", "--project", project]);
fs.writeFileSync(
  path.join(project, "raw", "sources", "guide.md"),
  "# Recovery guide\n\nAudit the project, inspect snapshots, and confirm rollback.\n",
  "utf8"
);
const applied = run(["update", "--project", project, "--apply"]);
assert.equal(applied.status, "accepted");
assert.equal(applied.chunk_count, 1);
const query = run(["query", "--project", project, "--text", "rollback snapshots"]);
assert.equal(query.results[0].relative_path, "raw/sources/guide.md");
const audit = run(["audit", "--project", project]);
assert.equal(audit.passed, true);

process.stdout.write("npm CLI smoke passed.\n");
