import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  API_BASE_URL,
  completeTask,
  editTask,
  getCurrentUser,
  listEmails,
  listNotifications,
  listTasks,
  loginUrl,
  logout,
  markEmailRead,
} from "@/lib/api";

function jsonResponse(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    document.cookie = "aeea_csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("echoes the CSRF cookie back as a header on a mutating request", async () => {
    document.cookie = "aeea_csrf_token=test-csrf-value";
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await logout();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-CSRF-Token"]).toBe("test-csrf-value");
  });

  it("never sends a CSRF header on a safe (GET) request", async () => {
    document.cookie = "aeea_csrf_token=test-csrf-value";
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    await listTasks();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("omits the CSRF header on a mutating request when no cookie is set yet", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await logout();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("loginUrl points at the backend's Google OAuth entry point", () => {
    expect(loginUrl()).toBe(`${API_BASE_URL}/auth/google/login`);
  });

  it("sends credentials + Accept header on every request", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "u1", email: "a@example.com" }));
    await getCurrentUser();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/auth/me`);
    expect(init.credentials).toBe("include");
    expect(init.headers.Accept).toBe("application/json");
  });

  it("adds a JSON Content-Type header only when a body is present", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "t1" }));
    await editTask("t1", { title: "New title" });

    const [, mutatingInit] = fetchMock.mock.calls[0];
    expect(mutatingInit.headers["Content-Type"]).toBe("application/json");
    expect(mutatingInit.body).toBe(JSON.stringify({ title: "New title" }));

    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await listTasks();
    const [, readInit] = fetchMock.mock.calls[1];
    expect(readInit.headers["Content-Type"]).toBeUndefined();
  });

  it("builds query strings from defined params only, dropping undefined ones", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await listEmails({ category: "action_required", is_read: undefined, limit: 25 });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(
      `${API_BASE_URL}/emails?category=action_required&limit=25`,
    );
  });

  it("omits the query string entirely when there are no params", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await listNotifications();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/notifications?unread_only=false`);
  });

  it("returns undefined for a 204 No Content response instead of parsing a body", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(logout()).resolves.toBeUndefined();
  });

  it("throws an ApiError built from the backend's RFC 9457 problem+json body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          title: "Not Found",
          status: 404,
          code: "not_found",
          detail: "No email with this id was found.",
        },
        { status: 404 },
      ),
    );

    const error = await markEmailRead("missing-id").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "No email with this id was found.",
    });
  });

  it("falls back to a synthetic problem when the error body isn't valid JSON", async () => {
    const brokenResponse = new Response("<html>502 Bad Gateway</html>", {
      status: 502,
      statusText: "Bad Gateway",
    });
    fetchMock.mockResolvedValueOnce(brokenResponse);

    const error = (await completeTask("t1").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.code).toBe("unknown_error");
  });
});
