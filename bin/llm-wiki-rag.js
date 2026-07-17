#!/usr/bin/env node

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const packageRoot = path.resolve(__dirname, "..");
const packageJson = require(path.join(packageRoot, "package.json"));
const pythonCli = path.join(
  packageRoot,
  "source",
  "llm-wiki-rag-orchestrator",
  "scripts",
  "llm_wiki_rag.py"
);

function fail(message, code = 1) {
  process.stderr.write(`llm-wiki-rag: ${message}\n`);
  process.exit(code);
}

if (!fs.existsSync(pythonCli)) {
  fail(`Python runtime is missing from the npm package: ${pythonCli}`);
}

const args = process.argv.slice(2);
if (args.length === 1 && ["--version", "-V"].includes(args[0])) {
  process.stdout.write(`${packageJson.version}\n`);
  process.exit(0);
}
if (args.length === 1 && args[0] === "--print-skill-path") {
  process.stdout.write(`${path.dirname(path.dirname(pythonCli))}\n`);
  process.exit(0);
}

const configured = process.env.LLM_WIKI_RAG_PYTHON;
const candidates = configured
  ? [configured]
  : process.platform === "win32"
    ? ["python", "py"]
    : ["python3", "python"];

for (const executable of candidates) {
  const pythonArgs = executable === "py" ? ["-3", pythonCli, ...args] : [pythonCli, ...args];
  const result = spawnSync(executable, pythonArgs, {
    cwd: process.cwd(),
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    stdio: "inherit"
  });
  if (!result.error) {
    if (result.signal) {
      fail(`Python runtime terminated by signal ${result.signal}`, 1);
    }
    process.exit(result.status ?? 1);
  }
  if (result.error.code !== "ENOENT") {
    fail(`unable to start ${executable}: ${result.error.message}`);
  }
}

fail(
  "Python 3.11+ was not found. Install Python or set LLM_WIKI_RAG_PYTHON to its executable path.",
  127
);
