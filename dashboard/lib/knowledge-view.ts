import type { Document } from "./knowledge.ts";

export function filterDocuments(
  documents: Document[],
  value: string,
): Document[] {
  const query = value.trim().toLowerCase();
  return documents.filter((document) =>
    document.title.toLowerCase().includes(query),
  );
}
