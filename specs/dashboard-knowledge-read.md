# Tenant knowledge inventory

Expose the existing tenant-scoped document list in the dashboard as a read-only
inventory. Authorize membership freshly before every AgentHub GET and never
expose document paths, content, embeddings or credentials. Project only ID,
title, type, status and chunk count, validating bounded values and ascending IDs.
Read up to 50 records with a bounded numeric offset; a full page may have an empty
next page. Users can move to the first, previous or next page. Concurrent changes
may shift offset pages. Tenant and page changes
clear old results and abort in-flight reads.
If a page read fails, the user can explicitly retry that page without changing
the tenant or offset. Authentication expiry still ends the session.
The endpoint remains disabled when AgentHub tenant resources are disabled. No
uploads, deletion, automatic retries, real providers or existing stand changes are in scope.
Test issuer denial, malformed source, pagination, isolation and session expiry.
