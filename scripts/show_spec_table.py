"""Print a model's spec table matching the Ozone website format.

Usage:
    python3 scripts/show_spec_table.py ozone-rush-6
    python3 scripts/show_spec_table.py ozone-moxie
"""
import sqlite3
import sys

DB_PATH = "output/ozone.db"

def show_table(slug: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, name, cell_count FROM models WHERE slug=?", (slug,))
    model = cur.fetchone()
    if not model:
        print(f"Model not found: {slug}")
        sys.exit(1)

    cur.execute(
        "SELECT id, size_label FROM size_variants WHERE model_id=? ORDER BY id",
        (model["id"],)
    )
    sizes = cur.fetchall()
    size_labels = [r["size_label"] for r in sizes]
    sv_ids      = [r["id"]         for r in sizes]

    rows_data = {}
    for sv_id, label in zip(sv_ids, size_labels):
        cur.execute("SELECT * FROM size_variants WHERE id=?", (sv_id,))
        sv = dict(cur.fetchone())
        cur.execute(
            "SELECT classification FROM certifications WHERE size_variant_id=?",
            (sv_id,)
        )
        cert = cur.fetchone()
        sv["certification"] = cert[0] if cert else "—"
        rows_data[label] = sv

    conn.close()

    fields = [
        ("Number of Cells",            lambda sv: str(model["cell_count"])),
        ("Projected Area (m²)",         lambda sv: str(sv["proj_area_m2"])),
        ("Flat Area (m²)",              lambda sv: str(sv["flat_area_m2"])),
        ("Projected Span (m)",          lambda sv: str(sv["proj_span_m"])),
        ("Flat Span (m)",               lambda sv: str(sv["flat_span_m"])),
        ("Projected Aspect Ratio",      lambda sv: str(sv["proj_aspect_ratio"])),
        ("Flat Aspect Ratio",           lambda sv: str(sv["flat_aspect_ratio"])),
        ("Glider Weight (kg)",          lambda sv: str(sv["wing_weight_kg"])),
        ("Certified Weight Range (kg)", lambda sv:
            f"{sv['ptv_min_kg']:.0f}-{sv['ptv_max_kg']:.0f}"
            if sv["ptv_min_kg"] else "—"),
        ("Certification",               lambda sv: sv["certification"]),
    ]

    col_w   = 10
    label_w = 32
    print(f"\n  {model['name'].upper()}\n")
    header = f"{'SIZES':<{label_w}}" + "".join(f"{s:>{col_w}}" for s in size_labels)
    print(header)
    print("─" * (label_w + col_w * len(size_labels)))
    for field_label, fn in fields:
        row = f"{field_label:<{label_w}}"
        for slabel in size_labels:
            row += f"{fn(rows_data[slabel]):>{col_w}}"
        print(row)
    print()


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "ozone-rush-6"
    show_table(slug)
