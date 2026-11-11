/**
 * Sheet M07 — the enrolment kiosk, driven through its real UI and kiosk
 * server against the local provider. In this order: the first two leave the
 * kiosk paired, which every later case needs.
 */
import { expect, test } from "@playwright/test";
import { checkpoint } from "../support/checkpoint";
import {
  adminToken,
  api,
  compose,
  expireTicket,
  faceStatus,
  kioskRecord,
  loadState,
  newTicket,
  setKioskSettings,
} from "../support/iden";
import { cameraRequests, expectIdle, idle, openKiosk, startAndAgree } from "../support/kiosk";
import { mediaPath, qrPng, stillY4m, y4m } from "../support/media";

const BLANK = () => mediaPath("blank.y4m");
const DARK_FACE = () => mediaPath("face-dark-15.png");
const NOTICE = "Testing - back soon";

/** Type a pairing code on the Setup screen's keypad: the eight letters, no dash. */
async function typePairingCode(page: import("@playwright/test").Page, code: string) {
  await page.getByRole("button", { name: "Type the code instead" }).click();
  for (const letter of code.replace(/[^A-Z0-9]/gi, "").toUpperCase()) {
    await page.getByRole("button", { name: letter, exact: true }).click();
  }
  await page.getByRole("button", { name: "Pair", exact: true }).click();
}

/** A camera file showing `ticket` as a QR code, made now so the ticket is fresh. */
async function qrVideo(ticket: string, name: string) {
  return stillY4m(await qrPng(ticket, `${name}.png`), `${name}.y4m`);
}

test("TC-198 wrong pairing code is refused", async ({}, info) => {
  const kiosk = await openKiosk(BLANK());
  try {
    const { page } = kiosk;
    await expect(page.getByRole("heading", { name: "Set up this kiosk" })).toBeVisible();
    await typePairingCode(page, "ABCD-EFGH");

    await checkpoint(page, info, "TC-198", "Error shown, stays on Setup", async () => {
      await expect(page.getByRole("alert")).toHaveText(
        "That code has expired or was already used. Show a new one in the dashboard.",
      );
      await expect(page.getByRole("heading", { name: "Set up this kiosk" })).toBeVisible();
    });
  } finally {
    await kiosk.close();
  }
});

test("TC-197 the real pairing code pairs the kiosk", async ({}, info) => {
  const { kiosk: registered } = loadState();
  const pairing = await api<{ code: string }>(
    await adminToken(),
    "POST",
    `/admin/kiosks/${registered.id}/pairing-code`,
  );
  const kiosk = await openKiosk(BLANK());
  try {
    const { page } = kiosk;
    await expect(page.getByRole("heading", { name: "Set up this kiosk" })).toBeVisible();
    await typePairingCode(page, pairing.code);

    await checkpoint(
      page,
      info,
      "TC-197",
      "Enrolment idle screen; admin API shows the kiosk online / last seen updated",
      async () => {
        await expectIdle(page, 30_000);
        let record = await kioskRecord();
        for (let i = 0; i < 15 && (record.status !== "online" || !record.lastSeenAt); i++) {
          await page.waitForTimeout(1_000);
          record = await kioskRecord();
        }
        expect(record.status).toBe("online");
        expect(record.lastSeenAt).not.toBeNull();
        return `pairing code ${pairing.code}; admin API: status=${record.status}, pairedAt=${record.pairedAt}, lastSeenAt=${record.lastSeenAt}, lastSeenVersion=${record.lastSeenVersion}`;
      },
    );
  } finally {
    await kiosk.close();
  }
});

