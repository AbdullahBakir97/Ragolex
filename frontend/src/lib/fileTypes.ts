/** The document types the API reads, as the upload picker and labels need them. */

const KINDS: { kind: string; extensions: string[]; types: string[] }[] = [
  { kind: "PDF", extensions: [".pdf"], types: ["application/pdf"] },
  {
    kind: "Word",
    extensions: [".docx"],
    types: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  },
  { kind: "Markdown", extensions: [".md", ".markdown"], types: ["text/markdown", "text/x-markdown"] },
  { kind: "HTML", extensions: [".html", ".htm"], types: ["text/html"] },
  // Source code, split by the API where its functions and classes start.
  { kind: "Python", extensions: [".py"], types: ["text/x-python"] },
  { kind: "JavaScript", extensions: [".js", ".mjs", ".cjs", ".jsx"], types: ["text/javascript"] },
  { kind: "TypeScript", extensions: [".ts", ".mts", ".cts", ".tsx"], types: ["text/x-typescript"] },
  { kind: "Go", extensions: [".go"], types: ["text/x-go"] },
  { kind: "Java", extensions: [".java"], types: ["text/x-java"] },
  { kind: "Kotlin", extensions: [".kt", ".kts"], types: ["text/x-kotlin"] },
  { kind: "C#", extensions: [".cs"], types: ["text/x-csharp"] },
  { kind: "C", extensions: [".c", ".h"], types: ["text/x-c"] },
  { kind: "C++", extensions: [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"], types: ["text/x-c++"] },
  { kind: "Rust", extensions: [".rs"], types: ["text/x-rust"] },
  { kind: "PHP", extensions: [".php"], types: ["text/x-php"] },
  { kind: "Swift", extensions: [".swift"], types: ["text/x-swift"] },
  { kind: "Text", extensions: [".txt"], types: ["text/plain"] },
];

/** For the file input's `accept` attribute. */
export const ACCEPT = KINDS.flatMap((entry) => [...entry.extensions, ...entry.types]).join(",");

export const SUPPORTED_LABEL = "PDF, Word, Markdown, HTML, text and source code files";

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

/** Whether the API can read the file, by its extension or its type. */
export function isSupported(file: { name: string; type: string }): boolean {
  return KINDS.some((entry) => entry.extensions.includes(extension(file.name)) || entry.types.includes(file.type));
}

/** A short label for a stored file: "PDF", "Word", "Markdown", "HTML", a language such as "Python", or "Text". */
export function fileKind(file: { content_type: string; original_name?: string }): string {
  const byType = KINDS.find((entry) => entry.types.includes(file.content_type));
  const name = extension(file.original_name ?? "");
  const byName = KINDS.find((entry) => entry.extensions.includes(name));
  return (byType ?? byName ?? KINDS.at(-1)!).kind;
}
