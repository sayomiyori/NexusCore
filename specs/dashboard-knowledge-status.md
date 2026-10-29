# Knowledge index status presentation

The existing document API returns only indexing state and chunk count, with no
embedding source or provider-error field. Show clear descriptions for all four
known states. For ready documents explicitly state that the embedding source is
unverified and readiness does not confirm successful provider indexing. For
failed documents explain that indexing failed and operator attention is needed;
never infer the reason. Pending may also indicate an uncertain queue receipt.
Do not expose text, vectors, filenames beyond existing metadata, or new API data.
No provider calls, writes, reindexing, or backend contract changes.

Acceptance: render each state with its matching description, preserve accessible
text, existing tenant authorization and paging, pass dashboard tests, lint,
typecheck and build. Verify a rendered view if a safe fixture is available.
