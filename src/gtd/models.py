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
    BOOK = "book"                 # ordered, ranked within a category — see /books
    CHECKLIST = "checklist"       # a member of a checklist, ranked within it
    TECH_PROJECT = "tech_project" # ordered dump list, no project ceremony
    DONE = "done"
    TRASHED = "trashed"           # soft delete, recoverable

    @classmethod
    def user_lists(cls) -> tuple["ItemState", ...]:
        """States a user browses as a generic list page (excludes done/trashed).

        BOOK is deliberately absent: it is ordered and grouped, so it has its own
        page rather than rendering through the generic list template.
        """
        return (cls.INBOX, cls.NEXT_ACTION, cls.WAITING_FOR, cls.SOMEDAY, cls.REFERENCE)


class BookCategory(StrEnum):
    """A book taxonomy, deliberately NOT an area of focus.

    Areas are life areas (Personal, Work, Health). Mixing a reading taxonomy
    into them would muddy both — a technology book is not a life area, and
    "Health" is not a shelf.
    """

    FICTION = "fiction"
    GRAPHIC_NOVEL = "graphic_novel"
    NONFICTION = "nonfiction"
    TECHNOLOGY = "technology"


BOOK_CATEGORY_LABELS: dict[str, str] = {
    BookCategory.FICTION: "Fiction",
    BookCategory.GRAPHIC_NOVEL: "Graphic Novels",
    BookCategory.NONFICTION: "General Non-fiction",
    BookCategory.TECHNOLOGY: "Technology",
}


# Progress as pickable buckets, not a free number. The point is an estimate —
# a text box invites fiddling with a figure nobody can actually know. Thirds are
# included because they get used in practice.
PERCENT_BUCKETS: tuple[int, ...] = (0, 25, 33, 50, 66, 75, 100)


class Energy(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChecklistStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"


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
    ItemState.BOOK: "Books",
    ItemState.CHECKLIST: "Checklist",
    ItemState.TECH_PROJECT: "Technology Projects",
    ItemState.DONE: "Done",
    ItemState.TRASHED: "Trash",
}
