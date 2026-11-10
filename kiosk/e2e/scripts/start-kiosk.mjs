/**
 * Runs the real kiosk server on 127.0.0.1:8080, serving the built kiosk client
 * (kiosk/client/dist) and talking to the local provider.
 *
 *   node scripts/start-kiosk.mjs           keep the pairing in .kiosk-data/
 *   node scripts/start-kiosk.mjs --fresh   start unpaired (what the suite does)
 *
 * The pairing lives in kiosk/e2e/.kiosk-data, never kiosk/server/data, so a run
 * cannot overwrite the credentials of a kiosk you paired by hand.
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const dataDir = here("../.kiosk-data");
const uiDir = here("../../client/dist");
const serverDir = here("../../server");

if (!existsSync(uiDir)) {
  console.error(`No kiosk client build at ${uiDir}. Run: cd kiosk/client && pnpm build`);
  process.exit(1);
}
if (process.argv.includes("--fresh")) rmSync(dataDir, { recursive: true, force: true });
mkdirSync(dataDir, { recursive: true });

const child = spawn(
  "uv",
  ["run", "--project", serverDir, "python", "-m", "uvicorn", "kiosk_server.app:app",
    "--host", "127.0.0.1", "--port", "8080"],
  {
    cwd: serverDir,
    stdio: "inherit",
    env: {
      ...process.env,
      KIOSK_ENV: "prod",
      KIOSK_ISSUER: process.env.M07_ISSUER ?? "http://localhost:8000",
      KIOSK_UI_DIR: uiDir,
      KIOSK_DATA_DIR: dataDir,
      KIOSK_VERSION: "m07-e2e",
    },
  },
);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill());
child.on("exit", (code) => process.exit(code ?? 0));
