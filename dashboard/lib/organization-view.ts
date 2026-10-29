import type { Tenant } from "./overview.ts";

export function filterOrganizations(
  tenants: Tenant[],
  value: string,
): Tenant[] {
  const query = value.trim().toLowerCase();
  return tenants.filter((tenant) => tenant.name.toLowerCase().includes(query));
}
