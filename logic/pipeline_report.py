"""
Pipeline report accumulator and serializer.

Contains: PipelineReport dataclass that collects per-file results, timing,
settings, and a summary for a full pipeline run. Serializes to a compact
JSON blob that is embedded as ``_pipeline_report.json`` in the output ZIP.

This module has no FastAPI dependency — it is pure Python and can be used
from any context (tests, CLI, the /pipeline/run endpoint).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# File-level result record
# ---------------------------------------------------------------------------

@dataclass
class FileResult:
    """
    Tracks what happened to one file across every pipeline stage.

    Attributes:
        filename:     Original filename as it entered the pipeline.
        page_count:   Number of pages detected during the pre-flight scan.
                      None if the file is not a PDF or could not be read.
        stages_ok:    Ordered list of stage names that completed successfully
                      for this file (e.g. ["unlock", "ocr", "bates"]).
        stages_failed: Mapping of stage_name → failure reason for stages that
                       could not process this file. A file may partially succeed
                       (e.g. OCR ok, Bates failed).
        first_bates:  First Bates label applied to this file (if any).
        last_bates:   Last Bates label applied to this file (if any).
        skipped_bates: True if the file already carried a Bates stamp and was
                       passed through unchanged by the smart-skip logic.
        elapsed_s:    Total wall-clock seconds spent processing this file
                      across all stages. Populated by the caller.
    """
    filename: str
    page_count: Optional[int] = None
    stages_ok: List[str] = field(default_factory=list)
    stages_failed: Dict[str, str] = field(default_factory=dict)
    first_bates: Optional[str] = None
    last_bates: Optional[str] = None
    skipped_bates: bool = False
    elapsed_s: float = 0.0

    def mark_ok(self, stage: str) -> None:
        """Record that *stage* completed successfully for this file."""
        if stage not in self.stages_ok:
            self.stages_ok.append(stage)

    def mark_failed(self, stage: str, reason: str) -> None:
        """Record that *stage* failed for this file with the given reason."""
        self.stages_failed[stage] = reason

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON serialization."""
        return {
            "filename": self.filename,
            "page_count": self.page_count,
            "stages_ok": self.stages_ok,
            "stages_failed": self.stages_failed,
            "first_bates": self.first_bates,
            "last_bates": self.last_bates,
            "skipped_bates": self.skipped_bates,
            "elapsed_s": round(self.elapsed_s, 3),
        }


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------

