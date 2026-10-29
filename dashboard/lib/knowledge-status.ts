export function knowledgeStatus(status: string): {
  label: string;
  detail: string;
} {
  switch (status) {
    case "pending":
      return {
        label: "Waiting to be indexed",
        detail: "If this does not change, contact an operator.",
      };
    case "processing":
      return {
        label: "Indexing in progress",
        detail: "Check again later for the result.",
      };
    case "ready":
      return {
        label: "Indexed",
        detail:
          "Embedding source is unverified; this status does not confirm provider success.",
      };
    case "failed":
      return {
        label: "Indexing failed",
        detail: "Contact an operator to investigate.",
      };
    default:
      return {
        label: "Index status unknown",
        detail: "Contact an operator to investigate.",
      };
  }
}
