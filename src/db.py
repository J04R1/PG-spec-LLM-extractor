"""
SQLite storage layer — schema v2.

7-table schema: manufacturers, models, model_target_uses, size_variants,
performance_data, certifications, provenance.

Uses upsert logic: create if missing, update only NULL fields.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    Certification,
    Manufacturer,
    ModelTargetUse,
    PerformanceData,
    Provenance,
    SizeVariant,
    TargetUse,
    WingModel,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manufacturers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    slug         TEXT    UNIQUE NOT NULL,
    country_code TEXT,
    website      TEXT,
    logo_url     TEXT,
    created_at   TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at   TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS models (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id   INTEGER NOT NULL REFERENCES manufacturers(id),
    name              TEXT    NOT NULL,
    slug              TEXT    UNIQUE NOT NULL,
    category          TEXT    NOT NULL CHECK(category IN (
                        'paraglider','tandem','miniwing','single_skin',
                        'acro','speedwing','paramotor'
                      )),
    year_released     INTEGER,
    year_discontinued INTEGER,
    is_current        INTEGER DEFAULT 1,
    cell_count        INTEGER,
    riser_config      TEXT,
    manufacturer_url  TEXT,
    created_at        TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS model_target_uses (
    model_id    INTEGER NOT NULL REFERENCES models(id),
    target_use  TEXT    NOT NULL CHECK(target_use IN (
                  'school','leisure','xc','competition',
                  'hike_and_fly','vol_biv','acro','speedflying'
                )),
    PRIMARY KEY (model_id, target_use)
);

CREATE TABLE IF NOT EXISTS size_variants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    size_label          TEXT    NOT NULL,
    flat_area_m2        REAL,
    flat_span_m         REAL,
    flat_aspect_ratio   REAL,
    proj_area_m2        REAL,
    proj_span_m         REAL,
    proj_aspect_ratio   REAL,
    wing_weight_kg      REAL,
    ptv_min_kg          REAL,
    ptv_max_kg          REAL,
    line_length_m       REAL,
    created_at          TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(model_id, size_label)
);

CREATE TABLE IF NOT EXISTS performance_data (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    size_variant_id   INTEGER NOT NULL REFERENCES size_variants(id),
    speed_trim_kmh    REAL,
    speed_max_kmh     REAL,
    glide_ratio_best  REAL,
    min_sink_ms       REAL,
    source_type       TEXT    NOT NULL DEFAULT 'manufacturer_stated'
                      CHECK(source_type IN (
                        'manufacturer_stated','test_report','independent_test'
                      )),
    created_at        TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS certifications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    size_variant_id  INTEGER NOT NULL REFERENCES size_variants(id),
    standard         TEXT    NOT NULL CHECK(standard IN (
                       'EN','LTF','AFNOR','DGAC','CCC','other'
                     )),
    classification   TEXT,
    ptv_min_kg       REAL,
    ptv_max_kg       REAL,
    test_lab         TEXT,
    report_number    TEXT,
    report_url       TEXT,
    test_date        TEXT,
    status           TEXT    DEFAULT 'active'
                     CHECK(status IN ('active','expired','revoked')),
    created_at       TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS provenance (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id           INTEGER NOT NULL REFERENCES models(id),
    source_name        TEXT    NOT NULL,
    source_url         TEXT,
    accessed_at        TEXT,
    extraction_method  TEXT,
    notes              TEXT,
    created_at         TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


class Database:
    """SQLite database improving the OpenParaglider production schema."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open connection and initialize schema."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # ── Upsert operations ──────────────────────────────────────────────────

    def upsert_manufacturer(self, mfr: Manufacturer) -> int:
        """Insert or find existing manufacturer by slug. Returns id."""
        row = self.conn.execute(
            "SELECT id FROM manufacturers WHERE slug = ?", (mfr.slug,)
        ).fetchone()
        if row:
            return row["id"]

        cur = self.conn.execute(
            "INSERT INTO manufacturers (name, slug, country_code, website) VALUES (?, ?, ?, ?)",
            (mfr.name, mfr.slug, mfr.country_code, mfr.website),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_model(self, model: WingModel, manufacturer_id: int) -> int:
        """Insert or update model by slug. Fills NULL fields from new data. Returns id."""
        row = self.conn.execute(
            "SELECT * FROM models WHERE slug = ?", (model.slug,)
        ).fetchone()
        if row:
            # Update NULL fields with new non-NULL values
            updates: list[str] = []
            values: list = []
            fill_fields = {
                "year_released": model.year_released,
                "year_discontinued": model.year_discontinued,
                "cell_count": model.cell_count,
                "riser_config": model.riser_config,
                "manufacturer_url": model.manufacturer_url,
            }
            for col, new_val in fill_fields.items():
                if row[col] is None and new_val is not None:
                    updates.append(f"{col} = ?")
                    values.append(new_val)
            # is_current: upgrade from 0→1 if new data says current
            if row["is_current"] == 0 and model.is_current:
                updates.append("is_current = ?")
                values.append(1)
            if updates:
                updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
                values.append(row["id"])
                self.conn.execute(
                    f"UPDATE models SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                self.conn.commit()
            return row["id"]

        cur = self.conn.execute(
            """INSERT INTO models
            (manufacturer_id, name, slug, category, year_released,
             year_discontinued, is_current, cell_count,
             riser_config, manufacturer_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                manufacturer_id,
                model.name,
                model.slug,
                model.category.value if model.category else "paraglider",
                model.year_released,
                model.year_discontinued,
                1 if model.is_current else 0,
                model.cell_count,
                model.riser_config,
                model.manufacturer_url,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_model_target_use(self, model_id: int, target_use: TargetUse) -> None:
        """Insert a target use for a model (ignore if already exists)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO model_target_uses (model_id, target_use) VALUES (?, ?)",
            (model_id, target_use.value),
        )
        self.conn.commit()

    def upsert_size_variant(self, sv: SizeVariant, model_id: int) -> int:
        """Insert or update size variant by model_id + size_label. Fills NULL fields. Returns id."""
        row = self.conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ? AND size_label = ?",
            (model_id, sv.size_label),
        ).fetchone()
        if row:
            updates: list[str] = []
            values: list = []
            fill_fields = {
                "flat_area_m2": sv.flat_area_m2,
                "flat_span_m": sv.flat_span_m,
                "flat_aspect_ratio": sv.flat_aspect_ratio,
                "proj_area_m2": sv.proj_area_m2,
                "proj_span_m": sv.proj_span_m,
                "proj_aspect_ratio": sv.proj_aspect_ratio,
                "wing_weight_kg": sv.wing_weight_kg,
                "ptv_min_kg": sv.ptv_min_kg,
                "ptv_max_kg": sv.ptv_max_kg,
                "line_length_m": sv.line_length_m,
            }
            for col, new_val in fill_fields.items():
                if row[col] is None and new_val is not None:
                    updates.append(f"{col} = ?")
                    values.append(new_val)
            if updates:
                updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
                values.append(row["id"])
                self.conn.execute(
                    f"UPDATE size_variants SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                self.conn.commit()
            return row["id"]

        cur = self.conn.execute(
            """INSERT INTO size_variants
            (model_id, size_label, flat_area_m2, flat_span_m, flat_aspect_ratio,
             proj_area_m2, proj_span_m, proj_aspect_ratio,
             wing_weight_kg, ptv_min_kg, ptv_max_kg, line_length_m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_id,
                sv.size_label,
                sv.flat_area_m2,
                sv.flat_span_m,
                sv.flat_aspect_ratio,
                sv.proj_area_m2,
                sv.proj_span_m,
                sv.proj_aspect_ratio,
                sv.wing_weight_kg,
                sv.ptv_min_kg,
                sv.ptv_max_kg,
                sv.line_length_m,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def insert_performance_data(self, perf: PerformanceData, size_variant_id: int) -> int:
        """Insert a performance data record. Returns id."""
        cur = self.conn.execute(
            """INSERT INTO performance_data
            (size_variant_id, speed_trim_kmh, speed_max_kmh,
             glide_ratio_best, min_sink_ms, source_type)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                size_variant_id,
                perf.speed_trim_kmh,
                perf.speed_max_kmh,
                perf.glide_ratio_best,
                perf.min_sink_ms,
                perf.source_type.value,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_certification(self, cert: Certification, size_variant_id: int) -> int:
        """Insert or replace a certification record for a size variant.

        Replaces any existing cert with the same (size_variant_id, standard).
        """
        std_val = cert.standard.value if cert.standard else None

        # Check for existing cert with same standard on this size
        row = self.conn.execute(
            "SELECT id FROM certifications WHERE size_variant_id = ? AND standard = ?",
            (size_variant_id, std_val),
        ).fetchone()

        if row:
            self.conn.execute(
                """UPDATE certifications
                SET classification = ?, ptv_min_kg = ?, ptv_max_kg = ?,
                    test_lab = ?, report_number = ?, report_url = ?,
                    test_date = ?, status = ?
                WHERE id = ?""",
                (
                    cert.classification,
                    cert.ptv_min_kg,
                    cert.ptv_max_kg,
                    cert.test_lab,
                    cert.report_number,
                    cert.report_url,
                    str(cert.test_date) if cert.test_date else None,
                    cert.status.value,
                    row["id"],
                ),
            )
            self.conn.commit()
            return row["id"]

        cur = self.conn.execute(
            """INSERT INTO certifications
            (size_variant_id, standard, classification,
             ptv_min_kg, ptv_max_kg, test_lab, report_number,
             report_url, test_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                size_variant_id,
                std_val,
                cert.classification,
                cert.ptv_min_kg,
                cert.ptv_max_kg,
                cert.test_lab,
                cert.report_number,
                cert.report_url,
                str(cert.test_date) if cert.test_date else None,
                cert.status.value,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # Backward compat alias
    insert_certification = upsert_certification

    def delete_certifications_for_size(self, size_variant_id: int) -> int:
        """Delete all certification records for a size variant. Returns count deleted."""
        cur = self.conn.execute(
            "DELETE FROM certifications WHERE size_variant_id = ?",
            (size_variant_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def insert_provenance(self, prov: Provenance, model_id: int) -> int:
        """Insert a provenance record. Returns id."""
        cur = self.conn.execute(
            """INSERT INTO provenance
            (model_id, source_name, source_url, accessed_at,
             extraction_method, notes)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                model_id,
                prov.source_name,
                prov.source_url,
                str(prov.accessed_at) if prov.accessed_at else None,
                prov.extraction_method,
                prov.notes,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Convenience ────────────────────────────────────────────────────────

    def record_provenance(
        self,
        model_id: int,
        source_url: str | None,
        manufacturer_slug: str,
        extraction_method: str = "llm_qwen25_3b",
    ) -> None:
        """Record a provenance entry for a model."""
        self.insert_provenance(
            Provenance(
                source_name=f"manufacturer_{manufacturer_slug}",
                source_url=source_url,
                extraction_method=extraction_method,
            ),
            model_id,
        )
