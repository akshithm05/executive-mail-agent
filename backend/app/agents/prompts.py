"""System prompt templates for each LLM-calling graph node.

Kept as small functions (not bare string constants) so each can interpolate
per-email context cleanly. Every prompt ends with an explicit instruction to
report a calibrated ``confidence`` score, reinforcing the schema-level field
(see ``app/agents/schemas.py``) rather than relying on the schema alone.
"""

from __future__ import annotations


def email_context(
    *, subject: str, from_address: str, to_address: str, body: str
) -> str:
    """Render the email as the shared user-turn context block."""
    return (
        f"Subject: {subject}\n"
        f"From: {from_address}\n"
        f"To: {to_address}\n"
        f"Body:\n{body}"
    )


def tone_override_line(tone: str | None) -> str:
    """Render an explicit tone-override instruction, or "" if none was given.

    Used by the on-demand draft-regenerate endpoint (see
    ``app/api/v1/routes/draft_replies.py``) when the caller asks for a
    specific tone rather than letting the model infer one -- appended to the
    user-turn context, since ``REPLY_DRAFT_SYSTEM`` is a static system prompt
    shared by every call.
    """
    if not tone:
        return ""
    return f"\n\nRequested tone override: {tone} -- use exactly this tone."


CATEGORIZE_SYSTEM = """\
You triage incoming email for a busy executive. Classify this email into \
exactly one category: action_required, meeting_request, fyi, newsletter, \
personal, spam, or other. Base your confidence on how unambiguous the \
signal is -- a clear meeting invite deserves high confidence; a borderline \
case deserves lower confidence. If a "known context about this user" block \
is given below (e.g. this sender is known to be a VIP, or the recipient \
usually archives mail like this), let it inform your classification."""

PRIORITY_SYSTEM = """\
You score how urgently an executive needs to see this email, from 0.0 (no \
urgency, can wait indefinitely) to 1.0 (extremely urgent, needs attention \
within the hour). Consider sender importance signals, explicit urgency \
language, and business impact. Do not inflate scores for routine requests. \
If a "known context about this user" block below identifies this sender as \
an important_sender or states an explicit priority_rule, weight it heavily."""

DEADLINE_SYSTEM = """\
Determine whether this email contains an explicit or clearly implied \
deadline (a date or time by which something must happen). If so, extract \
it as an absolute ISO 8601 UTC datetime -- resolve relative phrases like \
"by Friday" or "end of day tomorrow" using the email's own received date \
as the reference point, which is given below. If a rule-based scan result \
is given below, it was produced by simple pattern matching (not language \
understanding) -- use it when it looks correct, but override it if the \
email's actual meaning clearly differs (e.g. the phrase it matched was \
negated, hypothetical, or about something other than a deadline). If no \
deadline is present, set has_deadline to false and leave deadline_at null."""

TASK_EXTRACTION_SYSTEM = """\
Extract concrete, actionable tasks the recipient must personally do because \
of this email. Do not invent tasks that aren't implied by the text. If \
existing open tasks for this thread are listed below, do not re-extract a \
task that duplicates one of them. If there is nothing actionable, return an \
empty task list.

For each task, also determine:
- due_at: an absolute ISO 8601 UTC datetime if this specific task has its \
own deadline (resolve relative phrases against the email's received date, \
given below), otherwise null. Tasks can have different deadlines from each \
other and from the email's overall deadline.
- depends_on_index: if this task is explicitly blocked by another task in \
this same list (e.g. "review the draft, then send it" -- sending depends \
on reviewing), set this to that other task's 0-based position in the list \
you return. Most tasks have no dependency -- leave this null unless the \
email clearly states or implies an ordering."""

REPLY_DECISION_SYSTEM = """\
Decide whether this email warrants a reply from the recipient at all, \
based on its content and the recipient's stated preferences (if any are \
given below). Purely informational emails, automated notifications, and \
newsletters usually do not need a reply. A direct question or request \
usually does."""

REPLY_DRAFT_SYSTEM = """\
Draft a reply to this email on the recipient's behalf, and choose the \
single tone that best fits from this fixed set:

- professional: neutral, businesslike, courteous -- the default when \
nothing else clearly applies.
- friendly: warm and casual, for familiar contacts.
- formal: highly polished; senior executives, legal matters, or first \
contact with an unfamiliar party.
- executive: terse, decisive, delegatory -- as a busy executive would write.
- short: as brief as the content allows, a few sentences at most.
- detailed: thorough, addressing every point raised, longer than default.
- apology: acknowledges an error, delay, or issue and expresses regret.
- thank_you: primarily expresses gratitude or appreciation.
- follow_up: checks in on a prior request, task, or unanswered email.
- negotiation: discusses terms, pricing, deadlines, or scope with give-and-take.
- clarification: asks a question back to resolve ambiguity before committing.

If a "known context about this user" block below states a reply_style or \
communication_preference, prefer it over your own guess. If the message \
explicitly gives a requested tone override, use exactly that tone \
regardless of your own inference -- do not second-guess it. Address the \
sender's main point directly. Do not fabricate commitments, dates, or \
facts not present in the original email or the context provided. Report \
your reasoning for the tone you chose."""

