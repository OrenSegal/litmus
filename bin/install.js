#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const SKILL_NAME = "litmus";
const SOURCE_DIR = path.join(__dirname, "..", "skills", SKILL_NAME);

function parseTargetDir(argv) {
  const flagIndex = argv.indexOf("--dir");
  if (flagIndex !== -1 && argv[flagIndex + 1]) {
    return argv[flagIndex + 1];
  }
  // Claude Code only loads user skills from ~/.claude/skills; OpenCode reads it too.
  return path.join(os.homedir(), ".claude", "skills", SKILL_NAME);
}

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
  } else {
    fs.copyFileSync(src, dest);
  }
}

function main() {
  const targetDir = parseTargetDir(process.argv.slice(2));

  if (!fs.existsSync(SOURCE_DIR)) {
    console.error(`Skill source not found at ${SOURCE_DIR}`);
    process.exit(1);
  }

  // --dir is the skill's own directory. Never wipe a non-empty one that isn't a skill
  // (e.g. `--dir ~/.claude/skills` would otherwise delete every installed skill).
  if (fs.existsSync(targetDir) && fs.readdirSync(targetDir).length > 0 &&
      !fs.existsSync(path.join(targetDir, "SKILL.md"))) {
    console.error(`Refusing to replace ${targetDir}: not empty and has no SKILL.md`);
    process.exit(1);
  }

  fs.rmSync(targetDir, { recursive: true, force: true });
  copyRecursive(SOURCE_DIR, targetDir);

  console.log(`Installed litmus skill to ${targetDir}`);
  console.log("Engine (CLI): pip install litmus-ci   # provides the `litmus` command");
  console.log("Then in Claude Code / OpenCode:");
  console.log("  /litmus            # author or run a suite");
  console.log("  litmus run <suite> # red/green from the terminal");
}

main();
