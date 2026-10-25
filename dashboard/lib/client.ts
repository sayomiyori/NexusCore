export class RequestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    credentials: "same-origin",
  });
  const data = await response.json();
  if (!response.ok)
    throw new RequestError(
      response.status,
      typeof data.error === "string"
        ? data.error
        : "Data is temporarily unavailable.",
    );
  return data as T;
}