test("TC-201 holding the top-left corner for 5 s opens maintenance", async ({}, info) => {
  const kiosk = await openKiosk(BLANK());
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await page.mouse.move(10, 10);
    await page.mouse.down();
    await page.waitForTimeout(5_500);
    await page.mouse.up();

    await checkpoint(page, info, "TC-201", "Maintenance menu offering re-pairing", async () => {
      await expect(page.getByRole("heading", { name: "Maintenance" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Pair again" })).toBeVisible();
    });

    // Closed without re-pairing: the kiosk is still paired and back at idle.
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expectIdle(page);
    expect((await kioskRecord()).pairedAt).not.toBeNull();
  } finally {
    await kiosk.close();
  }
});

test("TC-199 out of service shows the notice, and back in service returns to idle", async ({}, info) => {
  test.setTimeout(240_000);
  const kiosk = await openKiosk(BLANK());
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await setKioskSettings({ inService: false, notice: NOTICE });
    const started = Date.now();

    await checkpoint(page, info, "TC-199", `Out of service screen showing "${NOTICE}" within 70 s`, async () => {
      await expect(page.getByRole("heading", { name: "Out of service" })).toBeVisible({ timeout: 70_000 });
      await expect(page.getByText(NOTICE)).toBeVisible();
      return `appeared after ${Math.round((Date.now() - started) / 1000)} s`;
    });

    await setKioskSettings({ inService: true, notice: null });
    const restored = Date.now();
    await checkpoint(page, info, "TC-199-restored", "Back in service: returns to idle", async () => {
      await expectIdle(page, 70_000);
      return `idle again after ${Math.round((Date.now() - restored) / 1000)} s`;
    });
  } finally {
    await setKioskSettings({ inService: true, notice: null });
    await kiosk.close();
  }
});

test("TC-200 provider stopped shows out of order, started again returns to idle", async ({}, info) => {
  test.setTimeout(300_000);
  const kiosk = await openKiosk(BLANK());
  let stopped = false;
  try {
    const { page } = kiosk;
    await expectIdle(page);
    compose("stop", "provider");
    stopped = true;
    const since = Date.now();

    await checkpoint(page, info, "TC-200", `"This kiosk cannot reach IDEN right now" within 70 s`, async () => {
      await expect(page.getByText("This kiosk cannot reach IDEN right now")).toBeVisible({ timeout: 70_000 });
      return `appeared after ${Math.round((Date.now() - since) / 1000)} s (docker compose stop provider)`;
    });

    compose("start", "provider");
    stopped = false;
    const back = Date.now();
    await checkpoint(page, info, "TC-200-restored", "Returns to idle within ~70 s of docker compose start provider", async () => {
      await expectIdle(page, 90_000);
      return `idle again after ${Math.round((Date.now() - back) / 1000)} s`;
    });
  } finally {
    if (stopped) compose("start", "provider");
    await kiosk.close();
  }
});

test("TC-202 declining consent never opens the camera", async ({}, info) => {
  const kiosk = await openKiosk(BLANK());
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await idle(page).click();
    await page.getByRole("button", { name: "No, thanks" }).click();

    await checkpoint(page, info, "TC-202", "Back to idle; getUserMedia called 0 times", async () => {
      await expectIdle(page);
      const calls = await cameraRequests(page);
      expect(calls).toBe(0);
      return `navigator.mediaDevices.getUserMedia calls: ${calls}`;
    });
  } finally {
    await kiosk.close();
  }
});

test("TC-203 a fresh ticket's QR shows the test user's name on the confirm screen", async ({}, info) => {
  const { user } = loadState();
  const kiosk = await openKiosk(await qrVideo(await newTicket(), "tc203-qr"));
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await startAndAgree(page);

    await checkpoint(page, info, "TC-203", `Confirm screen shows "${user.displayName}"`, async () => {
      await expect(page.getByText("Enrolling the face of")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText(user.displayName, { exact: true })).toBeVisible();
    });
  } finally {
    await kiosk.close();
  }
});

test("TC-205 Not me on the confirm screen returns to idle and enrols nothing", async ({}, info) => {
  const kiosk = await openKiosk(await qrVideo(await newTicket(), "tc205-qr"));
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await startAndAgree(page);
    await expect(page.getByText("Enrolling the face of")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "No, that's not me" }).click();

    await checkpoint(page, info, "TC-205", "Back to idle; test user's face status: not enrolled", async () => {
      await expectIdle(page);
      const face = await faceStatus();
      expect(face.enrolled).toBe(false);
      return `GET /entity/face for the test user: ${JSON.stringify(face)}`;
    });
  } finally {
    await kiosk.close();
  }
});

