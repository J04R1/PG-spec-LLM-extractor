"""
Data validator — per-model validation with issue detection and action log.

Scans each model in the database for:
  - Missing critical fields (completeness issues)
  - Implausible values (quality issues)
  - Internal inconsistencies (accuracy issues)

Produces a list of ModelIssue objects, each with a severity and suggested action.
Maintains a persistent JSON log of models needing attention, so validation
can be interrupted and resumed.

Usage:
    python -m src.pipeline validate --db output/ozone.db
    python -m src.pipeline validate --db output/ozone.db --auto-skip
    python -m src.pipeline validate --db output/ozone.db --resume
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Plausibility ranges (shared with benchmark) ───────────────────────────────

PLAUSIBILITY = {
    "flat_area_m2":      (10.0, 50.0),
    "flat_span_m":       (6.0, 20.0),
    "flat_aspect_ratio": (2.5, 8.5),
    "proj_area_m2":      (8.0, 42.0),
    "proj_span_m":       (5.0, 17.0),
    "proj_aspect_ratio": (2.0, 7.0),
    "wing_weight_kg":    (1.0, 12.0),
    "ptv_min_kg":        (30.0, 200.0),
    "ptv_max_kg":        (40.0, 250.0),
    "cell_count":        (15, 120),
    "year_released":     (1990, 2026),
    "speed_trim_kmh":    (25.0, 50.0),
    "speed_max_kmh":     (35.0, 80.0),
    "glide_ratio_best":  (5.0, 15.0),
    "min_sink_ms":       (0.7, 1.8),
}


class Severity(str, Enum):
    """Issue severity level."""
    critical = "critical"    # data is wrong / contradictory
    warning = "warning"      # data is missing or implausible
    info = "info"            # minor gap, cosmetic


class Action(str, Enum):
    """User-chosen action for a flagged model."""
    pending = "pending"          # not yet reviewed
    re_extract = "re_extract"    # trigger pipeline re-extraction
    skip = "skip"                # accept as-is, move on
    manual_fix = "manual_fix"    # user will fix manually later


@dataclass
class ModelIssue:
    """A single validation issue for a model."""
    check: str            # e.g. "missing_year_released", "ptv_min_gte_max"
    severity: Severity
    message: str          # human-readable explanation
    field: str = ""       # affected field or empty for cross-field
    size_label: str = ""  # empty if model-level issue


@dataclass
class ModelValidation:
    """Validation result for a single model."""
    model_id: int
    model_slug: str
    model_name: str
    manufacturer_slug: str
    manufacturer_url: str | None
    size_count: int = 0
    issues: list[ModelIssue] = field(default_factory=list)
    action: Action = Action.pending

    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.critical for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.severity == Severity.warning for i in self.issues)

    @property
    def score(self) -> str:
        """Quick status: ✗ critical, △ warning, ✓ clean."""
        if self.has_critical:
            return "✗"
        if self.has_warning:
            return "△"
        return "✓"

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_slug": self.model_slug,
            "model_name": self.model_name,
            "manufacturer_slug": self.manufacturer_slug,
            "manufacturer_url": self.manufacturer_url,
            "size_count": self.size_count,
            "action": self.action.value,
            "issues": [
                {
                    "check": i.check,
                    "severity": i.severity.value,
                    "message": i.message,
                    "field": i.field,
                    "size_label": i.size_label,
                }
                for i in self.issues
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ModelValidation:
        mv = cls(
            model_id=d["model_id"],
            model_slug=d["model_slug"],
            model_name=d["model_name"],
            manufacturer_slug=d["manufacturer_slug"],
            manufacturer_url=d.get("manufacturer_url"),
            size_count=d.get("size_count", 0),
            action=Action(d.get("action", "pending")),
        )
        for issue_d in d.get("issues", []):
            mv.issues.append(ModelIssue(
                check=issue_d["check"],
                severity=Severity(issue_d["severity"]),
                message=issue_d["message"],
                field=issue_d.get("field", ""),
                size_label=issue_d.get("size_label", ""),
            ))
        return mv


# ── Validation log (persistent JSON) ──────────────────────────────────────────


@dataclass
class ValidationLog:
    """Persistent log of validation results, survives restarts."""
    log_path: Path
    timestamp: str = ""
    db_path: str = ""
    models: dict[str, ModelValidation] = field(default_factory=dict)  # keyed by slug

    def save(self) -> None:
        """Write log to disk."""
        data = {
            "timestamp": self.timestamp,
            "db_path": self.db_path,
            "models": {
                slug: mv.to_dict() for slug, mv in self.models.items()
            },
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, log_path: Path) -> ValidationLog:
        """Load log from disk."""
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)
        vl = cls(
            log_path=log_path,
            timestamp=data.get("timestamp", ""),
            db_path=data.get("db_path", ""),
        )
        for slug, model_d in data.get("models", {}).items():
            vl.models[slug] = ModelValidation.from_dict(model_d)
        return vl

    @property
    def pending_models(self) -> list[ModelValidation]:
        return [mv for mv in self.models.values()
                if mv.action == Action.pending and mv.issues]

    @property
    def re_extract_models(self) -> list[ModelValidation]:
        return [mv for mv in self.models.values()
                if mv.action == Action.re_extract]

    def summary(self) -> dict:
        total = len(self.models)
        clean = sum(1 for mv in self.models.values() if not mv.issues)
        with_issues = total - clean
        critical = sum(1 for mv in self.models.values() if mv.has_critical)
        pending = len(self.pending_models)
        re_extract = len(self.re_extract_models)
        skipped = sum(1 for mv in self.models.values() if mv.action == Action.skip)
        manual = sum(1 for mv in self.models.values() if mv.action == Action.manual_fix)
        return {
            "total_models": total,
            "clean": clean,
            "with_issues": with_issues,
            "critical": critical,
            "pending": pending,
            "re_extract": re_extract,
            "skipped": skipped,
            "manual_fix": manual,
        }


# ── Per-model validation checks ───────────────────────────────────────────────


# Critical fields that should be populated for a model to be useful
_CRITICAL_MODEL_FIELDS = ["category", "cell_count", "manufacturer_url"]
_CRITICAL_SIZE_FIELDS = ["flat_area_m2", "ptv_min_kg", "ptv_max_kg"]


def validate_database(db_path: str | Path) -> ValidationLog:
    """
    Validate every model in the database. Returns a ValidationLog with
    per-model issues.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    log_file = db_path.with_suffix(".validation.json")
    vlog = ValidationLog(
        log_path=log_file,
        timestamp=datetime.now(timezone.utc).isoformat(),
        db_path=str(db_path),
    )

    try:
        models = conn.execute("""
            SELECT m.*, mfr.slug as mfr_slug
            FROM models m
            JOIN manufacturers mfr ON m.manufacturer_id = mfr.id
            ORDER BY mfr.slug, m.name
        """).fetchall()

        for model_row in models:
            mv = _validate_model(conn, model_row)
            vlog.models[mv.model_slug] = mv

    finally:
        conn.close()

    vlog.save()
    return vlog


