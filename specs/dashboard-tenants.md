# Tenant membership directory

Show the organizations already loaded from the authenticated issuer membership
list, with their names and the user's owner/member role. The directory is a
read-only snapshot; it does not claim a complete list when more pages exist.
The existing load-more control adds another issuer page. Opening an organization
selects its Overview, whose server endpoint rechecks membership. Switching views
aborts outstanding reads. No tenant creation, membership changes, new API,
new dependencies, live providers or existing stand changes are included.

Acceptance: owner/member roles and selected organization are visible; names
remain escaped; an empty list is explicit; paging and denied/expired sessions
use existing controls; opening a tenant performs the existing scoped read.
