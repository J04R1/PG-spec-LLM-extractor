"""
Benchmark scoring — quality, completeness, and accuracy metrics.

Scores a populated database across three dimensions:
  1. **Completeness** — what fraction of possible fields are populated
  2. **Quality** — do populated values pass plausibility checks
  3. **Accuracy** — are values internally consistent (cross-field checks)

Results are structured for comparison across extraction methods (LLM vs parser
vs manual), models (Qwen vs Llama vs GPT), and data sources.

Usage:
    python -m src.pipeline benchmark --db output/ozone.db
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Plausibility ranges for quality checks ─────────────────────────────────────

PLAUSIBILITY = {
    # Size variant geometry
    "flat_area_m2":      (10.0, 50.0),
    "flat_span_m":       (6.0, 20.0),
    "flat_aspect_ratio": (2.5, 8.5),
    "proj_area_m2":      (8.0, 42.0),
    "proj_span_m":       (5.0, 17.0),
    "proj_aspect_ratio": (2.0, 7.0),
    "wing_weight_kg":    (1.0, 12.0),
    "ptv_min_kg":        (30.0, 200.0),
    "ptv_max_kg":        (40.0, 250.0),
    "line_length_m":     (4.0, 12.0),
    # Performance
    "speed_trim_kmh":    (25.0, 50.0),
    "speed_max_kmh":     (35.0, 80.0),
    "glide_ratio_best":  (5.0, 15.0),
    "min_sink_ms":       (0.7, 1.8),
    # Model
    "cell_count":        (15, 120),
    "year_released":     (1990, 2026),
}


# ── Result data classes ────────────────────────────────────────────────────────


@dataclass
class FieldScore:
    """Score for a single field across all records."""
    field_name: str
    total: int = 0          # records where field could be present
    populated: int = 0      # records where field is not NULL
    plausible: int = 0      # populated values within expected range
    implausible_values: list = field(default_factory=list)  # sample bad values

    @property
    def completeness(self) -> float:
        return self.populated / self.total if self.total else 0.0

    @property
    def quality(self) -> float:
        return self.plausible / self.populated if self.populated else 1.0


@dataclass
class ConsistencyCheck:
    """Result of a cross-field consistency check."""
    check_name: str
    total: int = 0
    passed: int = 0
    failures: list = field(default_factory=list)  # sample failures

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 1.0


@dataclass
class TableScore:
    """Aggregate score for a database table."""
    table_name: str
    record_count: int = 0
    field_scores: dict[str, FieldScore] = field(default_factory=dict)
    consistency_checks: list[ConsistencyCheck] = field(default_factory=list)

    @property
    def completeness(self) -> float:
        if not self.field_scores:
            return 0.0
        return sum(f.completeness for f in self.field_scores.values()) / len(self.field_scores)

    @property
    def quality(self) -> float:
        scored = [f for f in self.field_scores.values() if f.populated > 0]
        if not scored:
            return 1.0
        return sum(f.quality for f in scored) / len(scored)

    @property
    def accuracy(self) -> float:
        if not self.consistency_checks:
            return 1.0
        return sum(c.accuracy for c in self.consistency_checks) / len(self.consistency_checks)


@dataclass
class BenchmarkReport:
    """Full benchmark report for a database."""
    db_path: str
    extraction_method: str = ""
    model_count: int = 0
    size_count: int = 0
    manufacturer_count: int = 0
    table_scores: dict[str, TableScore] = field(default_factory=dict)

    @property
    def completeness(self) -> float:
        if not self.table_scores:
            return 0.0
        return sum(t.completeness for t in self.table_scores.values()) / len(self.table_scores)

    @property
    def quality(self) -> float:
        if not self.table_scores:
            return 1.0
        return sum(t.quality for t in self.table_scores.values()) / len(self.table_scores)

    @property
    def accuracy(self) -> float:
        tables_with_checks = [t for t in self.table_scores.values() if t.consistency_checks]
        if not tables_with_checks:
            return 1.0
        return sum(t.accuracy for t in tables_with_checks) / len(tables_with_checks)

    def summary(self) -> dict:
        """Return a flat summary dict for comparison."""
        return {
            "db_path": self.db_path,
            "extraction_method": self.extraction_method,
            "manufacturers": self.manufacturer_count,
            "models": self.model_count,
            "sizes": self.size_count,
            "completeness": round(self.completeness, 4),
            "quality": round(self.quality, 4),
            "accuracy": round(self.accuracy, 4),
            "tables": {
                name: {
                    "records": t.record_count,
                    "completeness": round(t.completeness, 4),
                    "quality": round(t.quality, 4),
                    "accuracy": round(t.accuracy, 4),
                }
                for name, t in self.table_scores.items()
            },
        }

    def format_report(self) -> str:
        """Human-readable benchmark report."""
        lines = [
            f"═══ Benchmark Report: {self.db_path} ═══",
            f"Extraction method: {self.extraction_method or 'unknown'}",
            f"Scope: {self.manufacturer_count} manufacturers, "
            f"{self.model_count} models, {self.size_count} sizes",
            "",
            f"  COMPLETENESS: {self.completeness:.1%}",
            f"  QUALITY:      {self.quality:.1%}",
            f"  ACCURACY:     {self.accuracy:.1%}",
            "",
        ]

        for name, table in self.table_scores.items():
            lines.append(f"── {name} ({table.record_count} records) ──")
            lines.append(
                f"  completeness={table.completeness:.1%}  "
                f"quality={table.quality:.1%}  "
                f"accuracy={table.accuracy:.1%}"
            )

            # Show field-level detail
            for fname, fs in sorted(table.field_scores.items()):
                marker = "✓" if fs.quality >= 0.95 else "△" if fs.quality >= 0.8 else "✗"
                lines.append(
                    f"    {marker} {fname}: "
                    f"{fs.populated}/{fs.total} populated ({fs.completeness:.0%}), "
                    f"{fs.plausible}/{fs.populated} plausible ({fs.quality:.0%})"
                )
                if fs.implausible_values:
                    samples = fs.implausible_values[:3]
                    lines.append(f"      ↳ bad values: {samples}")

            # Show consistency checks
            for cc in table.consistency_checks:
                marker = "✓" if cc.accuracy >= 0.95 else "△" if cc.accuracy >= 0.8 else "✗"
                lines.append(
                    f"    {marker} {cc.check_name}: "
                    f"{cc.passed}/{cc.total} pass ({cc.accuracy:.0%})"
                )
                if cc.failures:
                    samples = cc.failures[:3]
                    lines.append(f"      ↳ failures: {samples}")

            lines.append("")

        return "\n".join(lines)


# ── Scoring engine ─────────────────────────────────────────────────────────────


def benchmark_database(db_path: str | Path) -> BenchmarkReport:
    """Run a full benchmark on a populated database. Returns a BenchmarkReport."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        report = BenchmarkReport(db_path=str(db_path))

        # Get extraction method from provenance
        prov_row = conn.execute(
            "SELECT extraction_method FROM provenance LIMIT 1"
        ).fetchone()
        if prov_row:
            report.extraction_method = prov_row["extraction_method"] or ""

        # Entity counts
        report.manufacturer_count = conn.execute(
            "SELECT COUNT(*) FROM manufacturers"
        ).fetchone()[0]
        report.model_count = conn.execute(
            "SELECT COUNT(*) FROM models"
        ).fetchone()[0]
        report.size_count = conn.execute(
            "SELECT COUNT(*) FROM size_variants"
        ).fetchone()[0]

        # Score each table
        report.table_scores["models"] = _score_models(conn)
        report.table_scores["size_variants"] = _score_size_variants(conn)
        report.table_scores["certifications"] = _score_certifications(conn)
        report.table_scores["performance_data"] = _score_performance(conn)

        return report
    finally:
        conn.close()