def _validate_model(conn: sqlite3.Connection, model: sqlite3.Row) -> ModelValidation:
    """Run all checks on a single model."""
    mv = ModelValidation(
        model_id=model["id"],
        model_slug=model["slug"],
        model_name=model["name"],
        manufacturer_slug=model["mfr_slug"],
        manufacturer_url=model["manufacturer_url"],
    )

    # ── Model-level checks ─────────────────────────────────────────────

    # Missing critical fields
    for field_name in _CRITICAL_MODEL_FIELDS:
        if model[field_name] is None:
            mv.issues.append(ModelIssue(
                check=f"missing_{field_name}",
                severity=Severity.warning,
                message=f"Missing {field_name}",
                field=field_name,
            ))

    # Year released missing
    if model["year_released"] is None:
        mv.issues.append(ModelIssue(
            check="missing_year_released",
            severity=Severity.warning,
            message="Missing year_released",
            field="year_released",
        ))

    # Year plausibility
    if model["year_released"] is not None:
        lo, hi = PLAUSIBILITY["year_released"]
        if not (lo <= model["year_released"] <= hi):
            mv.issues.append(ModelIssue(
                check="implausible_year_released",
                severity=Severity.critical,
                message=f"year_released={model['year_released']} outside {lo}–{hi}",
                field="year_released",
            ))

    # Cell count plausibility
    if model["cell_count"] is not None:
        lo, hi = PLAUSIBILITY["cell_count"]
        if not (lo <= model["cell_count"] <= hi):
            mv.issues.append(ModelIssue(
                check="implausible_cell_count",
                severity=Severity.warning,
                message=f"cell_count={model['cell_count']} outside {lo}–{hi}",
                field="cell_count",
            ))

    # Discontinued without year
    if model["is_current"] == 0 and model["year_discontinued"] is None:
        mv.issues.append(ModelIssue(
            check="discontinued_no_year",
            severity=Severity.info,
            message="Discontinued but year_discontinued not set",
            field="year_discontinued",
        ))

    # ── Size-level checks ──────────────────────────────────────────────

    sizes = conn.execute(
        "SELECT * FROM size_variants WHERE model_id = ?",
        (model["id"],),
    ).fetchall()
    mv.size_count = len(sizes)

    if not sizes:
        mv.issues.append(ModelIssue(
            check="no_sizes",
            severity=Severity.critical,
            message="Model has no size variants",
        ))
        return mv

    for size in sizes:
        label = size["size_label"]

        # Missing critical size fields
        for field_name in _CRITICAL_SIZE_FIELDS:
            if size[field_name] is None:
                mv.issues.append(ModelIssue(
                    check=f"missing_{field_name}",
                    severity=Severity.warning,
                    message=f"Size {label}: missing {field_name}",
                    field=field_name,
                    size_label=label,
                ))

        # PTV consistency
        if size["ptv_min_kg"] is not None and size["ptv_max_kg"] is not None:
            if size["ptv_min_kg"] >= size["ptv_max_kg"]:
                mv.issues.append(ModelIssue(
                    check="ptv_min_gte_max",
                    severity=Severity.critical,
                    message=f"Size {label}: ptv_min={size['ptv_min_kg']} >= ptv_max={size['ptv_max_kg']}",
                    field="ptv_min_kg",
                    size_label=label,
                ))

        # Geometry consistency: flat_area ≈ span²/AR
        area = size["flat_area_m2"]
        span = size["flat_span_m"]
        ar = size["flat_aspect_ratio"]
        if area and span and ar and ar > 0:
            computed = (span ** 2) / ar
            if abs(computed - area) / area > 0.05:
                mv.issues.append(ModelIssue(
                    check="flat_geometry_inconsistent",
                    severity=Severity.critical,
                    message=f"Size {label}: flat_area={area} but span²/AR={computed:.2f} (>{5}% off)",
                    field="flat_area_m2",
                    size_label=label,
                ))

        # Projected < flat
        if size["proj_area_m2"] and size["flat_area_m2"]:
            if size["proj_area_m2"] >= size["flat_area_m2"]:
                mv.issues.append(ModelIssue(
                    check="proj_gte_flat",
                    severity=Severity.critical,
                    message=f"Size {label}: proj_area={size['proj_area_m2']} >= flat_area={size['flat_area_m2']}",
                    field="proj_area_m2",
                    size_label=label,
                ))

        # Plausibility checks on numeric fields
        for field_name, (lo, hi) in PLAUSIBILITY.items():
            if field_name in ("cell_count", "year_released"):
                continue  # checked at model level
            try:
                val = size[field_name]
            except IndexError:
                continue
            if val is not None and not (lo <= val <= hi):
                mv.issues.append(ModelIssue(
                    check=f"implausible_{field_name}",
                    severity=Severity.warning,
                    message=f"Size {label}: {field_name}={val} outside {lo}–{hi}",
                    field=field_name,
                    size_label=label,
                ))

    # ── Certification checks ───────────────────────────────────────────

    certs = conn.execute("""
        SELECT c.*, sv.size_label
        FROM certifications c
        JOIN size_variants sv ON c.size_variant_id = sv.id
        WHERE sv.model_id = ?
    """, (model["id"],)).fetchall()

    if not certs:
        mv.issues.append(ModelIssue(
            check="no_certifications",
            severity=Severity.warning,
            message="No certification records",
        ))

    _VALID_CLASSES = {
        "EN": {"A", "B", "C", "D"},
        "LTF": {"A", "B", "C", "D", "1", "1-2", "2", "2-3", "3"},
        "AFNOR": {"Standard", "Performance", "Competition"},
    }
    for cert in certs:
        std = cert["standard"]
        cls = cert["classification"]
        if std in _VALID_CLASSES and cls:
            if cls not in _VALID_CLASSES[std]:
                mv.issues.append(ModelIssue(
                    check=f"invalid_{std.lower()}_classification",
                    severity=Severity.critical,
                    message=f"Size {cert['size_label']}: {std}/{cls} — expected {'/'.join(sorted(_VALID_CLASSES[std]))}",
                    field="classification",
                    size_label=cert["size_label"],
                ))

    return mv


