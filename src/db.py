"""
SQLite storage layer — production-aligned schema.

Matches the OpenParaglider production Postgres schema exactly:
  manufacturers, models, size_variants, certifications, data_sources

Uses upsert logic: create if missing, update only NULL fields.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    Certification,
    DataSource,
    EntityType,
    Manufacturer,
    SizeVariant,
    WingModel,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manufacturers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    slug        TEXT    UNIQUE NOT NULL,
    country     TEXT,
    website     TEXT,
    logo_url    TEXT,
    created_at  TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS models (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name            TEXT    NOT NULL,
    slug            TEXT    UNIQUE NOT NULL,
    category        TEXT    CHECK(category IN ('paraglider','tandem','miniwing','single_skin','acro','speedwing','paramotor')),
    target_use      TEXT    CHECK(target_use IN ('school','leisure','xc','competition','hike_and_fly','vol_biv','acro','tandem')),
    year            INTEGER,
    is_current      INTEGER DEFAULT 1,
    cell_count      INTEGER,
    line_material   TEXT,
    riser_config    TEXT,
    manufacturer_url TEXT,
    description     TEXT,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS size_variants (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id           INTEGER NOT NULL REFERENCES models(id),
    size_label         TEXT    NOT NULL,
    flat_area_m2       REAL,
    flat_span_m        REAL,
    flat_aspect_ratio  REAL,
    proj_area_m2       REAL,
    proj_span_m        REAL,
    proj_aspect_ratio  REAL,
    wing_weight_kg     REAL,
    ptv_min_kg         REAL,
    ptv_max_kg         REAL,
    speed_trim_kmh     REAL,
    speed_max_kmh      REAL,
    glide_ratio_best   REAL,
    min_sink_ms        REAL,
    created_at         TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at         TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS certifications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    size_variant_id  INTEGER NOT NULL REFERENCES size_variants(id),
    standard         TEXT    CHECK(standard IN ('EN','LTF','AFNOR','DGAC','CCC','other')),
    classification   TEXT,
    test_lab         TEXT,
    test_report_url  TEXT,
    test_date        TEXT,
    created_at       TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS data_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT    NOT NULL CHECK(entity_type IN ('manufacturer','model','size_variant','certification')),
    entity_id       INTEGER NOT NULL,
    source_name     TEXT    NOT NULL,
    source_url      TEXT,
    contributed_by  TEXT,
    verified        INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


class Database:
    """SQLite database matching the OpenParaglider production schema."""

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
            "INSERT INTO manufacturers (name, slug, country, website) VALUES (?, ?, ?, ?)",
            (mfr.name, mfr.slug, mfr.country, mfr.website),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_model(self, model: WingModel, manufacturer_id: int) -> int:
        """Insert or find existing model by slug. Returns id."""
        row = self.conn.execute(
            "SELECT id FROM models WHERE slug = ?", (model.slug,)
        ).fetchone()
        if row:
            return row["id"]

        cur = self.conn.execute(
            """INSERT INTO models
            (manufacturer_id, name, slug, category, target_use, year,
             is_current, cell_count, line_material, riser_config,
             manufacturer_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                manufacturer_id,
                model.name,
                model.slug,
                model.category.value if model.category else None,
                model.target_use.value if model.target_use else None,
                model.year,
                1 if model.is_current else 0,
                model.cell_count,
                model.line_material,
                model.riser_config,
                model.manufacturer_url,
                model.description,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_size_variant(self, sv: SizeVariant, model_id: int) -> int:
        """Insert or find existing size variant by model_id + size_label. Returns id."""
        row = self.conn.execute(
            "SELECT id FROM size_variants WHERE model_id = ? AND size_label = ?",
            (model_id, sv.size_label),
        ).fetchone()
        if row:
            return row["id"]

        cur = self.conn.execute(
            """INSERT INTO size_variants
            (model_id, size_label, flat_area_m2, flat_span_m, flat_aspect_ratio,
             proj_area_m2, proj_span_m, proj_aspect_ratio,
             wing_weight_kg, ptv_min_kg, ptv_max_kg,
             speed_trim_kmh, speed_max_kmh, glide_ratio_best, min_sink_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                sv.speed_trim_kmh,
                sv.speed_max_kmh,
                sv.glide_ratio_best,
                sv.min_sink_ms,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def insert_certification(self, cert: Certification, size_variant_id: int) -> int:
        """Insert a certification record. Returns id."""
        cur = self.conn.execute(
            """INSERT INTO certifications
            (size_variant_id, standard, classification, test_lab, test_report_url, test_date)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                size_variant_id,
                cert.standard.value if cert.standard else None,
                cert.classification,
                cert.test_lab,
                cert.test_report_url,
                str(cert.test_date) if cert.test_date else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def insert_data_source(self, ds: DataSource) -> int:
        """Insert a provenance record. Returns id."""
        cur = self.conn.execute(
            """INSERT INTO data_sources
            (entity_type, entity_id, source_name, source_url, contributed_by, verified)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ds.entity_type.value,
                ds.entity_id,
                ds.source_name,
                ds.source_url,
                ds.contributed_by,
                1 if ds.verified else 0,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Convenience ────────────────────────────────────────────────────────

    def record_provenance(
        self,
        entity_type: EntityType,
        entity_id: int,
        source_url: str | None,
        manufacturer_slug: str,
    ) -> None:
        """Record a data_sources provenance entry for any entity."""
        self.insert_data_source(
            DataSource(
                entity_type=entity_type,
                entity_id=entity_id,
                source_name=f"manufacturer_{manufacturer_slug}",
                source_url=source_url,
                contributed_by="pg-spec-extractor",
                verified=False,
            )
        )
