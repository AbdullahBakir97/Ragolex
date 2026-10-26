import { type APIRequestContext, type Page, expect } from "@playwright/test";

/** A handbook the stand-in model answers from: it quotes the first sentence sharing a word. */
export const HANDBOOK = [
  "Employees get 25 days of paid leave each year. Unused leave carries over until March.",
  "",
  "The office closes at 18:00 on Fridays. On other weekdays it is open until 20:00.",
  "",
  "Expenses above 50 euros need a receipt and the approval of a team lead.",
].join("\n");

/** A project name no other test uses, so tests can run in parallel on one database. */
export function projectName(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

/** A project with the handbook, uploaded, split and indexed through the API. */
export async function seedProject(request: APIRequestContext, name: string): Promise<string> {
  const upload = await request.post(`/api/v1/data/upload/${name}`, {
    multipart: { file: { name: "handbook.txt", mimeType: "text/plain", buffer: Buffer.from(HANDBOOK) } },
  });
  expect(upload.ok()).toBeTruthy();
  const { file_id } = await upload.json();
  const processed = await request.post(`/api/v1/data/process/${name}`, {
    data: { file_id, chunk_size: 120, overlap_size: 0 },
  });
  expect(processed.ok()).toBeTruthy();
  expect((await request.post(`/api/v1/index/${name}`)).ok()).toBeTruthy();
  return file_id as string;
}

/** Fails the test on errors the page logs, the way a person would see a broken app. */
export function watchForErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 500) errors.push(`${response.status()} from ${response.url()}`);
  });
  page.on("console", (message) => {
    // The browser's own line for a 404 is expected: a new project has no data until its first upload.
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) errors.push(message.text());
  });
  return errors;
}