def _score_field(
    rows: list[sqlite3.Row],
    field_name: str,
    plausibility_range: tuple | None = None,
    max_samples: int = 5,
) -> FieldScore:
    """Score a single field across all rows."""
    fs = FieldScore(field_name=field_name, total=len(rows))

    for row in rows:
        val = row[field_name]
        if val is None:
            continue
        fs.populated += 1

        if plausibility_range:
            lo, hi = plausibility_range
            if lo <= val <= hi:
                fs.plausible += 1
            elif len(fs.implausible_values) < max_samples:
                fs.implausible_values.append(val)
        else:
            # No range check → all populated values are plausible
            fs.plausible += 1

    return fs


def _score_models(conn: sqlite3.Connection) -> TableScore:
    """Score the models table."""
    rows = conn.execute("SELECT * FROM models").fetchall()
    ts = TableScore(table_name="models", record_count=len(rows))

    # Fields to score
    scored_fields = {
        "category":         None,
        "year_released":    PLAUSIBILITY.get("year_released"),
        "cell_count":       PLAUSIBILITY.get("cell_count"),
        "riser_config":     None,
        "manufacturer_url": None,
    }

    for fname, plaus in scored_fields.items():
        ts.field_scores[fname] = _score_field(rows, fname, plaus)

    # Consistency: is_current=0 should have year_discontinued (soft check)
    check = ConsistencyCheck(check_name="discontinued_has_year")
    for row in rows:
        if row["is_current"] == 0:
            check.total += 1
            if row["year_discontinued"] is not None:
                check.passed += 1
            elif len(check.failures) < 5:
                check.failures.append(row["slug"])
    if check.total > 0:
        ts.consistency_checks.append(check)

    # Consistency: year_released <= year_discontinued when both present
    check2 = ConsistencyCheck(check_name="released_before_discontinued")
    for row in rows:
        if row["year_released"] and row["year_discontinued"]:
            check2.total += 1
            if row["year_released"] <= row["year_discontinued"]:
                check2.passed += 1
            elif len(check2.failures) < 5:
                check2.failures.append(
                    f"{row['slug']}: {row['year_released']}→{row['year_discontinued']}"
                )
    if check2.total > 0:
        ts.consistency_checks.append(check2)

    return ts


