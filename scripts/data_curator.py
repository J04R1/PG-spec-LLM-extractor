#!/usr/bin/env python3
"""
Data Curation TUI — OpenPG spec database.

Interactive rich terminal UI for reviewing and fixing data gaps, marking fields
as verified or not_available, and delegating bulk research to an AI agent.

Usage:
  Interactive TUI (default):
    python3 scripts/data_curator.py --db output/ozone.db

  Export pending gaps as a task file for an AI agent session:
    python3 scripts/data_curator.py --db output/ozone.db \\
      --export-tasks output/tasks/cert_tasks.json [--slug SLUG] [--field FIELD]

  Review and apply an AI-researched patch:
    python3 scripts/data_curator.py --db output/ozone.db \\
      --apply-patch output/tasks/cert_patch.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ── Field configuration ──────────────────────────────────────────────────────────

# Fields that must be populated (or marked not_available) for status = "complete"
REQUIRED_FIELDS: dict[str, list[str]] = {
    "models": ["category", "year_released", "cell_count"],
    "size_variants": ["flat_area_m2", "flat_span_m", "proj_area_m2", "ptv_min_kg", "ptv_max_kg"],
    "certifications": ["standard", "classification"],
}

# Fields that must be populated for status = "verified"
OPTIONAL_FIELDS: dict[str, list[str]] = {
    "models": ["year_discontinued"],
    "size_variants": ["wing_weight_kg", "proj_span_m", "proj_aspect_ratio", "line_length_m"],
    "certifications": ["test_lab", "report_url", "test_date", "report_number"],
}

ALLOWED_TABLES: frozenset[str] = frozenset(REQUIRED_FIELDS.keys())

ALL_KNOWN_FIELDS: frozenset[str] = frozenset(
    f
    for table in ALLOWED_TABLES
    for f in REQUIRED_FIELDS[table] + OPTIONAL_FIELDS[table]
)

# Human-readable metadata per field (desc, range, optional numeric bounds)
FIELD_META: dict[str, dict[str, Any]] = {
    "category":           {"desc": "Wing category", "range": "paraglider|tandem|miniwing|single_skin|acro|speedwing|paramotor"},
    "year_released":      {"desc": "Year first released", "range": "1990–2030", "min": 1990, "max": 2030, "int": True},
    "year_discontinued":  {"desc": "Year production ended", "range": "1990–2030", "min": 1990, "max": 2030, "int": True},
    "cell_count":         {"desc": "Number of cells", "range": "15–120", "min": 15, "max": 120, "int": True},
    "flat_area_m2":       {"desc": "Flat area", "range": "10–50 m²", "min": 10.0, "max": 50.0},
    "flat_span_m":        {"desc": "Flat span", "range": "6–22 m", "min": 6.0, "max": 22.0},
    "proj_area_m2":       {"desc": "Projected area", "range": "8–45 m²", "min": 8.0, "max": 45.0},
    "proj_span_m":        {"desc": "Projected span", "range": "5–18 m", "min": 5.0, "max": 18.0},
    "flat_aspect_ratio":  {"desc": "Flat aspect ratio", "range": "2.5–8.5", "min": 2.5, "max": 8.5},
    "proj_aspect_ratio":  {"desc": "Projected aspect ratio", "range": "2.0–8.0", "min": 2.0, "max": 8.0},
    "wing_weight_kg":     {"desc": "Wing weight", "range": "1–15 kg", "min": 1.0, "max": 15.0},
    "ptv_min_kg":         {"desc": "Min all-up weight", "range": "30–250 kg", "min": 30.0, "max": 250.0},
    "ptv_max_kg":         {"desc": "Max all-up weight", "range": "30–250 kg", "min": 30.0, "max": 250.0},
    "line_length_m":      {"desc": "Free-flying line length", "range": "5–15 m", "min": 5.0, "max": 15.0},
    "standard":           {"desc": "Certification standard", "range": "EN|LTF|AFNOR|DGAC|CCC|other"},
    "classification":     {"desc": "Certification class", "range": "A|B|C|D|1|2|3|CCC"},
    "test_lab":           {"desc": "Testing laboratory", "range": "text (e.g. SHV, DHV, ACPUL)"},
    "report_number":      {"desc": "Test report number", "range": "text"},
    "report_url":         {"desc": "Test report PDF link", "range": "URL"},
    "test_date":          {"desc": "Date of test", "range": "YYYY-MM-DD"},
}

# Search hints and pre-populated URLs for task export
_DHV = "https://www.dhv.de/db2/module/geraet/suche/"
_OZONE_GLIDERS = "https://flyozone.com/paragliders/products/gliders"

SEARCH_HINTS: dict[str, str] = {
    # size_variants
    "ptv_min_kg": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find the row labelled 'Certified Weight Range', 'In-Flight Weight Range', "
        "'Pilot Weight Range', or 'Take-Off Weight Range'. "
        "The value is a range like '75-95' — set ptv_min_kg to the lower number (75)."
    ),
    "ptv_max_kg": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find the row labelled 'Certified Weight Range', 'In-Flight Weight Range', "
        "'Pilot Weight Range', or 'Take-Off Weight Range'. "
        "The value is a range like '75-95' — set ptv_max_kg to the upper number (95)."
    ),
    "wing_weight_kg": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find the row labelled 'Glider Weight', 'Wing Weight', or 'Weight'. "
        "Return the numeric value in kg for the correct size. "
        "If absent from the manufacturer site, check the fredvol paraglider dataset "
        "(https://github.com/fredvol/Paraglider_specs_studies) and note that source."
    ),
    "proj_area_m2": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Projected Area' in m\u00b2 for the correct size. "
        "Note: some older or simpler models do not publish projected geometry — "
        "if the field is absent from the spec table, leave value null."
    ),
    "proj_span_m": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Projected Span' in metres for the correct size. "
        "Note: some older models do not publish this — if absent, leave value null."
    ),
    "proj_aspect_ratio": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Projected Aspect Ratio' for the correct size. "
        "Note: some older models do not publish this — if absent, leave value null."
    ),
    "flat_area_m2": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Flat Area' in m\u00b2 for the correct size."
    ),
    "flat_span_m": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Flat Span' in metres for the correct size."
    ),
    "line_length_m": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Line Length' or 'Free Flying Line Length' in metres for the correct size. "
        "This field is often absent on older models — if missing, leave value null."
    ),
    # models
    "year_discontinued": (
        "Find the year {model} was discontinued. Check the manufacturer archive page or "
        "the Internet Archive Wayback Machine (https://web.archive.org). "
        "Use the last year the model appeared as current in manufacturer catalogues."
    ),
    "cell_count": (
        "Look up the spec table for {model} on the manufacturer website. "
        "Find 'Number of Cells' or 'Cells'. Return the integer value."
    ),
    # certifications
    "standard": (
        "Find the certification standard for {model}. "
        "Allowed values: EN, LTF, AFNOR, DGAC, CCC, other. "
        "Check the manufacturer page or the DHV Ger\u00e4teportal."
    ),
    "classification": (
        "Find the certification class for {model}. "
        "Allowed values: A, B, C, D (for EN/LTF); CCC. "
        "Check the spec table on the manufacturer page or the DHV Ger\u00e4teportal."
    ),
    "test_lab": (
        "Search the DHV Ger\u00e4teportal for {model} to find the testing laboratory name. "
        "Common values: SHV, DHV, ACPUL, DGAC. "
        "Return the name exactly as listed in the DHV database."
    ),
    "report_url": (
        "Search the DHV Ger\u00e4teportal for {model} to find the PDF link to the test report. "
        "Return the direct URL to the report document."
    ),
    "test_date": (
        "Search the DHV Ger\u00e4teportal for {model} to find the certification test date. "
        "Return in YYYY-MM-DD format."
    ),
    "report_number": (
        "Search the DHV Ger\u00e4teportal for {model} to find the official test report number. "
        "Return the identifier exactly as shown."
    ),
}

SEARCH_URLS: dict[str, list[str]] = {
    "test_lab":       [_DHV],
    "report_url":     [_DHV],
    "test_date":      [_DHV],
    "report_number":  [_DHV],
    "standard":       [_DHV],
    "classification": [_DHV],
    "ptv_min_kg":     [_OZONE_GLIDERS],
    "ptv_max_kg":     [_OZONE_GLIDERS],
    "wing_weight_kg": [_OZONE_GLIDERS],
}

# Task export priority:
#   high  — always included in --export-tasks by default (primary data gaps)
#   low   — only included when --all-fields is passed (cert details, rare geometry)
# Unlisted fields default to "high".
FIELD_TASK_PRIORITY: dict[str, str] = {
    # cert details: require a dedicated DHV search session — skip by default
    "test_lab":        "low",
    "report_url":      "low",
    "test_date":       "low",
    "report_number":   "low",
    # projected geometry: often absent on older pages — lower urgency
    "proj_area_m2":    "low",
    "proj_span_m":     "low",
    "proj_aspect_ratio": "low",
    "line_length_m":   "low",
}

STATUS_COLOR = {"incomplete": "red", "complete": "yellow", "verified": "cyan"}

# ── Database helpers ─────────────────────────────────────────────────────────────


def open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_field_verifications(conn)
    return conn


def _ensure_field_verifications(conn: sqlite3.Connection) -> None:
    """Create field_verifications table if it does not exist (idempotent)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS field_verifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name   TEXT    NOT NULL,
            record_id    INTEGER NOT NULL,
            field_name   TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'pending'
                         CHECK(status IN ('verified', 'not_available', 'pending_approval')),
            source_url   TEXT,
            verified_at  TEXT,
            verified_by  TEXT    CHECK(verified_by IN ('user', 'agent')),
            notes        TEXT,
            UNIQUE(table_name, record_id, field_name)
        )
    """)
    conn.commit()


def get_verifications(
    conn: sqlite3.Connection,
    table_name: str,
    record_id: int,
) -> dict[str, str]:
    """Return {field_name: status} for all verification records on a record."""
    rows = conn.execute(
        "SELECT field_name, status FROM field_verifications WHERE table_name = ? AND record_id = ?",
        (table_name, record_id),
    ).fetchall()
    return {r["field_name"]: r["status"] for r in rows}


def set_verification(
    conn: sqlite3.Connection,
    table_name: str,
    record_id: int,
    field_name: str,
    status: str,
    source_url: str | None = None,
    verified_by: str = "user",
    notes: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """INSERT INTO field_verifications
               (table_name, record_id, field_name, status, source_url,
                verified_at, verified_by, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(table_name, record_id, field_name)
               DO UPDATE SET status=excluded.status,
                             source_url=excluded.source_url,
                             verified_at=excluded.verified_at,
                             verified_by=excluded.verified_by,
                             notes=excluded.notes""",
        (table_name, record_id, field_name, status, source_url, now, verified_by, notes),
    )
    conn.commit()


# ── Completeness scoring ─────────────────────────────────────────────────────────


def _is_filled(row: sqlite3.Row, field: str, verifications: dict[str, str]) -> bool:
    """A field counts as filled if it has a value OR is marked not_available."""
    try:
        return row[field] is not None or verifications.get(field) == "not_available"
    except IndexError:
        return False


def compute_model_score(conn: sqlite3.Connection, model_id: int) -> dict:
    """
    Returns a score dict with keys:
      model_id, required_score (0..1), optional_score (0..1),
      status ("incomplete"|"complete"|"verified"), top_gaps (list[str])
    """
    model_row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    sv_rows = conn.execute(
        "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
    ).fetchall()

    req_total = req_filled = opt_total = opt_filled = 0
    gaps: list[tuple[int, str]] = []  # (0=required / 1=optional, field_name)

    def _tally(table: str, record_id: int, row: sqlite3.Row,
               req_fields: list[str], opt_fields: list[str]) -> None:
        nonlocal req_total, req_filled, opt_total, opt_filled
        verifs = get_verifications(conn, table, record_id)
        for f in req_fields:
            req_total += 1
            if _is_filled(row, f, verifs):
                req_filled += 1
            else:
                gaps.append((0, f))
        for f in opt_fields:
            opt_total += 1
            if _is_filled(row, f, verifs):
                opt_filled += 1
            else:
                gaps.append((1, f))

    _tally("models", model_id, model_row,
           REQUIRED_FIELDS["models"], OPTIONAL_FIELDS["models"])

    for sv in sv_rows:
        _tally("size_variants", sv["id"], sv,
               REQUIRED_FIELDS["size_variants"], OPTIONAL_FIELDS["size_variants"])

        cert_rows_sv = conn.execute(
            "SELECT * FROM certifications WHERE size_variant_id = ?", (sv["id"],)
        ).fetchall()
        if cert_rows_sv:
            for cert in cert_rows_sv:
                _tally("certifications", cert["id"], cert,
                       REQUIRED_FIELDS["certifications"], OPTIONAL_FIELDS["certifications"])
        else:
            # No cert records yet — every required cert field is a gap
            for f in REQUIRED_FIELDS["certifications"]:
                req_total += 1
                gaps.append((0, f))

    req_score = req_filled / req_total if req_total else 1.0
    opt_score = opt_filled / opt_total if opt_total else 1.0

    if req_score < 1.0:
        status = "incomplete"
    elif opt_score < 1.0:
        status = "complete"
    else:
        status = "verified"

    seen: set[str] = set()
    top_gaps: list[str] = []
    for _, label in sorted(gaps):
        if label not in seen:
            seen.add(label)
            top_gaps.append(label)
        if len(top_gaps) == 3:
            break

    return {
        "model_id": model_id,
        "required_score": req_score,
        "optional_score": opt_score,
        "status": status,
        "top_gaps": top_gaps,
    }


def compute_all_scores(
    conn: sqlite3.Connection,
    slug_filter: str | None = None,
) -> list[dict]:
    query = "SELECT id, name, slug FROM models"
    params: list = []
    if slug_filter:
        query += " WHERE slug LIKE ?"
        params.append(f"%{slug_filter}%")
    query += " ORDER BY name"
    rows = conn.execute(query, params).fetchall()

    scores = []
    for r in rows:
        s = compute_model_score(conn, r["id"])
        s["name"] = r["name"]
        s["slug"] = r["slug"]
        scores.append(s)

    priority = {"incomplete": 0, "complete": 1, "verified": 2}
    scores.sort(key=lambda x: (priority[x["status"]], x["required_score"], x["optional_score"]))
    return scores


# ── Screen rendering ─────────────────────────────────────────────────────────────


def _db_display_name(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]).name if row else "database"


def render_dashboard(
    console: Console,
    conn: sqlite3.Connection,
    slug_filter: str | None = None,
) -> list[dict]:
    scores = compute_all_scores(conn, slug_filter)

    n_total = len(scores)
    n_incomplete = sum(1 for s in scores if s["status"] == "incomplete")
    n_complete = sum(1 for s in scores if s["status"] == "complete")
    n_verified = sum(1 for s in scores if s["status"] == "verified")
    avg_req = sum(s["required_score"] for s in scores) / n_total if n_total else 0.0

    filter_note = f"  filter: [bold]{slug_filter}[/bold]" if slug_filter else ""
    header = (
        f"[bold]{_db_display_name(conn)}[/bold]{filter_note}  ·  {n_total} models  "
        f"·  avg req: [bold]{avg_req:.0%}[/bold]  "
        f"[red]incomplete: {n_incomplete}[/red]  "
        f"[yellow]complete: {n_complete}[/yellow]  "
        f"[cyan]verified: {n_verified}[/cyan]"
    )
    console.print(Panel(header, box=box.ROUNDED))

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Slug", min_width=30)
    tbl.add_column("Req%", justify="right", width=6)
    tbl.add_column("Opt%", justify="right", width=6)
    tbl.add_column("Status", width=12)
    tbl.add_column("Top gaps", style="dim")

    for i, s in enumerate(scores, 1):
        color = STATUS_COLOR[s["status"]]
        gaps_str = ", ".join(s["top_gaps"]) if s["top_gaps"] else "—"
        tbl.add_row(
            str(i),
            s["slug"],
            f"{s['required_score']:.0%}",
            f"{s['optional_score']:.0%}",
            f"[{color}]{s['status']}[/{color}]",
            gaps_str,
        )

    console.print(tbl)
    console.print(
        "\n[bold]Commands:[/bold]  "
        "[yellow]<number>[/yellow] open model  "
        "[yellow]f <text>[/yellow] filter by slug  "
        "[yellow]f[/yellow] clear filter  "
        "[yellow]r[/yellow] refresh  "
        "[yellow]q[/yellow] quit\n"
    )
    return scores


def render_model_detail(console: Console, conn: sqlite3.Connection, model_id: int) -> None:
    model = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    if not model:
        console.print("[red]Model not found.[/red]")
        return

    sv_rows = conn.execute(
        "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
    ).fetchall()
    cert_rows = []
    for sv in sv_rows:
        cert_rows.extend(
            conn.execute(
                "SELECT * FROM certifications WHERE size_variant_id = ?", (sv["id"],)
            ).fetchall()
        )

    year = model["year_released"] or "?"
    disc = f"–{model['year_discontinued']}" if model["year_discontinued"] else "–?"
    cells = model["cell_count"] or "?"
    title = (
        f"[bold]{model['name']}[/bold]  ·  {model['category']}  "
        f"·  {year}{disc}  ·  {cells} cells"
    )
    console.print(Panel(title, box=box.ROUNDED))

    # — MODEL FIELDS —
    model_verifs = get_verifications(conn, "models", model_id)
    tbl = Table(
        title="MODEL FIELDS", box=box.SIMPLE,
        show_header=True, header_style="bold dim",
    )
    tbl.add_column("Field", width=22)
    tbl.add_column("Value", width=22)
    tbl.add_column("V?", width=5)
    tbl.add_column("Range / allowed", style="dim")

    for f in REQUIRED_FIELDS["models"] + OPTIONAL_FIELDS["models"]:
        val = model[f]
        ver = model_verifs.get(f, "")
        meta = FIELD_META.get(f, {})
        req = f in REQUIRED_FIELDS["models"]

        if ver == "not_available":
            v_icon, val_str, style = "[dim]n/a[/dim]", "[dim]n/a[/dim]", "dim"
        elif ver == "verified":
            v_icon, val_str, style = "[green]✓[/green]", str(val), ""
        elif val is None and req:
            v_icon, val_str, style = "", "[red]—[/red]", "red"
        elif val is None:
            v_icon, val_str, style = "", "[yellow]—[/yellow]", "yellow"
        else:
            v_icon, val_str, style = "", str(val), ""

        tbl.add_row(f, val_str, v_icon, meta.get("range", ""), style=style)

    console.print(tbl)

    # — SIZE VARIANTS gap summary —
    if sv_rows:
        sv_tbl = Table(
            title=f"SIZE VARIANTS ({len(sv_rows)} sizes) — gap summary",
            box=box.SIMPLE, show_header=True, header_style="bold dim",
        )
        sv_tbl.add_column("Field", width=22)
        sv_tbl.add_column("Populated", width=20)
        sv_tbl.add_column("Status", width=10)

        for f in REQUIRED_FIELDS["size_variants"] + OPTIONAL_FIELDS["size_variants"]:
            req = f in REQUIRED_FIELDS["size_variants"]
            n_pop = n_na = 0
            for sv in sv_rows:
                v = get_verifications(conn, "size_variants", sv["id"])
                if sv[f] is not None:
                    n_pop += 1
                elif v.get(f) == "not_available":
                    n_na += 1
            total = len(sv_rows)
            pop_str = f"{n_pop + n_na}/{total}"
            if n_na:
                pop_str += f" ({n_na} n/a)"
            if n_pop + n_na == total:
                status_str, style = "[green]✓[/green]", ""
            elif req:
                status_str, style = "[red]missing[/red]", "red"
            else:
                status_str, style = "[yellow]gaps[/yellow]", "yellow"
            sv_tbl.add_row(f, pop_str, status_str, style=style)

        console.print(sv_tbl)

    # — CERTIFICATIONS gap summary —
    if cert_rows:
        cert_tbl = Table(
            title=f"CERTIFICATIONS ({len(cert_rows)} records) — gap summary",
            box=box.SIMPLE, show_header=True, header_style="bold dim",
        )
        cert_tbl.add_column("Field", width=22)
        cert_tbl.add_column("Populated", width=20)
        cert_tbl.add_column("Status", width=10)

        for f in REQUIRED_FIELDS["certifications"] + OPTIONAL_FIELDS["certifications"]:
            req = f in REQUIRED_FIELDS["certifications"]
            n_pop = n_na = 0
            for cert in cert_rows:
                v = get_verifications(conn, "certifications", cert["id"])
                if cert[f] is not None:
                    n_pop += 1
                elif v.get(f) == "not_available":
                    n_na += 1
            total = len(cert_rows)
            pop_str = f"{n_pop + n_na}/{total}"
            if n_na:
                pop_str += f" ({n_na} n/a)"
            if n_pop + n_na == total:
                status_str, style = "[green]✓[/green]", ""
            elif req:
                status_str, style = "[red]missing[/red]", "red"
            else:
                status_str, style = "[yellow]gaps[/yellow]", "yellow"
            cert_tbl.add_row(f, pop_str, status_str, style=style)

        console.print(cert_tbl)
    else:
        # Count how many sizes are missing certs entirely
        sizes_no_cert = sum(
            1 for sv in sv_rows
            if not conn.execute(
                "SELECT 1 FROM certifications WHERE size_variant_id = ?", (sv["id"],)
            ).fetchone()
        )
        if sizes_no_cert:
            console.print(
                f"[red]CERTIFICATIONS — no records for {sizes_no_cert}/{len(sv_rows)} sizes[/red]\n"
                f"  [red]→ Type [bold]standard[/bold] to add certification data for each size[/red]\n"
                f"    [dim](EN / LTF / CCC / other — will also prompt for classification)[/dim]"
            )
        else:
            console.print("[dim]No certifications.[/dim]")

    # ── Priority banner ────────────────────────────────────────────────────
    score = compute_model_score(conn, model_id)
    if score["top_gaps"]:
        first_req_gap = next(
            (f for f in score["top_gaps"] if f in
             REQUIRED_FIELDS["models"] + REQUIRED_FIELDS["size_variants"] + REQUIRED_FIELDS["certifications"]),
            None,
        )
        first_opt_gap = next(
            (f for f in score["top_gaps"] if f in
             OPTIONAL_FIELDS["models"] + OPTIONAL_FIELDS["size_variants"] + OPTIONAL_FIELDS["certifications"]),
            None,
        ) if not first_req_gap else None

        if first_req_gap:
            meta = FIELD_META.get(first_req_gap, {})
            console.print(
                f"\n  [bold red]▶ Next required action:[/bold red] "
                f"type [bold yellow]{first_req_gap}[/bold yellow] "
                f"[dim]({meta.get('desc', '')} · {meta.get('range', '')})[/dim]"
            )
        elif first_opt_gap:
            meta = FIELD_META.get(first_opt_gap, {})
            console.print(
                f"\n  [bold yellow]▶ Optional gap:[/bold yellow] "
                f"type [bold yellow]{first_opt_gap}[/bold yellow] "
                f"[dim]({meta.get('desc', '')} · {meta.get('range', '')})[/dim]"
            )

    # ── Editable fields reminder ──────────────────────────────────────────
    req_fields = sorted(
        REQUIRED_FIELDS["models"] + REQUIRED_FIELDS["size_variants"] + REQUIRED_FIELDS["certifications"]
    )
    opt_fields = sorted(
        OPTIONAL_FIELDS["models"] + OPTIONAL_FIELDS["size_variants"] + OPTIONAL_FIELDS["certifications"]
    )
    console.print(
        f"\n  [dim]Required fields: [red]{', '.join(req_fields)}[/red][/dim]"
    )
    console.print(
        f"  [dim]Optional fields: {', '.join(opt_fields)}[/dim]"
    )


# ── Field editing ────────────────────────────────────────────────────────────────


def _validate_value(field: str, raw: str) -> tuple[Any, str | None]:
    """Parse and range-check a value. Returns (parsed_value, error_msg)."""
    meta = FIELD_META.get(field, {})
    if "min" in meta:
        try:
            v: Any = int(raw) if meta.get("int") else float(raw)
        except ValueError:
            return None, f"Expected a number, got '{raw}'"
        if v < meta["min"] or v > meta["max"]:
            return None, f"Out of range {meta['range']} (got {v})"
        return v, None
    return raw.strip(), None


def _ask_ai(
    console: Console,
    model_name: str,
    field: str,
    context: str,
) -> tuple[str | None, str | None]:
    """
    Invoke Ollama inline for a field suggestion.
    Returns (suggested_value_str, note) or (None, error_message).
    Note: this uses training data only — Ollama cannot browse the web.
    """
    try:
        import httpx
    except ImportError:
        return None, "httpx not installed"

    meta = FIELD_META.get(field, {})
    prompt = (
        f"You are a paraglider spec database assistant. "
        f"Based on your training data only, what is the {field} "
        f"({meta.get('desc', field)}) for the {model_name}? "
        f"Context: {context}\n"
        f"Return ONLY a JSON object: "
        f'{{\"value\": \"...\", \"confidence\": \"high|medium|low\", \"note\": \"...\"}}\n'
        f"If you don't know, return "
        f'{{\"value\": null, \"confidence\": \"low\", \"note\": \"no data in training\"}}.'
    )

    console.print("[dim]  Asking Ollama (qwen2.5:3b)…[/dim]")
    try:
        resp = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen2.5:3b",
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        result = json.loads(resp.json()["message"]["content"])
        val = result.get("value")
        confidence = result.get("confidence", "?")
        note = result.get("note", "")
        if val is None:
            return None, f"AI has no data ({note})"
        return str(val), f"[{confidence} confidence] {note} — verify before accepting"
    except Exception as exc:
        return None, f"Ollama error: {exc}"


def _edit_one_record(
    console: Console,
    conn: sqlite3.Connection,
    table: str,
    record_id: int,
    field: str,
    context_label: str,
    model_name: str,
) -> bool:
    """
    Interactive prompt to edit a single field on a single record.
    Returns True if the record was changed (value written or marked not_available).
    """
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()  # noqa: S608
    current = row[field] if row and row[field] is not None else None
    meta = FIELD_META.get(field, {})

    console.print(
        f"\n  [bold]{field}[/bold]  [dim]{meta.get('desc', '')}[/dim]  "
        f"range: [dim]{meta.get('range', 'any')}[/dim]"
    )
    console.print(f"  [dim]{context_label}[/dim]")
    console.print(f"  current: [yellow]{current if current is not None else '—'}[/yellow]")
    console.print("  [dim]  n=not available   ?=ask AI   s=skip[/dim]")

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return False

        if raw in ("s", ""):
            console.print("  [dim]Skipped.[/dim]")
            return False

        if raw == "n":
            set_verification(conn, table, record_id, field, "not_available")
            console.print("  [dim]Marked as not_available.[/dim]")
            return True

        if raw == "?":
            suggested, note = _ask_ai(console, model_name, field, context_label)
            if suggested is None:
                console.print(f"  [yellow]{note}[/yellow]")
                console.print("  [dim]Enter a value manually or [s] to skip.[/dim]")
                continue
            console.print(f"  [cyan]AI suggests:[/cyan] [bold]{suggested}[/bold]")
            console.print(f"  [dim]{note}[/dim]")
            console.print("  [dim]Accept? [y]=yes  [n]=reject  or type a corrected value[/dim]")
            try:
                choice = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                return False
            if choice.lower() == "y" or choice == "":
                raw = suggested
            elif choice.lower() == "n":
                console.print("  [dim]Rejected. Enter a value manually or [s] to skip.[/dim]")
                continue
            else:
                raw = choice  # user typed a corrected value

        parsed, err = _validate_value(field, raw)
        if err:
            console.print(f"  [red]{err}[/red]")
            continue

        console.print(
            f"  Write [bold]{parsed!r}[/bold] to {table}.{field} "
            f"on {context_label}? (y/yes) ",
            end="",
        )
        try:
            confirm = input("").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False

        if confirm not in ("y", "yes", "1"):
            console.print("  [dim]Cancelled.[/dim]")
            return False

        conn.execute(f"UPDATE {table} SET {field} = ? WHERE id = ?", (parsed, record_id))  # noqa: S608
        conn.commit()
        set_verification(conn, table, record_id, field, "verified", verified_by="user")
        console.print("  [green]✓ Saved.[/green]")
        return True


def _create_cert_for_size(
    console: Console,
    conn: sqlite3.Connection,
    sv_id: int,
    sv_label: str,
    model_name: str,
) -> int | None:
    """
    Interactively create a new certification record for a size variant.
    Prompts for standard then classification. Returns the new cert id, or None on skip.
    """
    VALID_STANDARDS = {"EN", "LTF", "AFNOR", "DGAC", "CCC", "other"}
    VALID_CLASSES = {"A", "B", "C", "D", "1", "2", "3", "CCC", "Load test"}

    console.print(
        f"\n  [bold]New cert for {model_name} · size {sv_label}[/bold]"
    )

    # — standard —
    console.print(
        f"  [bold]standard[/bold]  [dim]Certification standard[/dim]  "
        f"range: [dim]EN | LTF | AFNOR | DGAC | CCC | other[/dim]\n"
        f"  current: [yellow]—[/yellow]"
    )
    console.print("  [dim]  n=not available   s=skip this size[/dim]")
    while True:
        try:
            raw_std = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw_std in ("s", ""):
            console.print("  [dim]Skipped.[/dim]")
            return None
        if raw_std == "n":
            console.print("  [dim]No certification standard — size skipped.[/dim]")
            return None
        if raw_std.upper() not in {s.upper() for s in VALID_STANDARDS}:
            console.print(
                f"  [red]'{raw_std}' is not a valid standard. "
                f"Choose: {', '.join(sorted(VALID_STANDARDS))}[/red]"
            )
            continue
        # normalise case
        std_val = next(s for s in VALID_STANDARDS if s.upper() == raw_std.upper())
        break

    # — classification —
    console.print(
        f"\n  [bold]classification[/bold]  [dim]Certification class[/dim]  "
        f"range: [dim]A | B | C | D | 1 | 2 | 3 | CCC | Load test[/dim]\n"
        f"  current: [yellow]—[/yellow]"
    )
    console.print("  [dim]  n=not available   s=skip this size[/dim]")
    while True:
        try:
            raw_cls = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw_cls in ("s", ""):
            console.print("  [dim]Skipped.[/dim]")
            return None
        if raw_cls == "n":
            raw_cls = None  # type: ignore[assignment]
            break
        break  # accept any non-empty string (validated loosely)

    console.print(
        f"  Create cert [bold]{std_val}[/bold]"
        + (f" / [bold]{raw_cls}[/bold]" if raw_cls else "")
        + f" on {model_name} size {sv_label}? (y/yes) ",
        end="",
    )
    try:
        confirm = input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if confirm not in ("y", "yes", "1"):
        console.print("  [dim]Cancelled.[/dim]")
        return None

    cur = conn.execute(
        "INSERT INTO certifications (size_variant_id, standard, classification, status) "
        "VALUES (?, ?, ?, 'active')",
        (sv_id, std_val, raw_cls),
    )
    conn.commit()
    cert_id = cur.lastrowid
    set_verification(conn, "certifications", cert_id, "standard", "verified", verified_by="user")
    if raw_cls:
        set_verification(conn, "certifications", cert_id, "classification", "verified", verified_by="user")
    console.print(f"  [green]✓ Cert created (id={cert_id}).[/green]")
    return cert_id


def edit_field_for_model(
    console: Console,
    conn: sqlite3.Connection,
    model_id: int,
    field: str,
) -> int:
    """
    Dispatch field editing across all records of a model that have the field NULL
    (and not already verified/not_available).
    Returns count of changes made.
    """
    model = conn.execute("SELECT name FROM models WHERE id = ?", (model_id,)).fetchone()
    model_name = model["name"] if model else f"model#{model_id}"
    changes = 0

    if field in REQUIRED_FIELDS["models"] + OPTIONAL_FIELDS["models"]:
        context = f"{model_name} · model record"
        verifs = get_verifications(conn, "models", model_id)
        if verifs.get(field) not in ("not_available", "verified"):
            if _edit_one_record(console, conn, "models", model_id, field, context, model_name):
                changes += 1

    elif field in REQUIRED_FIELDS["size_variants"] + OPTIONAL_FIELDS["size_variants"]:
        sv_rows = conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
        ).fetchall()
        for sv in sv_rows:
            verifs = get_verifications(conn, "size_variants", sv["id"])
            if sv[field] is None and verifs.get(field) not in ("not_available", "verified"):
                context = f"{model_name} · size {sv['size_label']}"
                if _edit_one_record(console, conn, "size_variants", sv["id"], field, context, model_name):
                    changes += 1

    elif field in REQUIRED_FIELDS["certifications"] + OPTIONAL_FIELDS["certifications"]:
        sv_rows = conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
        ).fetchall()
        for sv in sv_rows:
            sv_label = sv["size_label"]
            cert_rows = conn.execute(
                "SELECT * FROM certifications WHERE size_variant_id = ?", (sv["id"],)
            ).fetchall()

            # No cert records for this size — offer to create one first
            if not cert_rows:
                if field in ("standard", "classification"):
                    # Creating a cert means we handle both standard+classification together
                    cert_id = _create_cert_for_size(
                        console, conn, sv["id"], sv_label, model_name
                    )
                    if cert_id is not None:
                        changes += 1
                else:
                    console.print(
                        f"  [yellow]Size {sv_label}: no cert record exists. "
                        f"Type 'standard' first to create one.[/yellow]"
                    )
                continue

            for cert in cert_rows:
                verifs = get_verifications(conn, "certifications", cert["id"])
                if cert[field] is None and verifs.get(field) not in ("not_available", "verified"):
                    context = (
                        f"{model_name} · size {sv_label} · "
                        f"cert {cert['standard']}/{cert['classification']}"
                    )
                    if _edit_one_record(
                        console, conn, "certifications", cert["id"], field, context, model_name
                    ):
                        changes += 1

    else:
        console.print(f"  [red]Unknown field '{field}'.[/red]")

    return changes


# ── Lock ─────────────────────────────────────────────────────────────────────────


def lock_model(console: Console, conn: sqlite3.Connection, model_id: int) -> None:
    """Mark all currently non-NULL populated fields on a model as verified."""
    model = conn.execute("SELECT name FROM models WHERE id = ?", (model_id,)).fetchone()
    model_name = model["name"] if model else f"model#{model_id}"

    items: list[tuple[str, int, str]] = []
    model_row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    for f in REQUIRED_FIELDS["models"] + OPTIONAL_FIELDS["models"]:
        try:
            if model_row[f] is not None:
                items.append(("models", model_id, f))
        except IndexError:
            pass

    for sv in conn.execute(
        "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
    ).fetchall():
        for f in REQUIRED_FIELDS["size_variants"] + OPTIONAL_FIELDS["size_variants"]:
            try:
                if sv[f] is not None:
                    items.append(("size_variants", sv["id"], f))
            except IndexError:
                pass
        for cert in conn.execute(
            "SELECT * FROM certifications WHERE size_variant_id = ?", (sv["id"],)
        ).fetchall():
            for f in REQUIRED_FIELDS["certifications"] + OPTIONAL_FIELDS["certifications"]:
                try:
                    if cert[f] is not None:
                        items.append(("certifications", cert["id"], f))
                except IndexError:
                    pass

    if not items:
        console.print("[yellow]Nothing to lock (no non-NULL fields found).[/yellow]")
        return

    console.print(
        f"\n  Lock [bold]{len(items)}[/bold] fields on [bold]{model_name}[/bold] as verified? (y/yes) ",
        end="",
    )
    try:
        confirm = input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm not in ("y", "yes", "1"):
        console.print("  [dim]Cancelled.[/dim]")
        return

    for table, record_id, field in items:
        set_verification(conn, table, record_id, field, "verified", verified_by="user")
    console.print(f"  [cyan]✓ Locked {len(items)} fields.[/cyan]")


# ── Export tasks ─────────────────────────────────────────────────────────────────


def export_tasks(
    conn: sqlite3.Connection,
    output_path: str,
    slug_filter: str | None = None,
    field_filter: str | None = None,
    all_fields: bool = False,
) -> None:
    """Export pending field gaps as a structured JSON task file for AI delegation.

    By default only exports high-priority fields. Pass all_fields=True to also
    include low-priority cert details and rare geometry fields.
    """
    query = "SELECT id, name, slug FROM models"
    params: list = []
    if slug_filter:
        query += " WHERE slug LIKE ?"
        params.append(f"%{slug_filter}%")
    query += " ORDER BY name"
    models = conn.execute(query, params).fetchall()

    # Determine which (table, field) pairs to scan
    if field_filter:
        if field_filter not in ALL_KNOWN_FIELDS:
            print(f"Error: unknown field '{field_filter}'", file=sys.stderr)
            sys.exit(1)
        target_pairs = [
            (table, field_filter)
            for table in ALLOWED_TABLES
            if field_filter in REQUIRED_FIELDS[table] + OPTIONAL_FIELDS[table]
        ]
    else:
        target_pairs = [
            (table, f)
            for table in ("models", "size_variants", "certifications")
            for f in REQUIRED_FIELDS[table] + OPTIONAL_FIELDS[table]
            if all_fields or FIELD_TASK_PRIORITY.get(f, "high") == "high"
        ]

    items: list[dict] = []

    for model in models:
        model_id = model["id"]
        sv_rows = conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ? ORDER BY id", (model_id,)
        ).fetchall()

        for table, field in target_pairs:
            if table == "models":
                model_row = conn.execute(
                    "SELECT * FROM models WHERE id = ?", (model_id,)
                ).fetchone()
                verifs = get_verifications(conn, "models", model_id)
                if model_row[field] is None and verifs.get(field) not in ("not_available", "verified"):
                    items.append({
                        "table": "models",
                        "record_id": model_id,
                        "model_slug": model["slug"],
                        "model_name": model["name"],
                        "size_label": None,
                        "field": field,
                        "priority": FIELD_TASK_PRIORITY.get(field, "high"),
                        "current_value": None,
                        "context": f"{model['name']} — model record",
                        "search_hint": SEARCH_HINTS.get(field, f"Find {field} for {{model}}").format(model=model["name"]),
                        "search_urls": SEARCH_URLS.get(field, []),
                        "value": None,
                        "source_url": None,
                    })

            elif table == "size_variants":
                for sv in sv_rows:
                    verifs = get_verifications(conn, "size_variants", sv["id"])
                    if sv[field] is None and verifs.get(field) not in ("not_available", "verified"):
                        items.append({
                            "table": "size_variants",
                            "record_id": sv["id"],
                            "model_slug": model["slug"],
                            "model_name": model["name"],
                            "size_label": sv["size_label"],
                            "field": field,
                            "priority": FIELD_TASK_PRIORITY.get(field, "high"),
                            "current_value": None,
                            "context": f"{model['name']} size {sv['size_label']}",
                            "search_hint": SEARCH_HINTS.get(field, f"Find {field} for {{model}}").format(model=model["name"]),
                            "search_urls": SEARCH_URLS.get(field, []),
                            "value": None,
                            "source_url": None,
                        })

            elif table == "certifications":
                for sv in sv_rows:
                    for cert in conn.execute(
                        "SELECT * FROM certifications WHERE size_variant_id = ?", (sv["id"],)
                    ).fetchall():
                        verifs = get_verifications(conn, "certifications", cert["id"])
                        if cert[field] is None and verifs.get(field) not in ("not_available", "verified"):
                            items.append({
                                "table": "certifications",
                                "record_id": cert["id"],
                                "model_slug": model["slug"],
                                "model_name": model["name"],
                                "size_label": sv["size_label"],
                                "field": field,
                                "priority": FIELD_TASK_PRIORITY.get(field, "high"),
                                "current_value": None,
                                "context": (
                                    f"{model['name']} size {sv['size_label']} "
                                    f"cert {cert['standard']}/{cert['classification']}"
                                ),
                                "search_hint": SEARCH_HINTS.get(field, f"Find {field} for {{model}}").format(model=model["name"]),
                                "search_urls": SEARCH_URLS.get(field, []),
                                "value": None,
                                "source_url": None,
                            })

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    priority_note = "all fields (high + low priority)" if all_fields else "high-priority fields only (use --all-fields to include cert details and rare geometry)"
    task = {
        "task_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db_path": str(conn.execute("PRAGMA database_list").fetchone()[2]),
        "total_items": len(items),
        "scope": priority_note,
        "instructions": (
            "For each item, find the value for the specified field and fill in "
            "'value' and 'source_url'. "
            "source_url is REQUIRED whenever you provide a value: "
            "link to the exact page (manufacturer product page, DHV report page, "
            "dataset URL, etc.) where you found the data. "
            "If the data did not come from the manufacturer's own website, "
            "state that clearly in a 'source_note' field on the item. "
            "If you cannot find the value with confidence, leave value and source_url "
            "as null. Do not guess or infer values you are not certain about."
        ),
        "source_required": True,
        "items": items,
    }
    Path(output_path).write_text(json.dumps(task, indent=2))
    print(f"✓ Exported {len(items)} pending items → {output_path}")


# ── Apply patch ──────────────────────────────────────────────────────────────────


def apply_patch(
    console: Console,
    conn: sqlite3.Connection,
    patch_path: str,
) -> None:
    try:
        data = json.loads(Path(patch_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[red]Cannot read patch file: {exc}[/red]")
        return

    raw_items = data.get("items", [])

    # Validate and filter actionable items
    missing_source: list[str] = []
    actionable: list[dict] = []
    for item in raw_items:
        if item.get("value") is None:
            continue
        # Security: only allow known table/field names from our config
        if item.get("table") not in ALLOWED_TABLES:
            console.print(f"  [red]Skipping invalid table '{item.get('table')}'[/red]")
            continue
        if item.get("field") not in ALL_KNOWN_FIELDS:
            console.print(f"  [red]Skipping unknown field '{item.get('field')}'[/red]")
            continue
        verifs = get_verifications(conn, item["table"], item["record_id"])
        if verifs.get(item["field"]) == "verified":
            continue  # already verified — skip silently
        if not item.get("source_url"):
            missing_source.append(
                f"{item.get('model_slug','?')} / {item.get('size_label','') or 'model'} / {item['field']}"
            )
        actionable.append(item)

    if missing_source:
        console.print(
            f"[yellow]Warning: {len(missing_source)} item(s) have no source_url — "
            f"provenance will be unverifiable:[/yellow]"
        )
        for label in missing_source[:5]:
            console.print(f"  [dim]{label}[/dim]")
        if len(missing_source) > 5:
            console.print(f"  [dim]… and {len(missing_source) - 5} more[/dim]")
        console.print()

    if not actionable:
        console.print("[yellow]No actionable items (all already verified or no values provided).[/yellow]")
        return

    tbl = Table(
        title=f"Patch review — {len(actionable)} proposed changes",
        box=box.SIMPLE, show_header=True, header_style="bold",
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Model", min_width=26)
    tbl.add_column("Size", width=6)
    tbl.add_column("Field", width=20)
    tbl.add_column("Current", width=10)
    tbl.add_column("Proposed", width=16)
    tbl.add_column("Source", style="dim", min_width=30)

    for i, item in enumerate(actionable, 1):
        source_cell = item.get("source_url") or ""
        if item.get("source_note"):
            source_cell += f" [{item['source_note']}]"
        if not source_cell:
            source_cell = "[red]MISSING[/red]"
        tbl.add_row(
            str(i),
            item.get("model_slug", "?"),
            item.get("size_label") or "—",
            item["field"],
            str(item.get("current_value") or "—"),
            f"[cyan]{item['value']}[/cyan]",
            source_cell,
        )

    console.print(tbl)
    console.print(
        "\n[bold]Commands:[/bold]  "
        "[yellow]a[/yellow]=accept all  "
        "[yellow]1,3,5[/yellow]=accept by number  "
        "[yellow]r[/yellow]=reject all\n"
    )

    try:
        choice = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice.lower() in ("r", ""):
        console.print("[yellow]All rejected.[/yellow]")
        return

    if choice.lower() == "a":
        accept_indices = set(range(1, len(actionable) + 1))
    else:
        try:
            accept_indices = {int(x.strip()) for x in choice.split(",") if x.strip()}
        except ValueError:
            console.print("[red]Invalid input — expected 'a', 'r', or comma-separated numbers.[/red]")
            return

    count = 0
    for i, item in enumerate(actionable, 1):
        if i not in accept_indices:
            continue
        parsed, err = _validate_value(item["field"], str(item["value"]))
        if err:
            console.print(f"  [red]item {i}: {err} — skipped[/red]")
            continue
        conn.execute(
            f"UPDATE {item['table']} SET {item['field']} = ? WHERE id = ?",  # noqa: S608
            (parsed, item["record_id"]),
        )
        set_verification(
            conn, item["table"], item["record_id"], item["field"],
            "verified", source_url=item.get("source_url"), verified_by="agent",
        )
        count += 1

    conn.commit()
    console.print(f"[green]✓ Applied {count} of {len(actionable)} proposed changes.[/green]")


# ── Interactive TUI loops ─────────────────────────────────────────────────────────


def run_model_detail_loop(
    console: Console,
    conn: sqlite3.Connection,
    model_id: int,
) -> None:
    all_fields = list(ALL_KNOWN_FIELDS)

    while True:
        console.clear()
        render_model_detail(console, conn, model_id)

        try:
            console.print(
                "[dim]field-name[/dim] edit  "
                "[bold yellow]l[/bold yellow] lock  "
                "[bold yellow]b[/bold yellow] back  "
                "[bold yellow]q[/bold yellow] quit",
            )
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "q":
            sys.exit(0)
        if cmd == "b":
            break
        if cmd == "":
            continue  # plain Enter just re-renders

        if cmd == "l":
            lock_model(console, conn, model_id)
            input("  Press Enter to continue…")
            continue

        if cmd in ALL_KNOWN_FIELDS:
            changes = edit_field_for_model(console, conn, model_id, cmd)
            s = compute_model_score(conn, model_id)
            if changes:
                console.print(
                    f"\n  [green]✓ {changes} change(s) saved.[/green]  "
                    f"req: [bold]{s['required_score']:.0%}[/bold]  "
                    f"opt: [bold]{s['optional_score']:.0%}[/bold]  "
                    f"status: [{STATUS_COLOR[s['status']]}]{s['status']}[/{STATUS_COLOR[s['status']]}]"
                )
            else:
                console.print(
                    f"\n  [dim]No pending gaps for '{cmd}' "
                    f"(all sizes already filled or verified).[/dim]"
                )
            input("  Press Enter to continue…")
            continue

        console.print(
            f"  [red]Unknown command '{cmd}'[/red]  "
            f"[dim]— type a field name, or: l=lock  b=back  q=quit[/dim]"
        )
        input("  Press Enter…")


def run_interactive(console: Console, conn: sqlite3.Connection) -> None:
    slug_filter: str | None = None

    while True:
        console.clear()
        scores = render_dashboard(console, conn, slug_filter)
        if not scores:
            console.print("[yellow]No models found.[/yellow]")
            break

        try:
            console.print(
                "[dim]<number>[/dim] open  "
                "[bold yellow]f <text>[/bold yellow] filter  "
                "[bold yellow]f[/bold yellow] clear  "
                "[bold yellow]r[/bold yellow] refresh  "
                "[bold yellow]q[/bold yellow] quit",
            )
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd.lower() == "q":
            break
        if cmd.lower() == "r":
            continue
        if cmd.lower() == "f":
            slug_filter = None
            continue
        if cmd.lower().startswith("f "):
            slug_filter = cmd[2:].strip() or None
            continue

        try:
            idx = int(cmd)
        except ValueError:
            console.print(f"[red]Unknown command '{cmd}'[/red]")
            input("  Press Enter to continue…")
            continue

        if idx < 1 or idx > len(scores):
            console.print(f"[red]Number {idx} out of range (1–{len(scores)}).[/red]")
            input("  Press Enter to continue…")
            continue

        run_model_detail_loop(console, conn, scores[idx - 1]["model_id"])


# ── Entry point ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Data curation TUI for the OpenPG spec database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/data_curator.py --db output/ozone.db\n"
            "  python3 scripts/data_curator.py --db output/ozone.db "
            "--export-tasks output/tasks/cert_tasks.json --field test_lab\n"
            "  python3 scripts/data_curator.py --db output/ozone.db "
            "--apply-patch output/tasks/cert_patch.json\n"
        ),
    )
    parser.add_argument("--db", required=True, help="Path to SQLite database file.")
    parser.add_argument(
        "--export-tasks", metavar="TASK_FILE",
        help="Export pending field gaps as a JSON task file for AI agent delegation.",
    )
    parser.add_argument(
        "--apply-patch", metavar="PATCH_FILE",
        help="Review and apply an AI-researched patch JSON.",
    )
    parser.add_argument("--slug", help="Filter to models whose slug contains this string.")
    parser.add_argument("--field", help="Filter to a specific field (use with --export-tasks).")
    parser.add_argument(
        "--all-fields", action="store_true",
        help="Include low-priority fields in --export-tasks (cert details: test_lab, report_url, "
             "test_date, report_number; rare geometry: proj_area_m2, proj_span_m, proj_aspect_ratio, "
             "line_length_m). Default: high-priority fields only.",
    )
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = open_db(args.db)
    console = Console()

    try:
        if args.export_tasks:
            export_tasks(
                conn, args.export_tasks,
                slug_filter=args.slug,
                field_filter=args.field,
                all_fields=args.all_fields,
            )
        elif args.apply_patch:
            apply_patch(console, conn, args.apply_patch)
        else:
            run_interactive(console, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
