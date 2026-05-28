/**
 * rlg-pipeline.js — Full Pipeline Stepper UI with Review Stage
 *
 * Drives the [rlg_pipeline] shortcode. The pipeline runs the complete
 * document workflow in two phases:
 *
 * Phase 1 (POST /pipeline/run):
 *   Upload → Scan → Unlock → OCR → Redact → Organize → Bates
 *   Ends with a review_ready event. The stream closes; UI shows Review panel.
 *
 * Review (user action):
 *   Attorney inspects per-file redaction hit counts.
 *   Optional: add missed patterns → POST /pipeline/re-redact/{run_id}
 *   When satisfied: POST /pipeline/finalize/{run_id}
 *
 * Phase 2 (POST /pipeline/finalize/{run_id}):
 *   Index → done event → automatic download trigger
 *
 * Visual stepper: one circle per stage, connected by horizontal lines.
 *   - Active  → blue ring + spinner
 *   - Complete → green circle + checkmark
 *   - Skipped  → dim grey + original icon
 *   - Error    → orange ring + warning icon
 *   - Review   → amber circle + eye icon (waiting for attorney input)
 *
 * Dependencies: rlg-core.js (for RLGDiscovery namespace).
 */

(function ($) {
    'use strict';

    // -------------------------------------------------------------------------
    // Stage definitions — order matches the API pipeline sequence.
    // The 'review' step is a UI-only pause between Redact and Index.
    // -------------------------------------------------------------------------
    var STAGES = [
        { key: 'scan',     label: 'Scan',     icon: '🔍' },
        { key: 'unlock',   label: 'Unlock',   icon: '🔓' },
        { key: 'ocr',      label: 'OCR',      icon: '👁️'  },
        { key: 'redact',   label: 'Redact',   icon: '⬛' },
        { key: 'organize', label: 'Organize', icon: '📁' },
        { key: 'bates',    label: 'Bates',    icon: '🏷️'  },
        { key: 'review',   label: 'Review',   icon: '🔍' },  // UI pause
        { key: 'index',    label: 'Index',    icon: '📋' },
    ];

    // -------------------------------------------------------------------------
    // PipelineController — one instance per [rlg_pipeline] on the page
    // -------------------------------------------------------------------------
    function PipelineController(root) {
        this.$root     = $(root);
        this.$form     = this.$root.find('#rlg-pipeline-form');
        this.$stepper  = this.$root.find('#rlg-pipeline-stepper');
        this.$log      = this.$root.find('#rlg-pipeline-log');
        this.$dlBtn    = this.$root.find('#rlg-pipeline-download');
        this.$submit   = this.$root.find('#rlg-pipeline-submit');
        this.$scanInfo = this.$root.find('#rlg-pipeline-scan-info');
        this.$review   = this.$root.find('#rlg-pipeline-review');
        this.$rerunBtn = this.$root.find('#rlg-pl-rerun-btn');
        this.$approveBtn = this.$root.find('#rlg-pl-approve-btn');
        this.$reviewTableWrap = this.$root.find('#rlg-pl-review-table-wrap');

        this.stageEls     = {};  // stage key → { $wrap, $circle, $spin, $check, $warn, $icon, $detail }
        this.runId        = null;
        this.scanId       = null;
        this._lockedFiles = [];  // FileScanResult objects for locked files (from last scan)

        this._initStepper();
        this._bindEvents();
        this._bindToggles();
        this._bindColorSwatches();
    }

    // -------------------------------------------------------------------------
    // Build the stepper DOM
    // -------------------------------------------------------------------------
    PipelineController.prototype._initStepper = function () {
        var self = this;
        this.$stepper.empty();
        var $track = $('<div class="rlg-pl-track"></div>');

        STAGES.forEach(function (stage, idx) {
            var $wrap = $('<div class="rlg-pl-step" data-stage="' + stage.key + '"></div>');
            var $circle = $(
                '<div class="rlg-pl-circle">' +
                    '<span class="rlg-pl-icon">' + stage.icon + '</span>' +
                    '<span class="rlg-pl-spinner" style="display:none"></span>' +
                    '<span class="rlg-pl-check"  style="display:none">&#10003;</span>' +
                    '<span class="rlg-pl-warn"   style="display:none">&#9888;</span>' +
                    '<span class="rlg-pl-eye"    style="display:none">&#128269;</span>' +
                '</div>'
            );
            var $label  = $('<div class="rlg-pl-label">' + stage.label + '</div>');
            var $detail = $('<div class="rlg-pl-detail"></div>');

            $wrap.append($circle).append($label).append($detail);
            $track.append($wrap);

            if (idx < STAGES.length - 1) {
                $track.append('<div class="rlg-pl-connector"></div>');
            }

            self.stageEls[stage.key] = {
                $wrap:   $wrap,
                $circle: $circle,
                $detail: $detail,
                $icon:   $circle.find('.rlg-pl-icon'),
                $spin:   $circle.find('.rlg-pl-spinner'),
                $check:  $circle.find('.rlg-pl-check'),
                $warn:   $circle.find('.rlg-pl-warn'),
                $eye:    $circle.find('.rlg-pl-eye'),
            };
        });

        this.$stepper.append($track);
    };

    // ---- Individual step state setters -----

    PipelineController.prototype._stepPending = function (key) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.removeClass('active complete error skip review');
        el.$icon.show(); el.$spin.hide(); el.$check.hide(); el.$warn.hide(); el.$eye.hide();
        el.$detail.text('');
    };

    PipelineController.prototype._stepActive = function (key, detail) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.addClass('active').removeClass('complete error skip review');
        el.$icon.hide(); el.$spin.show(); el.$check.hide(); el.$warn.hide(); el.$eye.hide();
        if (detail) el.$detail.text(detail);
    };

    PipelineController.prototype._stepComplete = function (key, detail) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.addClass('complete').removeClass('active error skip review');
        el.$icon.hide(); el.$spin.hide(); el.$check.show(); el.$warn.hide(); el.$eye.hide();
        if (detail) el.$detail.text(detail);
    };

    PipelineController.prototype._stepSkip = function (key) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.addClass('skip').removeClass('active complete error review');
        el.$icon.show(); el.$spin.hide(); el.$check.hide(); el.$warn.hide(); el.$eye.hide();
        el.$detail.text('Skipped');
    };

    PipelineController.prototype._stepError = function (key, detail) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.addClass('error').removeClass('active complete skip review');
        el.$icon.hide(); el.$spin.hide(); el.$check.hide(); el.$warn.show(); el.$eye.hide();
        if (detail) el.$detail.text(detail);
    };

    /** Review step: amber circle with eye icon, waiting for attorney action. */
    PipelineController.prototype._stepReview = function (key, detail) {
        var el = this.stageEls[key]; if (!el) return;
        el.$wrap.addClass('review').removeClass('active complete error skip');
        el.$icon.hide(); el.$spin.hide(); el.$check.hide(); el.$warn.hide(); el.$eye.show();
        if (detail) el.$detail.text(detail);
    };

    // ---- Log ----------------------------------------------------------------

    PipelineController.prototype._log = function (msg, cls) {
        var $line = $('<div class="rlg-pl-log-line"></div>').text(msg);
        if (cls) $line.addClass(cls);
        this.$log.append($line);
        this.$log.scrollTop(this.$log[0].scrollHeight);
    };

    // ---- Reset all steps ---------------------------------------------------

    PipelineController.prototype._reset = function () {
        var self = this;
        STAGES.forEach(function (s) { self._stepPending(s.key); });
        this.$log.empty();
        this.$dlBtn.hide().attr('href', '#').text('');
        this.$scanInfo.empty().hide();
        this.$root.find('#rlg-pl-password-panel').hide().empty();
        this.$review.hide();
        this.$reviewTableWrap.empty();
        this.runId        = null;
        this.scanId       = null;
        this._lockedFiles = [];
    };

    // -------------------------------------------------------------------------
    // Event binding
    // -------------------------------------------------------------------------
    PipelineController.prototype._bindEvents = function () {
        var self = this;

        // Main form submit → run Phase 1
        this.$form.on('submit', function (e) {
            e.preventDefault();
            self._runPhase1();
        });

        // Re-run redaction button in review panel
        this.$rerunBtn.on('click', function () {
            self._reRedact();
        });

        // Approve & finalize
        this.$approveBtn.on('click', function () {
            self._finalize();
        });

        // Scan manifest toggle
        this.$root.on('click', '#rlg-scan-details-toggle', function (e) {
            e.preventDefault();
            self.$root.find('#rlg-scan-details').toggle();
        });
    };

    /**
     * Wire the enable_* toggle switches to show/hide their section's
     * collapsible settings (.rlg-pl-toggle-target).
     *
     * Logic:  checked  = stage enabled  → show settings fields
     *         unchecked = stage disabled → hide settings fields
     */
    PipelineController.prototype._bindToggles = function () {
        var self = this;

        this.$form.on('change', 'input[name^="enable_"]', function () {
            var $cb    = $(this);
            var target = $cb.closest('section').find('.rlg-pl-toggle-target');
            if (!target.length) return;
            if ($cb.is(':checked')) target.slideDown(200);
            else                    target.slideUp(200);
        });

        // Apply initial visibility on page load
        this.$form.find('input[name^="enable_"]').each(function () {
            var $cb    = $(this);
            var target = $cb.closest('section').find('.rlg-pl-toggle-target');
            if (!target.length) return;
            if ($cb.is(':checked')) target.show();
            else                    target.hide();
        });
    };

    /** Wire color swatch buttons in the Bates section. */
    PipelineController.prototype._bindColorSwatches = function () {
        var self = this;
        this.$root.on('click', '#pl-color-presets .rlg-color-swatch', function () {
            var color = $(this).data('color');
            self.$root.find('#pl-color').val(color);
            self.$root.find('#pl-color-presets .rlg-color-swatch').removeClass('active');
            $(this).addClass('active');
        });
    };

    // -------------------------------------------------------------------------
    // Password panel — shown when scan detects locked files and Unlock is on
    // -------------------------------------------------------------------------

    /**
     * Render the per-file password collection panel.
     *
     * @param {Array}  lockedFiles  FileScanResult objects with is_locked === true
     * @param {Array}  badFiles     Filenames that had a wrong password (highlight in red)
     */
    PipelineController.prototype._showPasswordPanel = function (lockedFiles, badFiles) {
        var self    = this;
        var $panel  = this.$root.find('#rlg-pl-password-panel');
        var badSet  = {};
        (badFiles || []).forEach(function (f) { badSet[f] = true; });

        var html = '<h4>🔒 Password Required</h4>' +
            '<p>' + lockedFiles.length + ' file(s) in your upload are password protected. ' +
            'Enter the password for each file below, or leave blank to skip that file.</p>' +
            '<div class="rlg-pl-pw-files">';

        lockedFiles.forEach(function (f) {
            var isBad   = badSet[f.filename];
            var errHtml = isBad
                ? '<span class="rlg-pl-pw-err-msg">❌ Wrong password — please try again</span>'
                : '';
            html +=
                '<div class="rlg-pl-pw-file" data-filename="' + self._esc(f.filename) + '">' +
                    '<label title="' + self._esc(f.filename) + '">' +
                        self._esc(f.filename.replace(/^.*[\\/]/, '')) +  // basename only
                    '</label>' +
                    '<input type="password" class="rlg-pl-pw-input' + (isBad ? ' pw-error' : '') + '" ' +
                           'placeholder="Enter password…" autocomplete="current-password">' +
                    errHtml +
                '</div>';
        });

        html += '</div>' +
            '<div class="rlg-pl-pw-actions">' +
                '<button type="button" class="rlg-btn rlg-pl-pw-continue" id="rlg-pl-pw-continue">' +
                    '🔓 Continue with passwords' +
                '</button>' +
                '<button type="button" class="rlg-btn rlg-pl-pw-skip" id="rlg-pl-pw-skip">' +
                    'Skip locked files →' +
                '</button>' +
            '</div>';

        $panel.html(html).slideDown(250);
        this._log('🔒 ' + lockedFiles.length + ' file(s) need a password — see panel above.',
                  'rlg-pl-log-warn');

        // Bind Continue button
        $panel.find('#rlg-pl-pw-continue').one('click', function () {
            var passwords = {};
            $panel.find('.rlg-pl-pw-file').each(function () {
                var fname = $(this).data('filename');
                var pw    = $(this).find('.rlg-pl-pw-input').val().trim();
                if (pw) passwords[fname] = pw;
            });
            $panel.slideUp(200);
            self._submitRun(passwords);
        });

        // Bind Skip button — start run without any passwords (locked files fail gracefully)
        $panel.find('#rlg-pl-pw-skip').one('click', function () {
            $panel.slideUp(200);
            self._lockedFiles = [];
            self._submitRun({});
        });
    };

    /**
     * Build FormData and start the SSE run stream.
     * Called either directly (no locked files) or from the password panel Continue button.
     *
     * @param {Object} passwords  Map of filename → password (may be empty)
     */
    PipelineController.prototype._submitRun = function (passwords) {
        var self = this;
        var api  = this._api();
        var fd   = this._buildRunFormData();

        fd.append('passwords_json', JSON.stringify(passwords || {}));

        self._stepActive('unlock', '');
        self._log('Starting pipeline…');

        self._streamSSE(api.url + '/pipeline/run', self._authHeaders(), fd);
    };

    // -------------------------------------------------------------------------
    // Helpers: API URL / key
    // -------------------------------------------------------------------------
    PipelineController.prototype._api = function () {
        var RLG = window.RLGDiscovery;
        return {
            url: (RLG && RLG.getApiUrl ? RLG.getApiUrl()
                  : (window.rlgSettings && window.rlgSettings.apiUrl) || ''),
            key: (RLG && RLG.getApiKey ? RLG.getApiKey()
                  : (window.rlgSettings && window.rlgSettings.apiKey) || ''),
        };
    };

    PipelineController.prototype._authHeaders = function () {
        var key = this._api().key;
        return key ? {'X-API-Key': key} : {};
    };

    // -------------------------------------------------------------------------
    // Phase 1: Scan + Run
    // -------------------------------------------------------------------------
    PipelineController.prototype._runPhase1 = function () {
        var self = this;
        var api  = this._api();

        if (!api.url) {
            alert('API URL is not configured. Please contact your administrator.');
            return;
        }

        var fileInput = this.$form.find('input[name="files"]')[0];
        if (!fileInput || !fileInput.files.length) {
            alert('Please select at least one file.');
            return;
        }

        self._reset();
        self.$submit.prop('disabled', true).text('Running…');
        self.$form.find('[name]').not('[name="files"]').prop('disabled', true);

        // ------------------------------------------------------------------
        // 1a. POST /pipeline/scan
        // ------------------------------------------------------------------
        self._stepActive('scan', 'Uploading…');
        self._log('Uploading files for pre-flight scan…');

        var scanFd = new FormData();
        for (var i = 0; i < fileInput.files.length; i++) {
            scanFd.append('files', fileInput.files[i]);
        }

        fetch(api.url + '/pipeline/scan', {
            method: 'POST', headers: self._authHeaders(), body: scanFd,
        })
        .then(function (res) {
            if (!res.ok) return res.text().then(function (t) {
                throw new Error('Scan failed (' + res.status + '): ' + t);
            });
            return res.json();
        })
        .then(function (data) {
            self.scanId = data.scan_id;
            var m = data.manifest;

            self._stepComplete('scan', m.total_files + ' file(s)');
            self._log('Scan complete — ' + m.total_files + ' file(s), ' + m.total_pages + ' page(s).');
            if (m.warnings && m.warnings.length) {
                m.warnings.forEach(function (w) { self._log('⚠ ' + w, 'rlg-pl-log-warn'); });
            }
            self._renderScanInfo(m);

            // ------------------------------------------------------------------
            // 1b. POST /pipeline/run  (SSE — Phase 1 stages)
            //
            // If the scan found locked files AND Unlock is enabled, show the
            // password collection panel first.  The "Continue" button in that
            // panel calls _submitRun(passwords) with the entered values.
            // Otherwise start the run immediately with an empty passwords map.
            // ------------------------------------------------------------------
            var lockedFiles   = (m.files || []).filter(function (f) { return f.is_locked; });
            var unlockEnabled = self.$form.find('input[name="enable_unlock"]').is(':checked');

            if (lockedFiles.length > 0 && unlockEnabled) {
                self._lockedFiles = lockedFiles;
                self._showPasswordPanel(lockedFiles, []);
            } else {
                self._lockedFiles = [];
                self._submitRun({});
            }
        })
        .catch(function (err) {
            self._stepError('scan', 'Error');
            self._log('✗ ' + err.message, 'rlg-pl-log-error');
            self._unlockForm();
        });
    };

    // -------------------------------------------------------------------------
    // Review actions
    // -------------------------------------------------------------------------

    /** POST /pipeline/re-redact/{run_id} */
    PipelineController.prototype._reRedact = function () {
        var self = this;
        var api  = this._api();
        if (!self.runId) return;

        // Collect the additional patterns from the review panel inputs
        var fd = new FormData();

        this.$review.find('input[name="re_presets"]:checked').each(function () {
            fd.append('presets', $(this).val());
        });
        var regex = this.$review.find('#re-regex').val().trim();
        var literals = this.$review.find('#re-literals').val().trim();
        if (regex)    fd.append('regex_patterns', regex);
        if (literals) fd.append('literal_patterns', literals);

        if (!fd.has('presets') && !fd.has('regex_patterns') && !fd.has('literal_patterns')) {
            alert('Please add at least one redaction pattern (preset, regex, or literal phrase).');
            return;
        }

        this.$rerunBtn.prop('disabled', true).text('Re-running…');
        this.$approveBtn.prop('disabled', true);
        this._log('Re-running redaction with additional patterns…');

        this._streamSSE(
            api.url + '/pipeline/re-redact/' + encodeURIComponent(self.runId),
            self._authHeaders(),
            fd
        );
    };

    /** POST /pipeline/finalize/{run_id} */
    PipelineController.prototype._finalize = function () {
        var self = this;
        var api  = this._api();
        if (!self.runId) return;

        this.$rerunBtn.prop('disabled', true);
        this.$approveBtn.prop('disabled', true).text('Finalizing…');
        this.$review.hide();
        this._stepActive('index', 'Building index…');
        this._log('Approved — running Index stage…');

        this._streamSSE(
            api.url + '/pipeline/finalize/' + encodeURIComponent(self.runId),
            self._authHeaders(),
            new FormData()  // no body params needed; everything is in _review_store
        );
    };

    // -------------------------------------------------------------------------
    // SSE streaming  (shared by all three fetch calls)
    // -------------------------------------------------------------------------

    /**
     * POST to *url* with *headers* and *formData*, read the SSE stream,
     * and dispatch each event to _handleSseEvent().
     */
    PipelineController.prototype._streamSSE = function (url, headers, formData) {
        var self = this;

        fetch(url, { method: 'POST', headers: headers, body: formData })
        .then(function (res) {
            if (!res.ok) return res.text().then(function (t) {
                throw new Error('HTTP ' + res.status + ': ' + t);
            });

            var reader  = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer  = '';

            function pump() {
                return reader.read().then(function (result) {
                    if (result.done) {
                        if (buffer.trim()) self._handleSseChunk(buffer);
                        return;
                    }
                    buffer += decoder.decode(result.value, { stream: true });
                    // Events are separated by double newline
                    var parts = buffer.split('\n\n');
                    buffer = parts.pop();
                    parts.forEach(function (p) { self._handleSseChunk(p); });
                    return pump();
                });
            }
            return pump();
        })
        .catch(function (err) {
            self._log('✗ Stream error: ' + err.message, 'rlg-pl-log-error');
            self._unlockForm();
        });
    };

    // -------------------------------------------------------------------------
    // SSE event dispatch
    // -------------------------------------------------------------------------

    PipelineController.prototype._handleSseChunk = function (chunk) {
        var self = this;
        var match = chunk.match(/^data:\s*(.+)/m);
        if (!match) return;

        var evt;
        try { evt = JSON.parse(match[1]); }
        catch (e) { self._log('[debug] malformed event: ' + match[1]); return; }

        var type  = evt.type  || '';
        var stage = evt.stage || '';
        var label = evt.label || '';

        switch (type) {

            case 'stage_start':
                self._stepActive(stage, '');
                self._log('▶ ' + label);
                break;

            case 'stage_complete':
                self._stepComplete(stage, self._shortDetail(evt));
                self._log('✓ ' + label, 'rlg-pl-log-ok');
                if (evt.failures) {
                    self._log('  ⚠ ' + evt.failures + ' file(s) had errors in this stage.',
                              'rlg-pl-log-warn');
                }
                if (evt.hits !== undefined) {
                    self._log('  Redaction matches: ' + evt.hits);
                }
                // OCR: surface how many files were already searchable so the
                // attorney knows the Apple-pre-OCR'd ones were not re-processed.
                if (stage === 'ocr' && evt.already_searchable) {
                    self._log(
                        '  ℹ ' + evt.already_searchable +
                        ' file(s) already had a text layer (Apple/Preview OCR) — skipped.',
                        'rlg-pl-log-skip'
                    );
                }
                break;

            case 'password_error':
                // One or more passwords were wrong — re-show the panel with errors highlighted.
                // The stream is now closed; the attorney can correct and retry.
                self._log(
                    '✗ ' + (evt.message || 'Wrong password — please correct and try again.'),
                    'rlg-pl-log-error'
                );
                // Re-render the password panel highlighting the bad files
                if (self._lockedFiles && self._lockedFiles.length) {
                    self._showPasswordPanel(self._lockedFiles, evt.bad_files || []);
                }
                self._unlockForm();
                break;

            case 'stage_skip':
                self._stepSkip(stage);
                self._log('— ' + label, 'rlg-pl-log-skip');
                break;

            case 'stage_error':
                self._stepError(stage, 'Error');
                self._log('✗ ' + label, 'rlg-pl-log-error');
                break;

            case 'review_ready':
                // Phase 1 complete — store run_id, show review panel.
                // Individual stages (redact, organize, bates) are already
                // marked complete/skip by their own stage_complete/stage_skip events.
                self.runId = evt.run_id;
                self._stepReview('review', 'Awaiting approval');
                self._log('');
                self._log('Phase 1 complete — ' + (evt.total_hits || 0) + ' redaction match(es).', 'rlg-pl-log-ok');
                if (evt.bates_range) {
                    self._log('Bates range: ' + evt.bates_range);
                }
                self._renderReviewPanel(evt);
                // Re-enable the re-run and approve buttons
                self.$rerunBtn.prop('disabled', false).text('🔄 Re-run Redaction');
                self.$approveBtn.prop('disabled', false).text('✅ Approve & Finalize');
                break;

            case 'done':
                // Pipeline fully complete (emitted by /finalize)
                self._stepComplete('review', 'Approved');
                self._stepComplete('index', 'Done');
                self._log('');
                self._log('✅ Pipeline complete!', 'rlg-pl-log-ok');
                if (evt.bates_range) self._log('Bates range: ' + evt.bates_range);
                if (evt.partially_failed) {
                    self._log('⚠ ' + evt.partially_failed +
                              ' file(s) had partial errors — see _pipeline_report.json.',
                              'rlg-pl-log-warn');
                }
                self._triggerDownload(evt.run_id);
                self._unlockForm();
                break;

            default:
                self._log('[debug] ' + JSON.stringify(evt));
                break;
        }
    };

    /** Build a short detail string for the circle from event data. */
    PipelineController.prototype._shortDetail = function (evt) {
        if (evt.stage === 'bates'    && evt.last_num)  return '#' + evt.last_num;
        if (evt.stage === 'redact')                    return (evt.hits || 0) + ' hits';
        if (evt.stage === 'organize' && evt.failures)  return evt.failures + ' err';
        if (evt.stage === 'ocr'      && evt.failures)  return evt.failures + ' err';
        return '';
    };

    // -------------------------------------------------------------------------
    // FormData builders
    // -------------------------------------------------------------------------

    /**
     * Collect all pipeline settings into a FormData for /pipeline/run.
     *
     * enable_* toggles are converted to skip_* API parameters with inverted booleans:
     *   enable_unlock  checked   → skip_unlock  = "false"  (run unlock)
     *   enable_unlock  unchecked → skip_unlock  = "true"   (skip unlock)
     *
     * All other named inputs are passed through as-is.
     */
    PipelineController.prototype._buildRunFormData = function () {
        var self = this;
        var fd   = new FormData();

        fd.append('scan_id', self.scanId);

        self.$form.find('[name]').not('[name="files"]').each(function () {
            var $el  = $(this);
            var name = $el.attr('name');

            if ($el.is(':checkbox')) {
                if (name.indexOf('enable_') === 0) {
                    // Convert enable_* → skip_* with inverted boolean for the API
                    var skipName = 'skip_' + name.slice(7);  // 'enable_'.length === 7
                    fd.append(skipName, $el.is(':checked') ? 'false' : 'true');
                } else {
                    // Multi-value list fields (e.g. presets): only append when
                    // checked, using the element's actual value (e.g. 'SSN').
                    // Unchecked checkboxes are simply omitted — the server's
                    // List[str] = Form([]) treats absence as an empty list.
                    if ($el.is(':checked')) {
                        fd.append(name, $el.val());
                    }
                }
            } else if ($el.is('select[multiple]')) {
                $el.find('option:selected').each(function () {
                    fd.append(name, $(this).val());
                });
            } else {
                fd.append(name, $el.val() || '');
            }
        });

        return fd;
    };

    // -------------------------------------------------------------------------
    // Review panel rendering
    // -------------------------------------------------------------------------

    /**
     * Render the per-file review table from the review_ready event payload.
     * Shows each file, whether it was redacted, and how many hits were found.
     */
    PipelineController.prototype._renderReviewPanel = function (evt) {
        var self     = this;
        var byFile   = evt.hits_by_file || {};
        var fileList = Object.keys(byFile);
        var totalHits = evt.total_hits || 0;

        var html = '<table class="rlg-pl-review-table">' +
                   '<thead><tr>' +
                   '<th>File</th>' +
                   '<th>Redaction Hits</th>' +
                   '<th>Status</th>' +
                   '</tr></thead><tbody>';

        if (fileList.length === 0) {
            html += '<tr><td colspan="3" style="color:#6b7280;font-style:italic;">' +
                    (totalHits === 0
                        ? 'Redaction was skipped or found no matches.'
                        : 'No per-file data available.') +
                    '</td></tr>';
        } else {
            fileList.forEach(function (fname) {
                var hits   = byFile[fname] || 0;
                var cls    = hits > 0 ? 'hits-some' : 'hits-zero';
                var status = hits > 0 ? '⬛ Redacted' : '✓ No matches';
                html += '<tr>' +
                    '<td class="rlg-pl-rt-name">' + self._esc(fname) + '</td>' +
                    '<td class="' + cls + '">' + hits + '</td>' +
                    '<td>' + status + '</td>' +
                    '</tr>';
            });
        }

        html += '</tbody></table>';
        this.$reviewTableWrap.html(html);
        this.$review.slideDown(250);

        this._log('Review panel shown — inspect results and approve or re-run.');
    };

    // -------------------------------------------------------------------------
    // Scan manifest panel
    // -------------------------------------------------------------------------
    PipelineController.prototype._renderScanInfo = function (manifest) {
        var self  = this;
        var files = manifest.files || [];
        if (!files.length) return;

        var html = '<a href="#" id="rlg-scan-details-toggle" class="rlg-pl-details-link">' +
                   'Show scanned file details ▾</a>' +
                   '<div id="rlg-scan-details" style="display:none">' +
                   '<table class="rlg-pl-manifest-table">' +
                   '<thead><tr><th>File</th><th>Type</th><th>Pages</th><th>Note</th></tr></thead>' +
                   '<tbody>';

        files.forEach(function (f) {
            var note = '';
            if (f.is_locked)        note = '🔒 Password protected';
            else if (f.is_already_ocr) note = '✓ Already searchable';
            else if (f.error)       note = '⚠ ' + f.error;

            html += '<tr>' +
                '<td class="rlg-pl-mf-name">' + self._esc(f.filename) + '</td>' +
                '<td>' + self._esc(f.file_type) + '</td>' +
                '<td>' + (f.page_count !== null ? f.page_count : '—') + '</td>' +
                '<td>' + note + '</td>' +
                '</tr>';
        });

        html += '</tbody></table></div>';
        this.$scanInfo.html(html).show();
    };

    // -------------------------------------------------------------------------
    // Download trigger
    // -------------------------------------------------------------------------
    PipelineController.prototype._triggerDownload = function (runId) {
        var self = this;
        var api  = this._api();
        var dlUrl = api.url + '/pipeline/download/' + encodeURIComponent(runId);

        self._log('Fetching output ZIP…');

        fetch(dlUrl, { method: 'GET', headers: self._authHeaders() })
        .then(function (res) {
            if (!res.ok) throw new Error('Download failed: HTTP ' + res.status);
            // Read the server's Content-Disposition to get the custom filename.
            var disposition = res.headers.get('Content-Disposition') || '';
            var nameMatch   = disposition.match(/filename="?([^";]+)"?/);
            var dlName      = nameMatch
                ? nameMatch[1]
                : 'pipeline_output_' + runId.slice(0, 8) + '.zip';
            return res.blob().then(function (blob) {
                return { blob: blob, dlName: dlName };
            });
        })
        .then(function (result) {
            var objUrl  = URL.createObjectURL(result.blob);
            var $anchor = $('<a style="display:none"></a>')
                .attr('href', objUrl).attr('download', result.dlName);
            $('body').append($anchor);
            $anchor[0].click();
            $anchor.remove();
            setTimeout(function () { URL.revokeObjectURL(objUrl); }, 5000);

            self._log('✓ Download started — check your browser downloads.', 'rlg-pl-log-ok');

            // Persistent fallback download button
            self.$dlBtn
                .attr('href', objUrl)
                .attr('download', result.dlName)
                .text('⬇ Download Again')
                .show();
        })
        .catch(function (err) {
            self._log('✗ Download error: ' + err.message, 'rlg-pl-log-error');
            self.$dlBtn.attr('href', dlUrl).text('⬇ Try Manual Download').show();
        });
    };

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /** Re-enable the form after a run completes (success or failure). */
    PipelineController.prototype._unlockForm = function () {
        this.$submit.prop('disabled', false).text('▶ Run All-in-One Processing');
        this.$form.find('[name]').prop('disabled', false);
    };

    /** HTML-escape a string for safe innerHTML insertion. */
    PipelineController.prototype._esc = function (str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    };

    // -------------------------------------------------------------------------
    // Auto-init: find all [rlg_pipeline] wrappers on the page
    // -------------------------------------------------------------------------
    $(document).ready(function () {
        $('.rlg-pipeline-tool').each(function () {
            new PipelineController(this);
        });
    });

}(jQuery));
