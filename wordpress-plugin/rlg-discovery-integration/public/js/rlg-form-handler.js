/**
 * RLG Discovery - Form Handler Module
 * Form submission and API calls
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;
    var lastBates = RLG.lastBates;
    var batesState = RLG.batesPreviewState;

    // Form submission handler
    $(document).on('submit', '.rlg-discovery-form', function(e) {
        e.preventDefault();

        var $form = $(this);
        var $status = $form.find('.rlg-status');
        var $btn = $form.find('button[type="submit"]');

        var endpoint = $form.data('endpoint');
        var apiUrl = RLG.getApiUrl() + endpoint;

        var formData = new FormData(this);

        if (endpoint === '/bates') {
            formData.set('font_bold', document.getElementById('bates-fontbold').checked ? 'true' : 'false');
        }

        if (endpoint === '/index') {
            var source = $form.find('input[name="index_source"]:checked').val();
            if (source === 'last_bates') {
                if (!lastBates.output) {
                    $status.html('<span style="color:#dc2626;">No Bates output available. Please run Bates Labeler first or upload a ZIP.</span>');
                    return;
                }
                formData.delete('file');
                formData.append('file', lastBates.output, lastBates.filename);
                // Pass Bates metadata so the server can skip re-detection
                if (lastBates.files && lastBates.files.length > 0) {
                    formData.append('bates_metadata', JSON.stringify(lastBates.files));
                }
            }
        }

        $status.html('<span class="rlg-status loading">Processing... <span class="rlg-spinner"></span></span>');
        $btn.prop('disabled', true);

        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, 120000);

        // Build request headers. X-API-Key is always included so the server
        // can validate requests. If the key is blank (local dev / auth disabled),
        // the header is sent empty and the server allows it through.
        var requestHeaders = {};
        var apiKey = RLG.getApiKey();
        if (apiKey) {
            requestHeaders['X-API-Key'] = apiKey;
        }

        fetch(apiUrl, {
            method: 'POST',
            headers: requestHeaders,
            body: formData,
            signal: controller.signal
        })
            .then(function(response) {
                clearTimeout(timeoutId);
                if (!response.ok) {
                    var ctErr = response.headers.get('Content-Type') || '';
                    if (ctErr.indexOf('application/json') !== -1) {
                        return response.json().then(function(errData) {
                            throw new Error(errData.detail || ('Request failed (' + response.status + ')'));
                        });
                    }
                    if (response.status === 413) {
                        throw new Error('File too large for server to accept.');
                    }
                    if (response.status === 502 || response.status === 503 || response.status === 504) {
                        throw new Error('The server is waking up or busy. Wait ~30s and try again.');
                    }
                    throw new Error('Server error: ' + response.status + ' (' + response.statusText + ')');
                }

                var contentType = response.headers.get('Content-Type') || '';
                var disposition = response.headers.get('Content-Disposition') || '';
                // Per-file failures are reported by the server in the X-Failed-Files
                // header as a JSON object map {filename: reason} (omitted entirely
                // when nothing failed). Parse defensively.
                var failedFiles = [];
                var failedHeader = response.headers.get('X-Failed-Files') || '';
                if (failedHeader) {
                    try { failedFiles = JSON.parse(failedHeader) || []; }
                    catch (e) { failedFiles = []; }
                }
                return response.blob().then(function(blob) {
                    return { blob: blob, contentType: contentType, disposition: disposition, failedFiles: failedFiles };
                });

            })
            .then(function(result) {
                var blob = result.blob;
                var serverFilename = null;
                var match = result.disposition.match(/filename="?([^";]+)"?/);
                if (match) serverFilename = match[1];

                // Build a per-file failure warning from the server's X-Failed-Files
                // header. The server sends a JSON object map {filename: reason}; we
                // also tolerate an array of {filename, error}. Returns '' when empty.
                function failureNotice(failed) {
                    var pairs = [];
                    if (Array.isArray(failed)) {
                        failed.forEach(function(f) {
                            pairs.push([(f && (f.filename || f.name)) || 'Unknown file',
                                        (f && (f.error || f.reason)) || 'could not be processed']);
                        });
                    } else if (failed && typeof failed === 'object') {
                        Object.keys(failed).forEach(function(name) {
                            pairs.push([name, failed[name] || 'could not be processed']);
                        });
                    }
                    if (!pairs.length) return '';
                    function esc(s) {
                        return String(s).replace(/[&<>"]/g, function(c) {
                            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
                        });
                    }
                    var items = pairs.map(function(p) {
                        return '<li>' + esc(p[0]) + ' — ' + esc(p[1]) + '</li>';
                    }).join('');
                    return '<div class="rlg-status warning" style="margin-top:8px;padding:8px 12px;' +
                           'background:#fef3c7;border:1px solid #f59e0b;border-radius:4px;color:#92400e;">' +
                           '<strong>' + pairs.length + ' file(s) could not be processed:</strong>' +
                           '<ul style="margin:6px 0 0;padding-left:20px;">' + items + '</ul></div>';
                }

                // Shared download trigger — runs after /bates finishes its
                // async sidecar work, and synchronously for other endpoints.
                function triggerDownload() {
                    var url = window.URL.createObjectURL(blob);
                    var a = document.createElement('a');
                    a.href = url;

                    var filename = serverFilename;
                    if (!filename) {
                        var ct = result.contentType;
                        var isPdf = ct.indexOf('application/pdf') !== -1;
                        var isImage = ct.indexOf('image/png') !== -1 || ct.indexOf('image/jpeg') !== -1;
                        var ext = isPdf ? '.pdf' : isImage ? (ct.indexOf('png') !== -1 ? '.png' : '.jpg') : '.zip';
                        if (endpoint === '/unlock') filename = isPdf ? 'unlocked.pdf' : 'unlocked_pdfs.zip';
                        else if (endpoint === '/organize') filename = 'organized_by_year.zip';
                        else if (endpoint === '/bates') filename = ext !== '.zip' ? 'bates_labeled' + ext : 'bates_labeled.zip';
                        else if (endpoint === '/redact') filename = isPdf ? 'redacted_output.pdf' : 'redacted_output.zip';
                        else if (endpoint === '/index') filename = 'discovery_index.xlsx';
                        else if (endpoint === '/ocr') filename = isPdf ? 'ocr_output.pdf' : 'ocr_output.zip';
                        else filename = 'download.zip';
                    }
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);

                    $btn.prop('disabled', false);
                }

                if (endpoint === '/bates') {
                    lastBates.output = blob;
                    lastBates.filename = serverFilename || 'bates_labeled.zip';

                    // Use actual page counts from batesPreviewState if available
                    var prefix = $('#bates-prefix').val();
                    var startNum = parseInt($('#bates-start').val()) || 1;
                    var digits = parseInt($('#bates-digits').val()) || 8;

                    lastBates.files = [];

                    // Helper to extract category from file path
                    function getCategoryFromPath(fullPath) {
                        if (!fullPath) return '';
                        var parts = fullPath.split('/');
                        if (parts.length > 1) {
                            return parts[parts.length - 2];
                        }
                        return '';
                    }

                    // Try to read the server's authoritative Bates records
                    // from the sidecar embedded in the returned zip. When
                    // present, these are the real ranges stamped on the
                    // real files — no client-side prediction needed.
                    return blob.arrayBuffer().then(function(zipBuffer) {
                        return RLG.extractFilesFromZip(zipBuffer);
                    }).then(function(zipFiles) {
                        var usedSidecar = zipFiles.some(function(f) { return !!f.batesRange; });

                        if (usedSidecar) {
                            // Sidecar path: trust the server's ranges verbatim.
                            zipFiles.forEach(function(file) {
                                lastBates.files.push({
                                    name: file.name,
                                    path: file.fullPath || file.name,
                                    category: file.category || getCategoryFromPath(file.fullPath),
                                    batesRange: file.batesRange
                                });
                            });
                            // Also sync batesState so the preview table
                            // renders the real Bates values, not the
                            // predicted ones from the pre-submit preview.
                            if (batesState.files && batesState.files.length > 0) {
                                var lookup = {};
                                zipFiles.forEach(function(f) {
                                    if (f.fullPath) lookup[f.fullPath] = f;
                                });
                                batesState.files.forEach(function(f) {
                                    var matched = lookup[f.fullPath] || lookup[f.name];
                                    if (matched) {
                                        f.batesRange = matched.batesRange;
                                        f.batesFirst = matched.batesFirst;
                                        f.batesLast = matched.batesLast;
                                    }
                                });
                            }
                        } else if (batesState.files && batesState.files.length > 0) {
                            // Fallback: old server without sidecar — predict
                            // Bates numbers from the preview's page counts.
                            var currentNum = startNum;
                            batesState.files.forEach(function(file) {
                                var pageCount = file.pageCount || 1;
                                var firstLabel = RLG.formatBatesLabel(prefix, currentNum, digits);
                                var lastLabel = RLG.formatBatesLabel(prefix, currentNum + pageCount - 1, digits);
                                lastBates.files.push({
                                    name: file.name,
                                    path: file.fullPath || file.name,
                                    category: getCategoryFromPath(file.fullPath),
                                    batesRange: pageCount > 1 ? firstLabel + ' - ' + lastLabel : firstLabel
                                });
                                currentNum += pageCount;
                            });
                        }

                        // Calculate final label for display. Prefer the last
                        // entry of lastBates.files (covers both sidecar and
                        // prediction paths). Falls back to prediction-only
                        // formula if lastBates.files is empty.
                        var finalLabel = '';
                        if (lastBates.files.length > 0) {
                            var lastRange = lastBates.files[lastBates.files.length - 1].batesRange || '';
                            finalLabel = lastRange.indexOf(' - ') !== -1
                                ? lastRange.split(' - ')[1].trim()
                                : lastRange.trim();
                        }
                        if (!finalLabel) {
                            var totalPages = 0;
                            if (batesState.files) {
                                batesState.files.forEach(function(f) { totalPages += (f.pageCount || 1); });
                            }
                            finalLabel = RLG.formatBatesLabel(prefix, startNum + Math.max(totalPages - 1, 0), digits);
                        }

                        $('#bates-final-number')
                            .html('<strong>Final label used:</strong> ' + finalLabel)
                            .slideDown(200);

                        if ($('input[name="index_source"][value="last_bates"]').is(':checked')) {
                            $('#last-bates-info').html('<span style="color:#047857;">&#10003; Last Bates output ready (' + lastBates.filename + ')</span>');
                            RLG.updateIndexPreview();
                        }

                        // Generate and show the index preview
                        RLG.generateBatesIndexPreview();

                        var batesNotice = failureNotice(result.failedFiles);
                        if (batesNotice) {
                            $status.html('<span class="rlg-status success">Done — download started.</span>' + batesNotice);
                        } else {
                            $status.html('<span class="rlg-status success">Complete! Download started.</span>');
                        }
                        triggerDownload();
                    });
                } else {
                    var notice = failureNotice(result.failedFiles);
                    if (notice) {
                        $status.html('<span class="rlg-status success">Done — download started.</span>' + notice);
                    } else {
                        $status.html('<span class="rlg-status success">Success! Download started.</span>');
                    }
                    triggerDownload();
                }
            })
            .catch(function(error) {
                clearTimeout(timeoutId);
                if (error.name === 'AbortError') {
                    error = new Error('Request timed out. The file may be large or the server may be starting up – wait a moment and try again.');
                }
                console.error('Error:', error);
                $status.html('<div class="rlg-status error">' +
                    '<strong>Error:</strong> ' + error.message + '<br>' +
                    '<small>Attempted to connect to: ' + apiUrl + '</small><br>' +
                    '<small>Check console (F12) for details.</small>' +
                    '</div>');
                $btn.prop('disabled', false);
            });
    });

    console.log('RLG Discovery Integration v1.4.1 initialized');

})(jQuery);
