import { describe, expect, it } from "vitest";

import { ACCEPT, fileKind, isSupported } from "@/lib/fileTypes";

describe("file types", () => {
  it("accepts documents by extension or type", () => {
    expect(isSupported({ name: "notes.MD", type: "" })).toBe(true);
    expect(isSupported({ name: "letter.docx", type: "" })).toBe(true);
    expect(isSupported({ name: "page", type: "text/html" })).toBe(true);
    expect(isSupported({ name: "photo.png", type: "image/png" })).toBe(false);
    expect(isSupported({ name: "old.doc", type: "application/msword" })).toBe(false);
    expect(ACCEPT.split(",")).toContain(".markdown");
    // A TypeScript file can arrive as an MPEG stream: its extension decides.
    expect(isSupported({ name: "main.ts", type: "video/mp2t" })).toBe(true);
    expect(isSupported({ name: "lib.rs", type: "" })).toBe(true);
  });

  it("labels stored files by type, then by name", () => {
    expect(fileKind({ content_type: "application/pdf" })).toBe("PDF");
    expect(fileKind({ content_type: "text/markdown" })).toBe("Markdown");
    expect(fileKind({ content_type: "application/octet-stream", original_name: "page.htm" })).toBe("HTML");
    expect(fileKind({ content_type: "text/plain", original_name: "notes.txt" })).toBe("Text");
    expect(fileKind({ content_type: "text/x-python", original_name: "app.py" })).toBe("Python");
    expect(fileKind({ content_type: "text/x-c++" })).toBe("C++");
  });
});
