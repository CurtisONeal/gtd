"""Markdown export.

SQLite stays the source of truth; these files are a readable, greppable,
git-versionable mirror. Useful for reading lists at a terminal, diffing what
changed week over week, or feeding a list into an agent for review — without
anything else needing to speak SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import STATE_LABELS, ItemState
from .store import Store

# Lists worth mirroring to disk. Trash is deliberately excluded.
EXPORTED_STATES = (
    ItemState.INBOX,
    ItemState.NEXT_ACTION,
    ItemState.WAITING_FOR,
    ItemState.SOMEDAY,
    ItemState.REFERENCE,
)


def _annotations(row: sqlite3.Row) -> list[str]:
    """The metadata worth seeing inline, in a stable order."""
    keys = row.keys()
    bits: list[str] = []

    if "context_name" in keys and row["context_name"]:
        bits.append(str(row["context_name"]))
    if "project_name" in keys and row["project_name"]:
        bits.append(f"↳ {row['project_name']}")
    if "area_name" in keys and row["area_name"]:
        emoji = row["area_emoji"] if "area_emoji" in keys and row["area_emoji"] else ""
        bits.append(f"{emoji} {row['area_name']}".strip())
    if row["waiting_on"]:
        bits.append(f"waiting on {row['waiting_on']}")
    if "blocked_by_titles" in keys and row["blocked_by_titles"]:
        bits.append(f"blocked by {row['blocked_by_titles']}")
    if row["energy"]:
        bits.append(f"energy: {row['energy']}")
    if row["time_estimate_min"]:
        bits.append(f"{row['time_estimate_min']}m")
    if row["priority"]:
        bits.append(f"P{row['priority']}")
    if row["due_date"]:
        overdue = row["due_date"] < date.today().isoformat()
        bits.append(f"due {row['due_date']}{' ⚠ OVERDUE' if overdue else ''}")
    if row["defer_until"] and row["defer_until"] > date.today().isoformat():
        bits.append(f"deferred until {row['defer_until']}")
    return bits


def render_list(state: str, rows: list[sqlite3.Row]) -> str:
    label = STATE_LABELS.get(str(state), str(state))
    lines = [
        f"# {label}",
        "",
        f"_{len(rows)} item{'s' if len(rows) != 1 else ''} — generated "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        # Machine-readable alongside the human line above. An agent reading a
        # copy of this file (the Obsidian mirror, say) cannot tell from the
        # content alone whether it is current — and a brief built on a stale
        # export reports yesterday's list with full confidence. This lets it
        # compute the age and refuse, rather than guess.
        f"<!-- generated_at: {datetime.now().astimezone().isoformat(timespec='seconds')} -->",
        "",
    ]
    if not rows:
        lines.append("_Nothing here._")
        lines.append("")
        return "\n".join(lines)

    for row in rows:
        annotations = _annotations(row)
        suffix = f"  _({' · '.join(annotations)})_" if annotations else ""
        lines.append(f"- [ ] {row['title']}{suffix}")
        if row["notes"]:
            for note_line in str(row["notes"]).splitlines():
                lines.append(f"      {note_line}")
    lines.append("")
    return "\n".join(lines)


def render_projects(rows: list[sqlite3.Row]) -> str:
    lines = [
        "# Projects",
        "",
        f"_{len(rows)} active — generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        f"<!-- generated_at: {datetime.now().astimezone().isoformat(timespec='seconds')} -->",
        "",
    ]
    if not rows:
        lines.append("_No active projects._")
        lines.append("")
        return "\n".join(lines)

    for row in rows:
        area = ""
        if "area_name" in row.keys() and row["area_name"]:
            emoji = row["area_emoji"] if row["area_emoji"] else ""
            area = f" — {emoji} {row['area_name']}".rstrip()
        lines.append(f"## {row['name']}{area}")
        lines.append("")
        if row["outcome"]:
            lines.append(f"**Desired outcome:** {row['outcome']}")
            lines.append("")

        open_actions = row["open_actions"] if "open_actions" in row.keys() else 0
        if open_actions:
            lines.append(f"{open_actions} open next action{'s' if open_actions != 1 else ''}")
        else:
            # The single most useful signal a weekly review can surface.
            lines.append("⚠ **Stalled** — no next action defined")
        lines.append("")
        if row["notes"]:
            lines.append(str(row["notes"]))
            lines.append("")
    return "\n".join(lines)


def export_all(store: Store, export_dir: Path) -> list[Path]:
    """Write every list plus projects. Returns the paths written."""
    export_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    counts: dict[str, int] = {}

    for state in EXPORTED_STATES:
        rows = store.list_items(state, include_deferred=True)
        path = export_dir / f"{state}.md"
        path.write_text(render_list(state, rows), encoding="utf-8")
        written.append(path)
        counts[str(state)] = len(rows)

    projects_path = export_dir / "projects.md"
    projects_path.write_text(render_projects(store.list_projects()), encoding="utf-8")
    written.append(projects_path)

    # One file to check freshness against, so a reader does not have to parse
    # six. Written LAST: if the export dies partway, the manifest is absent or
    # older than the files, and a reader that trusts it fails closed rather
    # than reporting a half-written set as current.
    manifest = export_dir / "_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "files": sorted(p.name for p in written),
                "counts": counts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(manifest)

    return written
