# End-to-end test suites

Two standalone scripts that exercise the API in-process via FastAPI's
`TestClient` (full middleware + routing + real OCR/redaction/Bates logic and
shared pipeline state). They build their own fixtures (PDFs, locked PDFs,
images) in memory — no external files needed.

- `rlg_e2e.py` — core happy-path coverage of every tool + the full pipeline
  (scan → run → re-redact → finalize → download). 19 checks.
- `rlg_edge.py` — edge cases: input validation, redaction false-positive
  guards, pipeline error paths, locked-file unlock, auth enforcement, format
  edges. 36 checks.

## Running

Requires the project dependencies, including `onnxtr` (for OCR) — the same set
as `requirements.txt`, plus `httpx` (pulled in by `TestClient`):

```bash
# from the repo root, in a venv with requirements installed
pip install httpx                 # if not already present
python tests/rlg_e2e.py
python tests/rlg_edge.py
```

Each script prints `[PASS]/[FAIL]` per check and a summary line, and exits
non-zero if anything fails. No server needs to be running — `TestClient`
drives the ASGI app directly.

Auth is exercised by monkeypatching `main._API_KEY`; the scripts leave it unset
(disabled) otherwise. The first run downloads/loads the OCR models, so it takes
a bit longer.
