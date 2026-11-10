/**
 * What the fake camera shows. Chromium plays a .y4m file in a loop as the
 * camera, so every scene is a still image held for a number of seconds, encoded
 * with ffmpeg (the binary from `ffmpeg-static`).
 */
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import ffmpegPath from "ffmpeg-static";
import QRCode from "qrcode";
import { MEDIA, REPO } from "./iden";

const WIDTH = 640;
const HEIGHT = 480;
// Enough for jsQR's 250 ms scan and the capture's frame grabs; a lower rate
// keeps each 30 s file under 70 MB.
const FPS = 5;

/** The face the camera shows in TC-209; `M07_FACE_IMAGE` swaps in another photo. */
export const FACE = process.env.M07_FACE_IMAGE ?? `${REPO}engine/tests/data/astronaut.jpg`;

function ffmpeg(args: string[]) {
  if (!ffmpegPath) throw new Error("ffmpeg-static has no binary for this platform");
  execFileSync(ffmpegPath, ["-hide_banner", "-loglevel", "error", "-y", ...args]);
}

export function mediaPath(name: string) {
  mkdirSync(MEDIA, { recursive: true });
  return `${MEDIA}${name}`;
}

/** A QR code carrying `text`, dark on white — what the dashboard's Security page shows. */
export async function qrPng(text: string, name: string) {
  const path = mediaPath(name);
  await QRCode.toFile(path, text, { width: 420, margin: 4, errorCorrectionLevel: "M" });
  return path;
}

/** `src` with every channel scaled by `factor` — a face in a badly lit room. */
export function darkened(src: string, factor: number, name: string) {
  const path = mediaPath(name);
  const scale = `val*${factor}`;
  ffmpeg(["-i", src, "-vf", `lutrgb=r='${scale}':g='${scale}':b='${scale}'`, path]);
  return path;
}

export interface Scene {
  image: string;
  seconds: number;
  /** What fills the frame around an image that is not 4:3. */
  background?: string;
}

/**
 * The scenes one after another, each fitted into 640×480, as a raw .y4m file
 * Chromium can use as its fake camera. Chromium loops it.
 */
export function y4m(scenes: Scene[], name: string) {
  const path = mediaPath(name);
  const inputs = scenes.flatMap((scene) => ["-loop", "1", "-t", String(scene.seconds), "-i", scene.image]);
  const fitted = scenes.map(
    (scene, index) =>
      `[${index}:v]scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,` +
      `pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=${scene.background ?? "white"},` +
      `fps=${FPS},format=yuv420p,setsar=1[s${index}]`,
  );
  const joined = `${scenes.map((_, index) => `[s${index}]`).join("")}concat=n=${scenes.length}:v=1:a=0[out]`;
  ffmpeg([...inputs, "-filter_complex", [...fitted, joined].join(";"), "-map", "[out]", "-pix_fmt", "yuv420p", "-f", "yuv4mpegpipe", path]);
  return path;
}

/** One still image held for `seconds` (≈30 s by default). */
export function stillY4m(image: string, name: string, seconds = 30, background = "white") {
  return y4m([{ image, seconds, background }], name);
}

/** A plain frame: what the camera sees when nobody is in front of it. */
export function blankPng(name = "blank.png") {
  const path = mediaPath(name);
  ffmpeg(["-f", "lavfi", "-i", `color=c=white:s=${WIDTH}x${HEIGHT}`, "-frames:v", "1", path]);
  return path;
}
