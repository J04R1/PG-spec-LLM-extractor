# Paraglider Specs Extraction Pipeline
**Technical Specification — v1.0**
March 2026 | Standalone Pipeline Tool

---

## 1. Purpose & Scope

This document specifies the architecture, components, and implementation details of a standalone data pipeline that crawls paraglider manufacturer websites, extracts structured product specifications using an LLM, and stores normalized records in a local database.

The pipeline is intentionally isolated from any existing consumer applications. Downstream apps read the resulting database directly — they are never coupled to the pipeline's internals.

> **Design Principle:** The LLM layer is swappable by design. Phase 1 uses Ollama + Qwen2.5 locally. Future phases can substitute Claude API, GPT-4o, or any model with an OpenAI-compatible endpoint — with zero changes to the pipeline logic.

---

## 2. Architecture Overview

| Layer | Component | Purpose |
|-------|-----------|---------|
| Crawl | Crawl4AI + Playwright | Fetch & render JS-heavy manufacturer pages into clean markdown |
| Config | YAML per manufacturer | URLs, CSS hints, extraction overrides per brand |
| Extract | LLM via adapter | Parse markdown into structured JSON using a defined schema |
| Normalize | Python rules + LLM | Unify certifications, sizes, units across brands |
| Store | SQLite / Postgres | Append-safe, crash-resilient output |
| Import | import_enrichment_csv.py | Push finalized records into the main application DB |

### 2.1 Data Flow

```
Manufacturer YAML config
        |
        v
  Crawl4AI (Playwright)  -->  raw markdown / HTML
        |
        v
  LLM Extraction Layer   -->  output/<brand>_raw.json   (incremental, crash-safe)
        |
        v
  Normalization Rules    -->  output/<brand>_enrichment.csv
        |
        v
  import_enrichment_csv.py  -->  Application Database
```

---

## 3. LLM Adapter — Swappable Design

All LLM calls are routed through a single `LLMAdapter` class. Switching models requires only a config change — no pipeline code changes.

### 3.1 Adapter Interface

```python
class LLMAdapter:
    def extract(self, markdown: str, schema: dict) -> dict:
        raise NotImplementedError

class OllamaAdapter(LLMAdapter):      # Phase 1 — local
    model = 'qwen2.5:7b'              # or phi3.5, qwen2.5:3b
    endpoint = 'http://localhost:11434/api/chat'

class ClaudeAdapter(LLMAdapter):      # Phase 2 — cloud
    model = 'claude-sonnet-4-20250514'
    endpoint = 'https://api.anthropic.com/v1/messages'

class OpenAIAdapter(LLMAdapter):      # Phase 2 alt — cloud
    model = 'gpt-4o-mini'
```

### 3.2 Model Selection by Hardware

| Hardware Profile | Recommended Model | RAM Required | Speed |
|-----------------|-------------------|--------------|-------|
| 8 GB RAM, no GPU (current) | Qwen2.5:3B or Phi-3.5 Mini | ~3-4 GB | Slow — batch overnight |
| 16 GB RAM, no GPU | Qwen2.5:7B | ~6-8 GB | Moderate |
| 16 GB RAM + 8GB VRAM GPU | Qwen2.5:7B (GPU) | ~6-8 GB | Fast |
| Any — cloud API | Claude Sonnet / GPT-4o-mini | None local | Fast + accurate |

> **Phase 1 Recommendation:** Use `Qwen2.5:3B` via Ollama on current hardware. The pipeline runs ad-hoc (monthly), so overnight batch speed is acceptable. Switch to Claude API when extraction accuracy needs improvement.

---

## 4. Extraction Schema

The target schema is defined as a Pydantic model and passed to the LLM adapter as a JSON schema. The LLM is instructed to fill all fields and normalize values to the canonical forms below.

### 4.1 Paraglider Record Schema

```python
class ParagliderSpec(BaseModel):
    brand:            str         # e.g. 'Ozone', 'Nova', 'Advance'
    model_name:       str         # e.g. 'Rush 6', 'Ion 7'
    year:             int | None  # year of production/release
    certification:    str         # canonical: EN-A / EN-B / EN-C / EN-D / CCC
    sizes:            list[str]   # canonical: ['XS','S','M','L','XL']
    pilot_weight_min: float | None  # kg, lower bound for any size
    pilot_weight_max: float | None  # kg, upper bound for any size
    glider_weight:    float | None  # kg, glider only
    aspect_ratio:     float | None
    cells:            int | None
    category:         str | None  # 'paraglider' | 'speedwing' | 'tandem'
    source_url:       str         # original page URL
    extracted_at:     datetime
```

### 4.2 Certification Normalization Map

