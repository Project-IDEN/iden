/**
 * After the run: the kiosk is left paired and in service for the hand-run
 * cases, and the test user is checked for a face and then deleted. What was
 * found is written to test-results-m07/teardown.json for SUMMARY.md.
 */
import { writeFileSync } from "node:fs";
import { RESULTS, adminToken, api, faceStatus, kioskRecord, loadState, setKioskSettings } from "./support/iden";

export default async function globalTeardown() {
  const { kiosk, user } = loadState();
  const report: Record<string, unknown> = { kioskId: kiosk.id, kioskName: kiosk.name, userId: user.id, userEmail: user.email };

  await setKioskSettings({ inService: true, notice: null });
  const record = await kioskRecord();
  report.kioskStatus = record.status;
  report.kioskInService = record.settings.inService;
  report.kioskPairedAt = record.pairedAt;
  report.kioskLastSeenAt = record.lastSeenAt;

  const face = await faceStatus();
  report.userFaceEnrolledBeforeDelete = face.enrolled;
  if (face.enrolled) {
    // Must never happen: the suite enrols nobody. Removed here so the account
    // leaves no biometric data behind even if a test went wrong.
    await api(await adminToken(), "DELETE", `/admin/users/${user.id}/face`);
  }
  await api(await adminToken(), "DELETE", `/admin/users/${user.id}`);
  report.userDeleted = true;

  writeFileSync(`${RESULTS}teardown.json`, JSON.stringify(report, null, 2));
}