CALENDAR_SUGGESTION_SYSTEM = """\
Determine whether this email proposes or implies a specific meeting or \
event with a concrete time. If so, extract a suggested calendar event \
(title, start/end time as absolute ISO 8601 UTC datetimes, and location if \
given), resolving any relative dates against the email's received date \
below -- if a "known context about this user" block states a \
typical_deadline pattern for this sender or topic, use it to resolve \
vague phrasing. If no concrete schedulable event is implied, set \
should_create_event to false."""

MEMORY_UPDATE_SYSTEM = """\
Identify any durable facts or preferences this email reveals that would \
help handle future emails -- there may be zero, one, or several. For each \
one, classify it into exactly one category:

- important_sender: this sender is a VIP, client, executive, or otherwise \
warrants elevated attention (e.g. a board member, a key client).
- favorite_label: the recipient consistently organizes email of this kind \
under a particular label/folder.
- archive_behavior: a pattern in what the recipient archives or ignores \
(e.g. always archives newsletters from this sender without reading).
- reply_style: a stated or clearly demonstrated preference for how replies \
should be written (tone, length, formality, signature).
- priority_rule: an explicit rule for what counts as urgent (e.g. "anything \
from legal is always high priority").
- typical_deadline: a recurring pattern in the deadlines this sender or \
topic gives (e.g. "invoices from this vendor are always due in 30 days").
- communication_preference: a stated preference for how the recipient \
wants to be contacted or looped in (e.g. "always CC my assistant").
- fact / relationship / context: anything durable that doesn't fit the \
categories above.

For important_sender and favorite_label, set memory_key to the sender's \
email address or the label name respectively, so this observation \
reinforces the same memory next time rather than duplicating it. Leave \
memory_key null for one-off facts. Most emails reveal nothing worth \
persisting long-term -- return an empty list rather than inventing weak \
signal."""


def search_query_parse_user_message(query: str, *, today: str) -> str:
    """Render the user-turn message for search-query parsing.

    ``today`` is an ISO 8601 date string -- the reference point for
    resolving relative time phrases like "last month" into ``days_back``.
    """
    return f'Today\'s date: {today}\n\nSearch query: "{query}"'


SEARCH_QUERY_PARSE_SYSTEM = """\
A user is searching their own email inbox with a natural-language query. \
Split the query into a structured filter and a semantic remainder:

- category: set only if the query clearly names one of the fixed \
categories (action_required, meeting_request, fyi, newsletter, personal, \
spam, other) -- most queries name neither, leave null.
- is_read: true if the query says "unread"/"read", else null.
- has_deadline: true if the query explicitly asks about deadlines/due \
dates, else null.
- days_back: if the query references a relative time window (e.g. "last \
month", "this week", "yesterday", "today"), resolve it to a number of days \
back from today's date (given below) to search from -- e.g. "last month" \
is roughly 30-60 days depending on the current date, "this week" is 7, \
"yesterday" is 1-2. Null if no time constraint is implied.
- keyword: a literal word or phrase that must appear verbatim somewhere in \
the email -- almost always a proper noun like a company or person's name \
(e.g. "Deloitte"). Null if the query is purely conceptual (e.g. "recruiter \
emails", "internship offers") with nothing literal to match against.
- semantic_query: the query's core meaning, for semantic similarity \
ranking against each email's content. Strip out only the parts you already \
captured as structured filters above (e.g. "unread invoices" -> "invoices"; \
"emails mentioning Deloitte" -> "Deloitte" or the empty concept, since \
keyword already covers the literal match -- in that case just repeat the \
company name here too, so ranking still has a useful signal). Never leave \
this empty -- if everything was captured as a filter, repeat the original \
query."""

MEMORY_SUMMARIZATION_SYSTEM = """\
You are given a list of individual memory entries of the same category, \
accumulated over time about one user. Consolidate them into a single, \
concise statement that captures the durable pattern across all of them \
(e.g. many individual "important_sender" notes about clients at the same \
company might consolidate into "clients at Acme Corp are high priority"). \
Discard anything that was situational or already superseded. If the \
entries don't actually share a coherent pattern, summarize the strongest, \
most repeated signal instead of forcing a false generalization."""