| Raw value (examples) | Canonical output |
|----------------------|-----------------|
| EN-A, EN A, LTF A, DHV 1, A | EN-A |
| EN-B, EN B, LTF B, DHV 1-2, B | EN-B |
| EN-C, EN C, LTF C, DHV 2, DHV 2-3, C | EN-C |
| EN-D, EN D, DHV 3, D | EN-D |
| CCC, CIVL CCC | CCC |

### 4.3 Size Normalization Map

| Raw value (examples) | Canonical output |
|----------------------|-----------------|
| XS, Extra Small, 1, 18, 70 | XS |
| S, Small, 2, 19, 75, SM | S |
| M, Medium, 3, 20, 80, MD | M |
| L, Large, 4, 21, 85, LG | L |
| XL, Extra Large, 5, 22, 90 | XL |

---

## 5. Manufacturer Configuration

Each manufacturer is defined in a YAML file. This isolates per-brand crawl logic from pipeline code. Adding a new brand requires only a new YAML file — no code changes.

### 5.1 YAML Config Structure

```yaml
# config/manufacturers/ozone.yaml
brand: Ozone
base_url: https://www.flyozone.com
product_listing_url: https://www.flyozone.com/paragliders/
extraction_strategy: llm          # 'llm' | 'css'
css_selectors:                    # optional hints for CSS strategy
  model_name: h1.product-title
  certification: span.cert-badge
llm_hints: |                      # extra context injected into extraction prompt
  Ozone lists sizes as numbers (1-5). Map: 1=XS 2=S 3=M 4=L 5=XL.
  Certification is shown as 'EN B' without hyphen.
crawl_depth: 2                    # follow product links 2 levels deep
rate_limit_ms: 1500               # polite delay between requests
```

---

## 6. Project Structure

```
paraglider-pipeline/
  config/
    manufacturers/
      ozone.yaml
      nova.yaml
      advance.yaml
      ...                         # one file per brand
  src/
    crawler.py                    # Crawl4AI wrapper
    adapters/
      base.py                     # LLMAdapter interface
      ollama.py                   # Ollama local adapter
      claude.py                   # Anthropic API adapter
      openai.py                   # OpenAI-compatible adapter
    extractor.py                  # schema + prompt logic
    normalizer.py                 # post-extraction normalization rules
    db.py                         # SQLite write layer
    pipeline.py                   # orchestrator (CLI entry point)
  output/                         # gitignored
    ozone_raw.json                # incremental, crash-safe
    ozone_enrichment.csv
    ...
  scripts/
    import_enrichment_csv.py      # push to application DB
  .env                            # CLAUDE_API_KEY, OLLAMA_HOST, etc.
  pyproject.toml
  README.md
```

---

## 7. Dependencies

| Package | Purpose | Phase |
|---------|---------|-------|
| `crawl4ai` | Web crawling + JS rendering (wraps Playwright) | 1+ |
| `pyyaml` | Read manufacturer YAML config files | 1+ |
| `pydantic` | Schema definition + validation | 1+ |
| `httpx` | HTTP client for LLM adapter calls | 1+ |
| `ollama` (optional) | Python client for local Ollama server | 1 |
| `anthropic` (optional) | Claude API client | 2+ |
| `sqlite3` (stdlib) | Local storage — no setup required | 1+ |
| `python-dotenv` | Load .env config for API keys | 1+ |
| `typer` | CLI interface (run, reset, status commands) | 1+ |

---

## 8. CLI Usage

```bash
# Run full pipeline for all configured manufacturers
python -m pipeline run --all

# Run for a single brand
python -m pipeline run --manufacturer ozone

# Run with explicit model override
python -m pipeline run --all --adapter claude
python -m pipeline run --all --adapter ollama --model qwen2.5:3b

# Check extraction status
python -m pipeline status

# Import finalized CSVs to application DB
python scripts/import_enrichment_csv.py --all
```

---

## 9. Delivery Phases

| Phase | Scope | LLM | Status |
|-------|-------|-----|--------|
| 1 — MVP | 3-5 manufacturers, SQLite output, CLI | Ollama / Qwen2.5:3B local | Build now |
| 2 — Expand | 20+ manufacturers, prompt refinement, CSV export | Ollama or Claude API | After Phase 1 validation |
| 3 — Fine-tune | QLoRA fine-tune on accumulated labeled examples | Custom local model | When 500+ labeled records exist |
| 4 — Automate | Monthly cron / webhook trigger, delta detection | TBD | Post Phase 2 |

---

## 10. Out of Scope

- Any user-facing frontend or API — this is a backend pipeline only
- Real-time or on-demand crawling — runs are batch and ad-hoc
- Authentication-gated pages (manufacturer portals, dealer logins)
- Image or video extraction from product pages
- Distributed or multi-machine execution

---

*Paraglider Extraction Pipeline — Technical Spec v1.0 | March 2026*