def _score_size_variants(conn: sqlite3.Connection) -> TableScore:
    """Score the size_variants table."""
    rows = conn.execute("SELECT * FROM size_variants").fetchall()
    ts = TableScore(table_name="size_variants", record_count=len(rows))

    scored_fields = {
        "flat_area_m2":      PLAUSIBILITY["flat_area_m2"],
        "flat_span_m":       PLAUSIBILITY["flat_span_m"],
        "flat_aspect_ratio": PLAUSIBILITY["flat_aspect_ratio"],
        "proj_area_m2":      PLAUSIBILITY["proj_area_m2"],
        "proj_span_m":       PLAUSIBILITY["proj_span_m"],
        "proj_aspect_ratio": PLAUSIBILITY["proj_aspect_ratio"],
        "wing_weight_kg":    PLAUSIBILITY["wing_weight_kg"],
        "ptv_min_kg":        PLAUSIBILITY["ptv_min_kg"],
        "ptv_max_kg":        PLAUSIBILITY["ptv_max_kg"],
        "line_length_m":     PLAUSIBILITY["line_length_m"],
    }

    for fname, plaus in scored_fields.items():
        ts.field_scores[fname] = _score_field(rows, fname, plaus)

    # Consistency: ptv_min < ptv_max
    check = ConsistencyCheck(check_name="ptv_min_lt_max")
    for row in rows:
        if row["ptv_min_kg"] is not None and row["ptv_max_kg"] is not None:
            check.total += 1
            if row["ptv_min_kg"] < row["ptv_max_kg"]:
                check.passed += 1
            elif len(check.failures) < 5:
                check.failures.append(
                    f"size {row['id']}: {row['ptv_min_kg']}–{row['ptv_max_kg']}"
                )
    if check.total > 0:
        ts.consistency_checks.append(check)

    # Consistency: flat_area ≈ flat_span² / flat_aspect_ratio (within 5%)
    check2 = ConsistencyCheck(check_name="flat_area_span_ar_consistent")
    for row in rows:
        area = row["flat_area_m2"]
        span = row["flat_span_m"]
        ar = row["flat_aspect_ratio"]
        if area and span and ar and ar > 0:
            check2.total += 1
            computed = (span ** 2) / ar
            if abs(computed - area) / area <= 0.05:
                check2.passed += 1
            elif len(check2.failures) < 5:
                check2.failures.append(
                    f"size {row['id']}: area={area}, span²/AR={computed:.2f}"
                )
    if check2.total > 0:
        ts.consistency_checks.append(check2)

    # Consistency: proj_area ≈ proj_span² / proj_aspect_ratio (within 5%)
    check3 = ConsistencyCheck(check_name="proj_area_span_ar_consistent")
    for row in rows:
        area = row["proj_area_m2"]
        span = row["proj_span_m"]
        ar = row["proj_aspect_ratio"]
        if area and span and ar and ar > 0:
            check3.total += 1
            computed = (span ** 2) / ar
            if abs(computed - area) / area <= 0.05:
                check3.passed += 1
            elif len(check3.failures) < 5:
                check3.failures.append(
                    f"size {row['id']}: area={area}, span²/AR={computed:.2f}"
                )
    if check3.total > 0:
        ts.consistency_checks.append(check3)

    # Consistency: projected < flat (area and span)
    check4 = ConsistencyCheck(check_name="proj_lt_flat_area")
    for row in rows:
        fa = row["flat_area_m2"]
        pa = row["proj_area_m2"]
        if fa and pa:
            check4.total += 1
            if pa < fa:
                check4.passed += 1
            elif len(check4.failures) < 5:
                check4.failures.append(
                    f"size {row['id']}: proj={pa} >= flat={fa}"
                )
    if check4.total > 0:
        ts.consistency_checks.append(check4)

    return ts


