// Mirrors the Pydantic response schemas in the backend (see
// `backend/app/schemas/*.py`). Kept hand-written rather than generated --
// the surface is small and stable enough that a codegen step would add more
// ceremony than it saves.

export type EmailCategory =
  | "action_required"
  | "meeting_request"
  | "fyi"
  | "newsletter"
  | "personal"
  | "spam"
  | "other";

export const EMAIL_CATEGORIES: EmailCategory[] = [
  "action_required",
  "meeting_request",
  "fyi",
  "newsletter",
  "personal",
  "spam",
  "other",
];

export type TaskStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";

export type DraftReplyStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "sent"
  | "discarded";

export type DraftReplyTone =
  | "professional"
  | "friendly"
  | "formal"
  | "executive"
  | "short"
  | "detailed"
  | "apology"
  | "thank_you"
  | "follow_up"
  | "negotiation"
  | "clarification";

export const DRAFT_REPLY_TONES: DraftReplyTone[] = [
  "professional",
  "friendly",
  "formal",
  "executive",
  "short",
  "detailed",
  "apology",
  "thank_you",
  "follow_up",
  "negotiation",
  "clarification",
];

export interface UserProfile {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  picture_url: string;
}

export interface EmailSummary {
  id: string;
  subject: string;
  snippet: string;
  from_address: string;
  received_at: string;
  is_read: boolean;
  is_starred: boolean;
  category: EmailCategory | null;
  priority_score: number | null;
  has_deadline: boolean;
  deadline_at: string | null;
}

export interface EmailFull extends EmailSummary {
  tenant_id: string;
  user_id: string;
  gmail_message_id: string;
  gmail_thread_id: string;
  to_addresses: string;
  cc_addresses: string;
  body_text: string | null;
  body_html: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface Task {
  id: string;
  tenant_id: string;
  user_id: string;
  email_id: string | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  created_by: "user" | "ai";
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface CalendarEvent {
  id: string;
  tenant_id: string;
  user_id: string;
  email_id: string | null;
  google_event_id: string | null;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  status: "confirmed" | "tentative" | "cancelled";
  attendees: unknown[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface AppNotification {
  id: string;
  tenant_id: string;
  user_id: string;
  type: string;
  title: string;
  body: string;
  is_read: boolean;
  read_at: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface DraftReply {
  id: string;
  tenant_id: string;
  user_id: string;
  email_id: string;
  subject: string;
  body_text: string;
  body_html: string | null;
  status: DraftReplyStatus;
  generated_by: "ai" | "user";
  tone: DraftReplyTone | null;
  reasoning: string | null;
  confidence: number | null;
  gmail_draft_id: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface Preference {
  id: string;
  tenant_id: string;
  user_id: string;
  key: string;
  value: Record<string, unknown>;
  category: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface PriorityHeatmapCell {
  category: string;
  priority_band: string;
  count: number;
}

export interface DashboardSummary {
  total_emails: number;
  unread_emails: number;
  urgent_emails: number;
  upcoming_deadlines: number;
  pending_tasks: number;
  pending_drafts: number;
  unread_notifications: number;
  category_counts: Record<string, number>;
  priority_heatmap: PriorityHeatmapCell[];
}
