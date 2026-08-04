# User Guide

A guide to using the AI Executive Email Assistant day to day. For how it's
built, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for running it yourself,
see [`DEPLOYMENT.md`](DEPLOYMENT.md).

## 1. Signing in

Open the app and click **Sign in with Google**. You'll be sent to Google's
consent screen and asked to grant read access to your Gmail (and Calendar,
for meeting suggestions) — the assistant never requests permission to send
email on your behalf; it drafts replies for you to send yourself, or
approve.

If the app can't reach the backend at all (rather than you simply not being
signed in yet), the sign-in screen tells you that explicitly instead of
just showing a generic sign-in prompt.

## 2. The Overview dashboard

Your home screen after signing in. At a glance:

- **Stat tiles**: total emails, unread, urgent, upcoming deadlines, pending
  tasks, pending drafts, unread notifications.
- **Category chart** and **priority heatmap**: how your recent mail breaks
  down by AI-assigned category and urgency.
- **Urgent emails** and **upcoming deadlines** cards: your most
  time-sensitive items, without needing to go into the full inbox.

Every number here refreshes from the same triage pipeline that runs on new
mail automatically in the background — you don't need to do anything to
populate it beyond having connected Gmail.

## 3. Inbox

Every email the assistant has processed, in one filterable list:

- **Category filter** — narrow to one AI-assigned category: Action required,
  Meeting request, FYI, Newsletter, Personal, Spam, or Other.
- **Sort** — Recent (newest first) or Priority (most urgent first).
- Click any email to open it: subject, sender, full body, and the AI's
  classification.
- **Mark read** and **star** toggle from the inbox or the detail view.

A freshly-connected mailbox won't show anything until the background poller
picks up new mail (typically within a couple of minutes — see
[`ARCHITECTURE.md` §8](ARCHITECTURE.md#8-background-jobs) if you're curious
about the exact cadence) and runs it through triage. Existing mail already
in your inbox at connection time is not retroactively imported — only mail
that arrives after you connect is ingested.

## 4. Draft replies

When the assistant decides a reply is warranted, it drafts one — in your
configured default tone (see §7) unless the email calls for something
different — and it shows up on the **Draft Replies** page, never sent
automatically. From there, for each draft:

- **Edit** the subject/body directly before doing anything else with it.
- **Regenerate** with a different tone (11 available: Professional,
  Friendly, Formal, Executive, Short, Detailed, Apology, Thank you, Follow
  up, Negotiation, Clarification) if the first attempt isn't right.
- **Approve** or **Discard**.

Nothing the assistant drafts is ever sent without you explicitly approving
it here.

## 5. Tasks

Action items and deadlines the assistant extracted from your email, on the
**Tasks** page:

- Change a task's **priority** (Low/Medium/High/Urgent) inline.
- **Complete** a task when you're done with it.

## 6. Calendar

Meeting requests and other calendar-worthy items the assistant spotted in
your email, grouped by day on the **Calendar** page, pulled from your
actual Google Calendar once synced.

## 7. Notifications

The **Notifications** page lists everything the assistant has surfaced —
draft-ready alerts, high-priority-email alerts, reminders — with a filter
for unread-only, and a per-notification "mark read" action.

## 8. Settings

- **Account** — your connected Google profile, and **Sign out**, which ends
  your app session *and* best-effort revokes the app's Google grant
  (reconnect any time by signing in again — you'll be asked to re-consent).
- **Appearance** — Light, Dark, or follow System theme.
- **Notifications** — toggle whether urgent emails and upcoming deadlines
  generate an in-app notification.
- **Draft replies** — set your default reply tone (used unless a specific
  email calls for something else, e.g. an apology-toned reply to a
  complaint).

### 8.1 External notification channels (Slack, email, etc.)

The assistant can also deliver notifications to Slack, Discord, Telegram,
WhatsApp, email (SMTP), a generic webhook, and desktop/mobile push — but
configuring a destination for any of these is **not yet available from the
Settings page**; it's reachable via the API directly
(`PUT /api/v1/notification-channels/{channel_type}`, documented at `/docs`)
until a Settings UI for it ships. If you need this today, see the API docs
or ask your administrator.

## 9. Data & privacy

- Your Gmail/Calendar OAuth tokens are encrypted at rest and never exposed
  to the browser — the frontend only ever holds a session cookie.
- **Sign out** (§8) both ends your session and best-effort revokes the
  app's Google grant. If that revocation call itself fails (e.g. Google is
  briefly unreachable), your session still ends locally; double-check via
  your [Google Account permissions page](https://myaccount.google.com/permissions)
  if you want certainty that access was revoked.
- See [`ARCHITECTURE.md` §12](ARCHITECTURE.md#12-security) for the full
  security model if you want the technical detail behind these guarantees.
