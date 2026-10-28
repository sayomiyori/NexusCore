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

Organizations has an explicit Refresh control, available even for an empty list
or a failed refresh. It clears loaded rows, current selection and scoped data,
then reads the first membership page again. Success replaces the snapshot and
selects the first returned organization; paging starts again at offset 50.
Pending and failed refreshes are distinct from a successful empty list. Failures
allow an explicit refresh retry; 401 ends the session. Aborted membership reads
cannot restore rows or a logged-out screen. No automatic polling is introduced.
At the maximum accepted offset 100000, a full page has no next-page control;
the loaded count must never be presented as the total membership count.