def _score_certifications(conn: sqlite3.Connection) -> TableScore:
    """Score the certifications table."""
    rows = conn.execute("SELECT * FROM certifications").fetchall()
    ts = TableScore(table_name="certifications", record_count=len(rows))

    ts.field_scores["standard"] = _score_field(rows, "standard")
    ts.field_scores["classification"] = _score_field(rows, "classification")
    ts.field_scores["test_lab"] = _score_field(rows, "test_lab")
    ts.field_scores["report_url"] = _score_field(rows, "report_url")
    ts.field_scores["test_date"] = _score_field(rows, "test_date")

    # Consistency: classification matches expected values for standard
    en_classes = {"A", "B", "C", "D"}
    check = ConsistencyCheck(check_name="classification_valid_for_standard")
    for row in rows:
        if row["standard"] == "EN" and row["classification"]:
            check.total += 1
            if row["classification"] in en_classes:
                check.passed += 1
            elif len(check.failures) < 5:
                check.failures.append(
                    f"cert {row['id']}: EN/{row['classification']}"
                )
    if check.total > 0:
        ts.consistency_checks.append(check)

    return ts


def _score_performance(conn: sqlite3.Connection) -> TableScore:
    """Score the performance_data table."""
    rows = conn.execute("SELECT * FROM performance_data").fetchall()
    ts = TableScore(table_name="performance_data", record_count=len(rows))

    scored_fields = {
        "speed_trim_kmh":   PLAUSIBILITY["speed_trim_kmh"],
        "speed_max_kmh":    PLAUSIBILITY["speed_max_kmh"],
        "glide_ratio_best": PLAUSIBILITY["glide_ratio_best"],
        "min_sink_ms":      PLAUSIBILITY["min_sink_ms"],
    }

    for fname, plaus in scored_fields.items():
        ts.field_scores[fname] = _score_field(rows, fname, plaus)

    # Consistency: trim speed < max speed
    check = ConsistencyCheck(check_name="trim_lt_max_speed")
    for row in rows:
        trim = row["speed_trim_kmh"]
        maxs = row["speed_max_kmh"]
        if trim and maxs:
            check.total += 1
            if trim < maxs:
                check.passed += 1
            elif len(check.failures) < 5:
                check.failures.append(
                    f"perf {row['id']}: trim={trim} >= max={maxs}"
                )
    if check.total > 0:
        ts.consistency_checks.append(check)

    return ts
