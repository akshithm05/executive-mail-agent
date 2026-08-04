import type {
  AppNotification,
  CalendarEvent,
  DashboardSummary,
  DraftReply,
  DraftReplyTone,
  EmailFull,
  EmailSummary,
  Preference,
  Task,
  TaskPriority,
  TaskStatus,
  UserProfile,
} from "@/lib/types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

// Must match app/config/settings.py's CSRFSettings defaults on the backend
// (CSRF_COOKIE_NAME / CSRF_HEADER_NAME) -- the double-submit-cookie pattern:
// the backend hands back a JS-readable cookie at login, and every mutating
// request must echo it back as this header or the backend's CSRF middleware
// rejects it with 403 csrf_check_failed.
const _CSRF_COOKIE_NAME = "aeea_csrf_token";
const _CSRF_HEADER_NAME = "X-CSRF-Token";
const _SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** The backend's RFC 9457 problem+json error shape. */
interface ProblemDetail {
  title: string;
  status: number;
  code: string;
  detail: string;
  request_id?: string;
  errors?: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(problem: ProblemDetail) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.code = problem.code;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const csrfToken = _SAFE_METHODS.has(method) ? null : readCookie(_CSRF_COOKIE_NAME);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken ? { [_CSRF_HEADER_NAME]: csrfToken } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let problem: ProblemDetail;
    try {
      problem = await response.json();
    } catch {
      problem = {
        title: response.statusText,
        status: response.status,
        code: "unknown_error",
        detail: `Request to ${path} failed with ${response.status}.`,
      };
    }
    throw new ApiError(problem);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function queryString<T extends object>(params: T) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// -- Auth ---------------------------------------------------------------

export function loginUrl(): string {
  return `${API_BASE_URL}/auth/google/login`;
}

export async function getCurrentUser(): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/me");
}

export async function logout(): Promise<void> {
  await apiFetch("/auth/logout", { method: "POST" });
}

// -- Dashboard ------------------------------------------------------------

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/dashboard/summary");
}

// -- Emails -----------------------------------------------------------------

export interface ListEmailsParams {
  category?: string;
  is_read?: boolean;
  has_deadline?: boolean;
  sort?: "recent" | "priority";
  limit?: number;
  offset?: number;
}

export async function listEmails(params: ListEmailsParams = {}): Promise<EmailSummary[]> {
  return apiFetch<EmailSummary[]>(`/emails${queryString(params)}`);
}

export async function listUrgentEmails(limit = 6): Promise<EmailSummary[]> {
  return apiFetch<EmailSummary[]>(`/emails/urgent${queryString({ limit })}`);
}

export async function listDeadlineEmails(limit = 6): Promise<EmailSummary[]> {
  return apiFetch<EmailSummary[]>(`/emails/deadlines${queryString({ limit })}`);
}

export async function getEmail(id: string): Promise<EmailFull> {
  return apiFetch<EmailFull>(`/emails/${id}`);
}

export async function markEmailRead(id: string): Promise<EmailFull> {
  return apiFetch<EmailFull>(`/emails/${id}/read`, { method: "POST" });
}

export async function toggleEmailStar(id: string): Promise<EmailFull> {
  return apiFetch<EmailFull>(`/emails/${id}/star`, { method: "POST" });
}

// -- Tasks --------------------------------------------------------------

export async function listTasks(status?: TaskStatus): Promise<Task[]> {
  return apiFetch<Task[]>(`/tasks${queryString({ status })}`);
}

export interface TaskEditPayload {
  title?: string;
  description?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  due_at?: string | null;
}

export async function editTask(id: string, payload: TaskEditPayload): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function completeTask(id: string): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}/complete`, { method: "POST" });
}

// -- Calendar -----------------------------------------------------------

export async function listUpcomingEvents(limit = 50): Promise<CalendarEvent[]> {
  return apiFetch<CalendarEvent[]>(`/calendar-events${queryString({ limit })}`);
}

// -- Notifications --------------------------------------------------------

export async function listNotifications(unreadOnly = false): Promise<AppNotification[]> {
  return apiFetch<AppNotification[]>(
    `/notifications${queryString({ unread_only: unreadOnly })}`,
  );
}

export async function markNotificationRead(id: string): Promise<AppNotification> {
  return apiFetch<AppNotification>(`/notifications/${id}/read`, { method: "POST" });
}

// -- Preferences ----------------------------------------------------------

export async function listPreferences(): Promise<Preference[]> {
  return apiFetch<Preference[]>("/preferences");
}

export async function setPreference(
  key: string,
  value: Record<string, unknown>,
  category?: string,
): Promise<Preference> {
  return apiFetch<Preference>(`/preferences/${key}`, {
    method: "PUT",
    body: JSON.stringify({ value, category }),
  });
}

// -- Draft replies --------------------------------------------------------

export async function listDraftReplies(status?: string): Promise<DraftReply[]> {
  return apiFetch<DraftReply[]>(`/draft-replies${queryString({ status })}`);
}

export interface DraftReplyEditPayload {
  subject?: string;
  body_text?: string;
  body_html?: string;
}

export async function editDraftReply(
  id: string,
  payload: DraftReplyEditPayload,
): Promise<DraftReply> {
  return apiFetch<DraftReply>(`/draft-replies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function approveDraftReply(id: string): Promise<DraftReply> {
  return apiFetch<DraftReply>(`/draft-replies/${id}/approve`, { method: "POST" });
}

export async function discardDraftReply(id: string): Promise<DraftReply> {
  return apiFetch<DraftReply>(`/draft-replies/${id}/discard`, { method: "POST" });
}

export async function regenerateDraftReply(
  id: string,
  tone?: DraftReplyTone,
): Promise<DraftReply> {
  return apiFetch<DraftReply>(`/draft-replies/${id}/regenerate`, {
    method: "POST",
    body: JSON.stringify(tone ? { tone } : {}),
  });
}
