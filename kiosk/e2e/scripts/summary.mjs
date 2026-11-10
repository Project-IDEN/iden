/**
 * test-results-m07/SUMMARY.md from Playwright's JSON report: one row per test
 * case with what was expected, what the screen showed, the verdict and the
 * screenshot. Run after `pnpm test`: `node scripts/summary.mjs`.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const RESULTS = process.env.M07_RESULTS_DIR
  ? `${process.env.M07_RESULTS_DIR.replace(/[\\/]+$/, "")}/`
  : fileURLToPath(new URL("../../../test-results-m07/", import.meta.url));
const report = JSON.parse(readFileSync(`${RESULTS}results.json`, "utf8"));
const teardown = existsSync(`${RESULTS}teardown.json`)
  ? JSON.parse(readFileSync(`${RESULTS}teardown.json`, "utf8"))
  : null;

const cell = (text) => String(text ?? "").replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();

function* specs(suite) {
  for (const spec of suite.specs ?? []) yield spec;
  for (const child of suite.suites ?? []) yield* specs(child);
}

const rows = [];
for (const suite of report.suites) {
  for (const spec of specs(suite)) {
    const result = spec.tests[0]?.results.at(-1);
    const notes = spec.tests[0]?.annotations ?? [];
    const pick = (type) => notes.filter((n) => n.type === type).map((n) => n.description);
    const id = spec.title.match(/^TC-\d+/)?.[0] ?? spec.title;
    const expected = pick("expected");
    const actual = pick("actual");
    const shots = pick("screenshot");
    const status = result?.status === "passed" ? "Pass" : result?.status === "skipped" ? "Skipped" : "Fail";
    const error = result?.error?.message?.split("\n")[0]?.replace(/\u001b\[[0-9;]*m/g, "");
    rows.push({
      id,
      title: spec.title,
      expected: expected.join(" / then: ") || "—",
      actual: actual.join(" / then: ") || (error ? `stopped before the expected moment: ${error}` : "—"),
      status,
      error: status === "Fail" ? error : "",
      shots: shots.join(", ") || "—",
      seconds: Math.round((result?.duration ?? 0) / 1000),
    });
  }
}

// Cases run by hand, recorded by the tester in manual.json beside the results.
const manual = existsSync(`${RESULTS}manual.json`)
  ? JSON.parse(readFileSync(`${RESULTS}manual.json`, "utf8"))
  : [];

const passed = rows.filter((r) => r.status === "Pass").length;
const lines = [
  "# Sheet M07 — kiosk, automated",
  "",
  `Run ${report.stats?.startTime ?? ""} on the local stack only (provider http://localhost:8000, kiosk server http://127.0.0.1:8080). ` +
    `${rows.length} automated cases: **${passed} passed, ${rows.length - passed} failed**` +
    (manual.length ? `; ${manual.length} rows run by hand (marked *manual*).` : ".") +
    " No application code was changed; failures are recorded, not fixed.",
  "",
  "| TC id | Expected | Actual (what the screen showed) | Pass/Fail | Screenshot |",
  "|---|---|---|---|---|",
  ...rows.map(
    (r) =>
      `| ${cell(r.id)}${r.title.includes("timed-capture") ? " (timed-capture path)" : ""} | ${cell(r.expected)} | ${cell(r.actual)}${
        r.error ? ` — assertion: \`${cell(r.error)}\`` : ""
      } | **${r.status}** | ${cell(r.shots)} |`,
  ),
  ...manual.map(
    (m) => `| ${cell(m.id)} | ${cell(m.expected)} | ${cell(m.actual)} | **${cell(m.status)}** | ${cell(m.screenshot)} |`,
  ),
  "",
  "## After the run",
  "",
  teardown
    ? [
        `- Kiosk **${teardown.kioskName}** (\`${teardown.kioskId}\`): status \`${teardown.kioskStatus}\`, in service: **${teardown.kioskInService}**, paired at ${teardown.kioskPairedAt}, last seen ${teardown.kioskLastSeenAt}. Left paired and in service for TC-206/207/208.`,
        `- Test user \`${teardown.userEmail}\`: face enrolled before deletion: **${teardown.userFaceEnrolledBeforeDelete}**; deleted: **${teardown.userDeleted}**.`,
      ].join("\n")
    : "- teardown.json missing: global teardown did not finish.",
  "",
  "## Notes",
  "",
  "- **TC-209 is run by hand.** A still photograph cannot perform the head movements the capture asks for, so the case needs a live",
  "  person in poor light. Too dark, and the MediaPipe head tracker cannot follow the head: the capture stops at the head-movement",
  "  challenge on the kiosk (`kiosk/client/src/ui/capture-sequence.ts`) and no frame reaches IDEN, so the light-specific advice the",
  "  engine would give (`poor_capture` / `too_dark`) is never shown. A little dark, and the head challenge passes but the engine's",
  "  anti-spoofing check refuses the capture, which the kiosk explains as \"Make sure your face is evenly lit, with nothing covering",
  "  it, and try again.\" (`kiosk/client/src/screens/enrol-problems.ts`, `not_live` → `anti_spoofing`). Recorded in `manual.json`.",
  "- Camera: Chromium `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-video-capture=<file>`,",
  "  each `.y4m` a still image looped ~30 s (640×480, 5 fps), made with ffmpeg 6.1.1 from `ffmpeg-static`. The QR code encodes the raw",
  "  ticket string — what the dashboard draws with `QRCodeSVG value={ticket.ticket}` (`web/dashboard/src/features/account/security-face.tsx:137`).",
  "- Kiosk timings seen: settings changes and IDEN outages reach the screen within one heartbeat (60 s) plus one client poll (10 s);",
  "  recovery after the provider restarts takes up to the 15 s retry plus the poll.",
  "",
  "## Commands run",
  "",
  "```bash",
  "# the local stack (repository root)",
  "IDEN_BIOMETRIC_ENABLED=true docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.engine-gpu.yml \\",
  "  up -d --no-build postgres redis seaweedfs migrate provider engine",
  "# the kiosk client, with its head tracker",
  "cd kiosk/client && pnpm build",
  "# the suite (starts the kiosk server itself: node scripts/start-kiosk.mjs --fresh)",
  "cd kiosk/e2e && pnpm install",
  "M07_ADMIN_EMAIL=tds-admin@localhost M07_ADMIN_PASSWORD='…' npx playwright test",
  "node scripts/summary.mjs",
  "# inside the cases, run by the tests themselves:",
  "#   docker compose -f deploy/docker-compose.yml stop provider     (TC-200)",
  "#   docker compose -f deploy/docker-compose.yml start provider    (TC-200)",
  "#   docker compose -f deploy/docker-compose.yml exec -T redis redis-cli -a iden --no-auth-warning EXPIRE face-ticket:<sha256(ticket)> 1   (TC-204)",
  "```",
  "",
];
writeFileSync(`${RESULTS}SUMMARY.md`, lines.join("\n"));
console.log(`SUMMARY.md: ${passed}/${rows.length} passed`);
