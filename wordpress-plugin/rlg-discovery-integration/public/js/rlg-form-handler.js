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

        if (endpoint === '/index') {
            var source = $form.find('input[name="index_source"]:checked').val();
            if (source === 'last_bates') {
                if (!lastBates.output) {
                    $status.html('<span style="color:#dc2626;">No Bates output available. Please run Bates Labeler first or upload a ZIP.</span>');
                    return;
                }
                formData.delete('file');
                formData.append('file', lastBates.output, lastBates.filename);
            }
        }

        $status.html('<span class="rlg-status loading">Processing... <span class="rlg-spinner"></span></span>');
        $btn.prop('disabled', true);

        fetch(apiUrl, {
            method: 'POST',
            body: formData
        })
            .then(function(response) {
                if (!response.ok) {
                    return response.json().then(function(errData) {
                        var message = errData.detail || 'Request failed';
                        throw new Error(message);
                    }).catch(function(e) {
                        if (e.message && e.message !== 'Request failed') {
                            throw e;
                        }
                        throw new Error('Network response was not ok: ' + response.statusText);
                    });
                }
                return response.blob();
            })
            .then(function(blob) {
                if (endpoint === '/bates') {
                    lastBates.output = blob;
                    lastBates.filename = 'bates_labeled.zip';

                    // Use actual page counts from batesPreviewState if available
                    var prefix = $('#bates-prefix').val();
                    var startNum = parseInt($('#bates-start').val()) || 1;
                    var digits = parseInt($('#bates-digits').val()) || 8;

                    lastBates.files = [];
                    var currentNum = startNum;

                    if (batesState.files && batesState.files.length > 0) {
                        // Use preview state which has actual page counts
                        batesState.files.forEach(function(file) {
                            var pageCount = file.pageCount || 1;
                            var firstLabel = RLG.formatBatesLabel(prefix, currentNum, digits);
                            var lastLabel = RLG.formatBatesLabel(prefix, currentNum + pageCount - 1, digits);

                            lastBates.files.push({
                                name: file.name,
                                category: '',
                                batesRange: pageCount > 1 ? firstLabel + ' - ' + lastLabel : firstLabel
                            });
                            currentNum += pageCount;
                        });
                    }

                    // Calculate final number used (currentNum - 1 since we incremented after the last file)
                    var finalNumUsed = currentNum - 1;
                    var finalLabel = RLG.formatBatesLabel(prefix, finalNumUsed, digits);

                    // Display final number under the preview column
                    $('#bates-final-number')
                        .html('<strong>Final label used:</strong> ' + finalLabel)
                        .slideDown(200);

                    if ($('input[name="index_source"][value="last_bates"]').is(':checked')) {
                        $('#last-bates-info').html('<span style="color:#047857;">&#10003; Last Bates output ready (' + lastBates.filename + ')</span>');
                        RLG.updateIndexPreview();
                    }

                    // Generate and show the index preview
                    RLG.generateBatesIndexPreview();

                    $status.html('<span class="rlg-status success">Complete! Download started.</span>');
                } else {
                    $status.html('<span class="rlg-status success">Success! Download started.</span>');
                }

                var url = window.URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;

                var filename = 'download.zip';
                if (endpoint === '/unlock') filename = 'unlocked_pdfs.zip';
                if (endpoint === '/organize') filename = 'organized_by_year.zip';
                if (endpoint === '/bates') filename = 'bates_labeled.zip';
                if (endpoint === '/redact') filename = 'redacted_output.zip';
                if (endpoint === '/index') filename = 'discovery_index.xlsx';

                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);

                $btn.prop('disabled', false);
            })
            .catch(function(error) {
                console.error('Error:', error);
                $status.html('<div class="rlg-status error">' +
                    '<strong>Error:</strong> ' + error.message + '<br>' +
                    '<small>Attempted to connect to: ' + apiUrl + '</small><br>' +
                    '<small>Check console (F12) for details.</small>' +
                    '</div>');
                $btn.prop('disabled', false);
            });
    });

    console.log('RLG Discovery Integration v1.4.0 initialized');

})(jQuery);
