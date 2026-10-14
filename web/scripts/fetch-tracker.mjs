// Puts the head tracker's files where an app serves them: MediaPipe's WASM
// runtime, copied from @iden/shared's dependency, and the face landmarker model,
// downloaded once and checked against its sha256. Served by the app itself so
// nothing is fetched from another origin at run time.
//
//     node ../scripts/fetch-tracker.mjs public/tracker
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const MODEL = {
  url: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
  sha256: "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
};
// The SIMD build, and the one without for a browser that lacks it.
const RUNTIME = [
  "vision_wasm_internal.js",
  "vision_wasm_internal.wasm",
  "vision_wasm_nosimd_internal.js",
  "vision_wasm_nosimd_internal.wasm",
];

const out = process.argv[2];
if (!out) throw new Error("usage: fetch-tracker.mjs <output directory>");

const shared = createRequire(new URL("../shared/package.json", import.meta.url));
const wasm = join(dirname(shared.resolve("@mediapipe/tasks-vision")), "wasm");
const sha256 = (data) => createHash("sha256").update(data).digest("hex");

await mkdir(out, { recursive: true });
for (const name of RUNTIME) await copyFile(join(wasm, name), join(out, name));

const model = join(out, "face_landmarker.task");
if (!existsSync(model) || sha256(await readFile(model)) !== MODEL.sha256) {
  const response = await fetch(MODEL.url);
  if (!response.ok) throw new Error(`${MODEL.url} answered ${response.status}`);
  const data = Buffer.from(await response.arrayBuffer());
  if (sha256(data) !== MODEL.sha256) throw new Error(`${MODEL.url} does not match its sha256`);
  await writeFile(model, data);
}
