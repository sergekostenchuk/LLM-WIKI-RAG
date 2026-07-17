"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const skill = path.join(root, "source", "llm-wiki-rag-orchestrator");
const releaseCheck = path.join(skill, "scripts", "release_check.py");
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "llm-wiki-rag-release-"));
const report = path.join(tempRoot, "release-check.json");
const configured = process.env.LLM_WIKI_RAG_PYTHON;
const candidates = configured
  ? [[configured]]
  : process.platform === "win32"
    ? [["python"], ["py", "-3"]]
    : [["python3"], ["python"]];

for (const [command, ...prefix] of candidates) {
  const result = spawnSync(
    command,
    [...prefix, releaseCheck, "--skill-path", skill, "--output", report],
    {
      cwd: root,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
      stdio: "inherit"
    }
  );
  if (!result.error) {
    if (result.status !== 0 && fs.existsSync(report)) {
      const details = JSON.parse(fs.readFileSync(report, "utf8"));
      for (const check of details.checks || []) {
        if (check.passed) continue;
        process.stderr.write(`Failed command: ${check.command.join(" ")}\n`);
        if (check.stdout) process.stderr.write(`stdout:\n${check.stdout}\n`);
        if (check.stderr) process.stderr.write(`stderr:\n${check.stderr}\n`);
      }
    }
    process.exit(result.status ?? 1);
  }
  if (result.error.code !== "ENOENT") throw result.error;
}

process.stderr.write("Python 3.11+ was not found.\n");
process.exit(127);
