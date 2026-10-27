import { authorizedTenant, type Tenant } from "./overview.ts";
import { ApiError, origin, record, requestJson, text } from "./server.ts";

export type Document = {
  id: number;
  title: string;
  type: string;
  status: string;
  chunks: number;
};
export type KnowledgePage = {
  tenant: Tenant;
  items: Document[];
  offset: number;
  nextOffset: number | null;
};

export async function knowledge(
  token: string,
  selected: string,
  offset: number,
): Promise<KnowledgePage> {
  const tenant = await authorizedTenant(token, selected);
  const rows = await requestJson(
    origin("AGENT"),
    `/api/v1/tenants/${tenant.id}/documents?offset=${offset}&limit=50`,
    token,
    tenant.id,
  );
  if (!Array.isArray(rows) || rows.length > 50) throw new ApiError(502);
  let previous = 0;
  const items = rows.map((value): Document => {
    const row = record(value),
      title = text(row.title, 510);
    if (
      !Number.isSafeInteger(row.id) ||
      (row.id as number) <= previous ||
      Array.from(title).length > 255 ||
      typeof row.content_type !== "string" ||
      !["txt", "md", "pdf"].includes(row.content_type) ||
      typeof row.upload_status !== "string" ||
      !["pending", "processing", "ready", "failed"].includes(
        row.upload_status,
      ) ||
      !Number.isSafeInteger(row.chunk_count) ||
      (row.chunk_count as number) < 0
    )
      throw new ApiError(502);
    previous = row.id as number;
    return {
      id: previous,
      title,
      type: row.content_type,
      status: row.upload_status,
      chunks: row.chunk_count as number,
    };
  });
  return {
    tenant,
    items,
    offset,
    nextOffset:
      items.length === 50 && offset + 50 <= 1000000 ? offset + 50 : null,
  };
}