test("TC-204 an expired ticket's QR is refused", async ({}, info) => {
  const ticket = await newTicket();
  const key = expireTicket(ticket, 1);
  await new Promise((resolve) => setTimeout(resolve, 2_500));
  const kiosk = await openKiosk(await qrVideo(ticket, "tc204-qr"));
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await startAndAgree(page);

    await checkpoint(page, info, "TC-204", "Problem screen: ticket invalid", async () => {
      await expect(page.getByRole("heading", { name: "This code can't be used" })).toBeVisible({ timeout: 20_000 });
      return `Redis EXPIRE ${key} 1, then waited 2.5 s`;
    });
  } finally {
    await kiosk.close();
  }
});

/**
 * A dark face through the capture. The camera file shows the ticket's QR for
 * 6 s, then the darkened face for the rest of the loop; the capture is started
 * once the face is on screen.
 */
async function darkCapture(info: import("@playwright/test").TestInfo, name: string, blockTracker: boolean) {
  test.setTimeout(180_000);
  const ticket = await newTicket();
  const qr = await qrPng(ticket, `${name}-qr.png`);
  const video = y4m(
    [
      { image: qr, seconds: 6 },
      { image: DARK_FACE(), seconds: 40, background: "black" },
    ],
    `${name}.y4m`,
  );
  const kiosk = await openKiosk(video, { blockTracker });
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await startAndAgree(page);
    await expect(page.getByText("Enrolling the face of")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Yes, start" }).click();

    const start = page.getByRole("button", { name: "Start", exact: true });
    await expect(start).toBeEnabled({ timeout: 30_000 });
    // Past the QR part of the loop, whether the camera restarted the file or not.
    await page.waitForTimeout(8_000);
    await start.click();

    const serverProblem = page.getByRole("heading", { name: "We couldn't see your face clearly" });
    // The client's own timeouts: no face, or an action not seen (a movement,
    // a blink or a smile, whichever the challenge drew).
    const clientStopped = page.getByText(
      /We couldn't see your face\.|We didn't see (that movement|you blink|a smile)/,
    );
    await expect(serverProblem.or(clientStopped)).toBeVisible({ timeout: 90_000 });

    await checkpoint(
      page,
      info,
      name,
      "Problem screen explaining the light, retry offered; nothing enrolled",
      async () => {
        const face = await faceStatus();
        const path = (await serverProblem.isVisible()) ? "engine judged the frames" : "the client stopped before sending any frame";
        expect(face.enrolled).toBe(false);
        await expect(serverProblem).toBeVisible();
        await expect(page.getByText("It's too dark. Face a lamp or a window.")).toBeVisible();
        await expect(page.getByRole("button", { name: /Try again \(\d+ left\)/ })).toBeVisible();
        return `${path}; face enrolled: ${face.enrolled}`;
      },
    );
  } finally {
    await kiosk.close();
  }
}

// A still photograph cannot follow the head-movement challenge, so with the real
// head tracker the client stops before any frame reaches the engine and the
// light advice is never shown. Run by hand with a live person (see summary.mjs).
test.fixme("TC-209 a badly lit face is refused with advice about the light", async ({}, info) => {
  await darkCapture(info, "TC-209", false);
});

test("TC-209 (timed-capture path, head tracker blocked) a badly lit face is refused with advice about the light", async ({}, info) => {
  await darkCapture(info, "TC-209-timed", true);
});

test("TC-210 left on the confirm screen, the kiosk returns to idle by itself", async ({}, info) => {
  const { settings } = await kioskRecord();
  test.setTimeout((settings.idleSeconds + 120) * 1000);
  const kiosk = await openKiosk(await qrVideo(await newTicket(), "tc210-qr"));
  try {
    const { page } = kiosk;
    await expectIdle(page);
    await startAndAgree(page);
    await expect(page.getByText("Enrolling the face of")).toBeVisible({ timeout: 20_000 });
    const left = Date.now();

    await checkpoint(page, info, "TC-210", `Returns to idle by itself after idleSeconds = ${settings.idleSeconds} s`, async () => {
      await expectIdle(page, (settings.idleSeconds + 30) * 1000);
      const seconds = Math.round((Date.now() - left) / 1000);
      expect(seconds).toBeGreaterThanOrEqual(settings.idleSeconds - 2);
      return `idleSeconds=${settings.idleSeconds}; idle again after ${seconds} s untouched`;
    });
  } finally {
    await kiosk.close();
  }
});
