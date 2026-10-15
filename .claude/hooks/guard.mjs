// Project guardrail (PreToolUse, Bash). Exit 2 blocks the call; the message goes back to the model.
import { readFileSync } from "node:fs";

const input = JSON.parse(readFileSync(0, "utf8") || "{}");
const command = String(input?.tool_input?.command ?? "");

const rules = [
  [
    /\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)/,
    "Force-pushing is not allowed.",
  ],
  [
    /\bgit\s+push\b[^\n]*\b(main|master)\b/,
    "Push a branch and open a PR; do not push to main.",
  ],
  [
    /\bgh\s+pr\s+merge\b(?![^\n]*--match-head-commit)/,
    "Merge only with --match-head-commit <sha> after the CI gate is green.",
  ],
  [
    /E2E_ENABLED\s*=\s*true/i,
    "Do not enable E2E in CI; run specs locally instead.",
  ],
  [/\bnpm\s+publish\b/, "Publishing is not allowed."],
];

for (const [pattern, message] of rules) {
  if (pattern.test(command)) {
    console.error(`Blocked by project guardrail: ${message}`);
    process.exit(2);
  }
}