# ── Format helpers ─────────────────────────────────────────────────────────────


def format_model_issues(mv: ModelValidation) -> str:
    """Format a single model's issues for terminal display."""
    lines = [f"\n{mv.score} {mv.model_name} ({mv.model_slug}) — {mv.size_count} sizes"]
    if mv.manufacturer_url:
        lines.append(f"  URL: {mv.manufacturer_url}")

    for issue in mv.issues:
        sev = {"critical": "✗", "warning": "△", "info": "·"}[issue.severity.value]
        ctx = f" [{issue.size_label}]" if issue.size_label else ""
        lines.append(f"  {sev} {issue.message}{ctx}")

    return "\n".join(lines)


def format_validation_summary(vlog: ValidationLog) -> str:
    """Format the full validation summary."""
    s = vlog.summary()
    lines = [
        f"═══ Validation Summary: {vlog.db_path} ═══",
        f"Total models: {s['total_models']}",
        f"  ✓ Clean:       {s['clean']}",
        f"  △ With issues: {s['with_issues']}",
        f"  ✗ Critical:    {s['critical']}",
        "",
        f"Actions:",
        f"  Pending:      {s['pending']}",
        f"  Re-extract:   {s['re_extract']}",
        f"  Skipped:      {s['skipped']}",
        f"  Manual fix:   {s['manual_fix']}",
    ]
    return "\n".join(lines)