@dataclass
class PipelineReport:
    """
    Accumulates the full story of a single /pipeline/run invocation.

    Usage pattern::

        report = PipelineReport(run_id="abc123")
        report.record_setting("bates_prefix", "RLG")
        report.start_stage("unlock")
        # ... do unlock work ...
        report.end_stage("unlock")
        # ... file-level calls on report.get_file(filename) ...
        report.finish()
        zip_bytes = report.to_json().encode()

    Attributes:
        run_id:          UUID or short token that identifies this run.
                         Stored in the report and used in the download URL.
        stages_run:      Ordered list of stage names that were attempted
                         (in execution order).
        settings:        Key/value dict of sanitized run parameters
                         (prefix, start_num, patterns, etc.) written into
                         the report so attorneys can audit what was applied.
        file_results:    Ordered list of FileResult objects (one per input
                         file, in the order they were processed).
        total_elapsed_s: Wall-clock seconds from report creation to
                         finish() call. Populated by finish().
        stage_elapsed_s: Per-stage timing. Keys are stage names.
        started_at:      ISO-8601 timestamp of when the pipeline started.
        finished_at:     ISO-8601 timestamp of when finish() was called.
        error:           If the whole pipeline aborted (not a per-file failure),
                         the error message is stored here.
    """
    run_id: str
    stages_run: List[str] = field(default_factory=list)
    settings: Dict[str, object] = field(default_factory=dict)
    file_results: List[FileResult] = field(default_factory=list)
    total_elapsed_s: float = 0.0
    stage_elapsed_s: Dict[str, float] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: _iso_now())
    finished_at: Optional[str] = None
    error: Optional[str] = None

    # Internal: track stage start times for elapsed calculation.
    _stage_start: Dict[str, float] = field(default_factory=dict, repr=False)
    _run_start: float = field(default_factory=time.monotonic, repr=False)

    # Internal: filename → FileResult lookup for O(1) per-file access.
    _file_index: Dict[str, FileResult] = field(default_factory=dict, repr=False)

    # -----------------------------------------------------------------
    # Settings
    # -----------------------------------------------------------------

    def record_setting(self, key: str, value: object) -> None:
        """
        Store a sanitized run parameter in the report.

        Sensitive values (passwords, raw regex) should be scrubbed by the
        caller before passing here — this dict is written verbatim to JSON.
        """
        self.settings[key] = value

    def record_settings(self, mapping: dict) -> None:
        """Convenience: record multiple settings at once."""
        self.settings.update(mapping)

    # -----------------------------------------------------------------
    # Stage timing
    # -----------------------------------------------------------------

    def start_stage(self, stage: str) -> None:
        """Mark the beginning of a pipeline stage."""
        if stage not in self.stages_run:
            self.stages_run.append(stage)
        self._stage_start[stage] = time.monotonic()

    def end_stage(self, stage: str) -> None:
        """Mark the end of a pipeline stage and record its elapsed time."""
        start = self._stage_start.pop(stage, None)
        if start is not None:
            self.stage_elapsed_s[stage] = round(time.monotonic() - start, 3)

    # -----------------------------------------------------------------
    # Per-file results
    # -----------------------------------------------------------------

    def get_file(self, filename: str) -> FileResult:
        """
        Return (or lazily create) the FileResult for *filename*.

        Call this whenever you want to record something about a specific
        file — OK, failure, Bates label, page count, etc.
        """
        if filename not in self._file_index:
            result = FileResult(filename=filename)
            self.file_results.append(result)
            self._file_index[filename] = result
        return self._file_index[filename]

    def record_file_ok(self, filename: str, stage: str) -> None:
        """Shorthand: mark *stage* successful for *filename*."""
        self.get_file(filename).mark_ok(stage)

    def record_file_failure(self, filename: str, stage: str, reason: str) -> None:
        """Shorthand: mark *stage* failed for *filename* with *reason*."""
        self.get_file(filename).mark_failed(stage, reason)

    def record_bates(self, filename: str, first: str, last: str, skipped: bool = False) -> None:
        """Record the Bates range assigned to *filename*."""
        fr = self.get_file(filename)
        fr.first_bates = first
        fr.last_bates = last
        fr.skipped_bates = skipped

    def record_page_count(self, filename: str, pages: int) -> None:
        """Store the detected page count for *filename*."""
        self.get_file(filename).page_count = pages

    def apply_failures(self, stage: str, failures: Dict[str, str]) -> None:
        """
        Bulk-import a failures dict (filename → reason) from a logic module.

        Each existing-or-new FileResult gets mark_failed(stage, reason).
        Call this after a stage returns its failures dict.
        """
        for filename, reason in failures.items():
            self.get_file(filename).mark_failed(stage, reason)

    # -----------------------------------------------------------------
    # Finish and serialize
    # -----------------------------------------------------------------

    def finish(self, error: Optional[str] = None) -> None:
        """
        Stamp the report as finished.

        Call once after all stages complete (or when aborting due to a
        top-level error). Sets finished_at and total_elapsed_s.
        """
        self.finished_at = _iso_now()
        self.total_elapsed_s = round(time.monotonic() - self._run_start, 3)
        if error:
            self.error = error

    # -----------------------------------------------------------------
    # Summary helpers (computed on demand)
    # -----------------------------------------------------------------

    @property
    def total_files(self) -> int:
        """Total number of input files that entered the pipeline."""
        return len(self.file_results)

    @property
    def fully_succeeded(self) -> int:
        """Files that completed every attempted stage without any failure."""
        return sum(1 for fr in self.file_results if not fr.stages_failed)

    @property
    def partially_failed(self) -> int:
        """Files that failed at least one stage (but were not entirely skipped)."""
        return sum(1 for fr in self.file_results if fr.stages_failed)

    @property
    def bates_range(self) -> Optional[str]:
        """
        Human-readable overall Bates range for the whole batch.

        Scans all FileResults to find the lowest first_bates and highest
        last_bates among non-skipped files. Returns None if no Bates stamps
        were applied at all.
        """
        firsts = [fr.first_bates for fr in self.file_results
                  if fr.first_bates and not fr.skipped_bates]
        lasts  = [fr.last_bates  for fr in self.file_results
                  if fr.last_bates  and not fr.skipped_bates]
        if not firsts:
            return None
        # Sort lexicographically — works for zero-padded numeric labels.
        return f"{min(firsts)} - {max(lasts)}"

    def _build_summary(self) -> dict:
        """Build the compact summary block included at the top of the JSON."""
        return {
            "total_files": self.total_files,
            "fully_succeeded": self.fully_succeeded,
            "partially_failed": self.partially_failed,
            "bates_range": self.bates_range,
            "stages_run": self.stages_run,
            "total_elapsed_s": self.total_elapsed_s,
            "stage_elapsed_s": self.stage_elapsed_s,
        }

    def to_dict(self) -> dict:
        """
        Serialize the full report to a plain dict.

        The dict is JSON-safe (no datetime objects, no sets). The top-level
        structure is::

            {
              "run_id": "...",
              "started_at": "...",
              "finished_at": "...",
              "error": null,
              "settings": {...},
              "summary": {...},
              "files": [...]
            }
        """
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "settings": self.settings,
            "summary": self._build_summary(),
            "files": [fr.to_dict() for fr in self.file_results],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
