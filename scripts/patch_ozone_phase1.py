"""One-shot patch for Ozone Phase 1 DB issues — Iteration 20."""
import sqlite3

conn = sqlite3.connect('output/ozone.db')
cur = conn.cursor()

# 1. Fix categories
fixes = {
    'ozone-session':    'acro',
    'ozone-swiftmax-2': 'tandem',
    'ozone-wisp-2':     'tandem',
    'ozone-magnum-4':   'tandem',
}
for slug, cat in fixes.items():
    cur.execute("UPDATE models SET category=? WHERE slug=?", (cat, slug))
    print(f"  category: {slug} -> {cat} ({cur.rowcount})")

# 2. Fix year_released for all 22 current models
years = {
    'ozone-moxie': 2021, 'ozone-alta-gt': 2025, 'ozone-buzz-z7': 2023,
    'ozone-geo-7': 2023, 'ozone-rush-6': 2022, 'ozone-swift-6': 2023,
    'ozone-delta-5': 2025, 'ozone-alpina-4-gt': 2025, 'ozone-alpina-5': 2025,
    'ozone-photon': 2023, 'ozone-lyght': 2024, 'ozone-zeolite-2-gt': 2024,
    'ozone-zeolite-2': 2023, 'ozone-zeno-2': 2022, 'ozone-enzo-3': 2019,
    'ozone-ultralite-5': 2023, 'ozone-session': 2022, 'ozone-magnum-4': 2022,
    'ozone-swiftmax-2': 2022, 'ozone-wisp-2': 2023, 'ozone-vibe-gt': 2025,
    'ozone-roadrunner': 2021,
}
for slug, yr in years.items():
    cur.execute("UPDATE models SET year_released=? WHERE slug=?", (yr, slug))
print(f"  years: {len(years)} models updated")

# 3. Remove bogus '-' certifications (Ultralite 5 smallest sizes have no EN cert)
cur.execute("DELETE FROM certifications WHERE classification='-'")
print(f"  bogus '-' certs deleted: {cur.rowcount}")

# 4. Insert / fix Roadrunner
cur.execute("SELECT id FROM manufacturers WHERE slug='ozone'")
mfr_id = cur.fetchone()[0]
cur.execute("SELECT id FROM models WHERE slug='ozone-roadrunner'")
rr = cur.fetchone()
if not rr:
    cur.execute(
        "INSERT INTO models (manufacturer_id, name, slug, category, cell_count, "
        "is_current, year_released, manufacturer_url) "
        "VALUES (?, 'Roadrunner', 'ozone-roadrunner', 'paraglider', 27, 1, 2021, "
        "'https://flyozone.com/paragliders/products/gliders/roadrunner')",
        (mfr_id,)
    )
    model_id = cur.lastrowid
    print(f"  roadrunner: inserted (id={model_id})")
else:
    model_id = rr[0]
    cur.execute(
        "UPDATE models SET cell_count=27, year_released=2021, is_current=1, "
        "manufacturer_url='https://flyozone.com/paragliders/products/gliders/roadrunner' "
        "WHERE id=?",
        (model_id,)
    )
    print(f"  roadrunner: updated (id={model_id})")

cur.execute("SELECT id FROM size_variants WHERE model_id=?", (model_id,))
if not cur.fetchone():
    cur.execute(
        "INSERT INTO size_variants (model_id, size_label, flat_area_m2, flat_span_m, "
        "flat_aspect_ratio, proj_area_m2, proj_span_m, proj_aspect_ratio, wing_weight_kg) "
        "VALUES (?, 'OS', 14.0, 7.74, 4.3, 12.1, 6.06, 3.0, 3.0)",
        (model_id,)
    )
    print(f"  roadrunner: size variant inserted (sv_id={cur.lastrowid})")
else:
    print("  roadrunner: size variant already exists")

cur.execute("SELECT id FROM provenance WHERE model_id=?", (model_id,))
if not cur.fetchone():
    cur.execute(
        "INSERT INTO provenance (model_id, source_name, source_url, extraction_method) "
        "VALUES (?, 'Ozone website', "
        "'https://flyozone.com/paragliders/products/gliders/roadrunner', "
        "'manual_patch_iter20')",
        (model_id,)
    )
    print("  roadrunner: provenance inserted")

conn.commit()
conn.close()
print("\nAll patches committed.")
