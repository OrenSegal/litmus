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
  return path.join(os.homedir(), ".agents", "skills", SKILL_NAME);
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

// True when replacing `dir` cannot lose anything: it does not exist, is empty,
// or is an earlier copy of this skill (its SKILL.md says `name: litmus`).
function safeToReplace(dir) {
  let stat;
  try {
    stat = fs.statSync(dir);
  } catch (err) {
    return err.code === "ENOENT";
  }
  if (!stat.isDirectory()) {
    return false;
  }
  if (fs.readdirSync(dir).length === 0) {
    return true;
  }
  try {
    const skill = fs.readFileSync(path.join(dir, "SKILL.md"), "utf8");
    return new RegExp(`^name:\\s*["']?${SKILL_NAME}["']?\\s*$`, "m").test(skill);
  } catch (err) {
    return false;
  }
}

function main() {
  const targetDir = parseTargetDir(process.argv.slice(2));

  if (!fs.existsSync(SOURCE_DIR)) {
    console.error(`Skill source not found at ${SOURCE_DIR}`);
    process.exit(1);
  }

  // The target is deleted before the copy, so stale files from an older
  // version do not linger. Only ever delete this skill's own folder.
  if (!safeToReplace(targetDir)) {
    console.error(`Refusing to replace ${targetDir}: it exists and is not a litmus skill folder.`);
    console.error(`--dir is the skill's own folder, for example ${path.join("~", ".claude", "skills", SKILL_NAME)}.`);
    process.exit(1);
  }

  fs.rmSync(targetDir, { recursive: true, force: true });
  copyRecursive(SOURCE_DIR, targetDir);

  console.log(`Installed litmus skill to ${targetDir}`);
  console.log("Engine (CLI): pip install git+https://github.com/OrenSegal/litmus   # provides the `litmus` command");
  console.log("Then in Claude Code / OpenCode:");
  console.log("  /litmus                  # can this eval suite fail?");
  console.log("  litmus vacuity <plugin>  # free check from the terminal");
}

main();
