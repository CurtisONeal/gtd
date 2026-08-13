"""Domain types.

The central idea: a GTD item is one row that *moves between lists* by changing
its `state`. Inbox, next actions, waiting-for, someday/maybe and reference are
not separate stores — they are states. That makes every "move" a single column
update instead of a copy-and-delete across two tables, which is where the
original gtd-flow design leaked (completing wrote to an archive sheet, and
un-completing had to find and delete that row again to stay consistent).
"""

from __future__ import annotations

from enum import StrEnum


class ItemState(StrEnum):
    """Every GTD list, as a state of the single items table."""

    INBOX = "inbox"           # captured, not yet clarified
    NEXT_ACTION = "next_action"
    WAITING_FOR = "waiting_for"   # delegated — tracked by `waiting_on`
    SOMEDAY = "someday"           # incubated, reviewed periodically
    REFERENCE = "reference"       # not actionable, worth keeping
    DONE = "done"
    TRASHED = "trashed"           # soft delete, recoverable

    @classmethod
    def user_lists(cls) -> tuple["ItemState", ...]:
        """States a user browses as a list page (excludes done/trashed)."""
        return (cls.INBOX, cls.NEXT_ACTION, cls.WAITING_FOR, cls.SOMEDAY, cls.REFERENCE)


class Energy(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    DONE = "done"
    DROPPED = "dropped"


class Source(StrEnum):
    """Where a capture came from. Lets the later Discord/email capture surfaces
    be distinguished without schema changes."""

    WEB = "web"
    DISCORD = "discord"
    EMAIL = "email"
    API = "api"
    CLI = "cli"


# Time estimates as pickable buckets rather than a free number.
#
# GTD uses time as a *selection* criterion — "I have 20 minutes before the call,
# what fits?" — so rough buckets are more useful than precise minutes, and much
# faster to enter on a phone. (A `<input type=number min=1 step=5>` also steps
# 1, 6, 11, 16… off the minimum, which is where the odd values came from.)
TIME_ESTIMATES: tuple[tuple[int, str], ...] = (
    (2, "2 min"),
    (5, "5 min"),
    (10, "10 min"),
    (15, "15 min"),
    (30, "30 min"),
    (45, "45 min"),
    (60, "1 hour"),
    (90, "1.5 hours"),
    (120, "2 hours"),
    (240, "half a day"),
    (480, "a full day"),
)


# Human-facing labels for list pages.
STATE_LABELS: dict[str, str] = {
    ItemState.INBOX: "Inbox",
    ItemState.NEXT_ACTION: "Next Actions",
    ItemState.WAITING_FOR: "Waiting For",
    ItemState.SOMEDAY: "Someday / Maybe",
    ItemState.REFERENCE: "Reference",
    ItemState.DONE: "Done",
    ItemState.TRASHED: "Trash",
}
