import type { Page, TestInfo } from "@playwright/test";
import { record, screenText, shot } from "./kiosk";

/**
 * The expected-result moment of a case: run its assertion, then — pass or
 * fail — take the screenshot and record what the screen actually showed. A
 * failed assertion is re-thrown afterwards, so the case still fails.
 */
export async function checkpoint(
  page: Page,
  info: TestInfo,
  name: string,
  expected: string,
  assertion: () => Promise<string | void>,
) {
  let error: unknown;
  let note: string | void = undefined;
  try {
    note = await assertion();
  } catch (caught) {
    error = caught;
  }
  const screenshot = await shot(page, info, name);
  const seen = await screenText(page);
  record(info, expected, note ? `${note} — screen: ${seen}` : `screen: ${seen}`, screenshot);
  if (error) throw error;
}
