/**
 * The kiosk's browser: Chromium with a fake camera playing a chosen .y4m file,
 * opened on the kiosk server's UI. One browser per test, because the camera
 * file is fixed when Chromium starts.
 */
import { chromium, expect, type Browser, type Page, type TestInfo } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { KIOSK, SCREENSHOTS } from "./iden";

export interface Kiosk {
  browser: Browser;
  page: Page;
  close: () => Promise<void>;
}

/** Counts every call to navigator.mediaDevices.getUserMedia on the page, in window.__gumCalls. */
const COUNT_CAMERA_REQUESTS = `
  window.__gumCalls = 0;
  const devices = navigator.mediaDevices;
  if (devices && devices.getUserMedia) {
    const original = devices.getUserMedia.bind(devices);
    devices.getUserMedia = (...args) => {
      window.__gumCalls += 1;
      return original(...args);
    };
  }
`;

export async function openKiosk(video: string, options: { blockTracker?: boolean } = {}): Promise<Kiosk> {
  const browser = await chromium.launch({
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-video-capture=${video}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await context.addInitScript(COUNT_CAMERA_REQUESTS);
  const page = await context.newPage();
  if (options.blockTracker) {
    // The client then captures on its timer instead of following the head tracker.
    await page.route("**/tracker/**", (route) => route.abort());
  }
  await page.goto(KIOSK);
  return { browser, page, close: () => browser.close() };
}

export async function cameraRequests(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __gumCalls: number }).__gumCalls);
}

export const idle = (page: Page) => page.getByRole("button", { name: "Start enrolling your face" });

export async function expectIdle(page: Page, timeout = 15_000) {
  await expect(idle(page)).toBeVisible({ timeout });
}

/** Idle → consent → agree → the QR scanner, which reads whatever the camera shows. */
export async function startAndAgree(page: Page) {
  await idle(page).click();
  await page.getByRole("button", { name: "I agree, continue" }).click();
  await expect(page.getByRole("heading", { name: "Show your QR code" })).toBeVisible();
}

/** The screenshot at the expected-result moment, named by the TC id and attached to the report. */
export async function shot(page: Page, info: TestInfo, name: string) {
  mkdirSync(SCREENSHOTS, { recursive: true });
  const path = `${SCREENSHOTS}${name}.png`;
  await page.screenshot({ path, fullPage: true });
  await info.attach(name, { path, contentType: "image/png" });
  return `screenshots/${name}.png`;
}

/** Records what was expected and what the screen showed, for SUMMARY.md. */
export function record(info: TestInfo, expected: string, actual: string, screenshot: string) {
  info.annotations.push(
    { type: "expected", description: expected },
    { type: "actual", description: actual },
    { type: "screenshot", description: screenshot },
  );
}

/** The visible text of the page, on one line, for the "actual" column. */
export async function screenText(page: Page) {
  return (await page.locator("body").innerText()).replace(/\s+/g, " ").trim().slice(0, 400);
}
