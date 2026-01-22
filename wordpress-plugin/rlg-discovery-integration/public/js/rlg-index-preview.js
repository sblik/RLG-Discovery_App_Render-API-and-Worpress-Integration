/**
 * RLG Discovery - Index Preview Module
 * Index table preview for the Index tool
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;
    var indexState = RLG.indexPreviewState;
    var lastBates = RLG.lastBates;

    /**
     * Update the index preview table
     */
    RLG.updateIndexPreview = function() {
        var $preview = $('#index-preview');
        if (!$preview.length) return;

        var $placeholder = $preview.find('.rlg-preview-placeholder');
        var $tableContainer = $preview.find('.rlg-preview-table-container');
        var $tbody = $('#index-preview-table tbody');

        var source = $('input[name="index_source"]:checked').val();
        var party = $('#index-party').val() || 'Client';
        var partyClass = party === 'Client' ? 'rlg-party-client' : 'rlg-party-op';

        var files = [];

        if (source === 'last_bates' && lastBates.files.length > 0) {
            files = lastBates.files;
        } else if (source === 'upload') {
            // Use detected files from indexPreviewState if available
            if (indexState.files && indexState.files.length > 0) {
                files = indexState.files;
            } else {
                var fileInput = document.getElementById('index-files');
                if (fileInput && fileInput.files && fileInput.files.length > 0) {
                    files = [{
                        name: fileInput.files[0].name,
                        category: '(from uploaded ZIP)',
                        batesRange: 'Processing...',
                        isLoading: true
                    }];
                }
            }
        }

        if (files.length === 0) {
            $placeholder.show();
            $tableContainer.hide();
            return;
        }

        $placeholder.hide();
        $tableContainer.css('display', 'block');

        var today = new Date().toLocaleDateString('en-US', {
            month: '2-digit',
            day: '2-digit',
            year: 'numeric'
        });

        var html = '';
        files.forEach(function(file) {
            var rowClass = file.isLoading ? 'rlg-loading ' + partyClass : partyClass;
            var batesDisplay = file.isLoading ?
                '<span class="rlg-detecting">Detecting... <span class="rlg-spinner-small"></span></span>' :
                (file.batesRange || '');

            html += '<tr class="' + rowClass + '">' +
                '<td>' + today + '</td>' +
                '<td>' + (file.category || '') + '</td>' +
                '<td>' + file.name + '</td>' +
                '<td>' + batesDisplay + '</td>' +
                '</tr>';
        });

        $tbody.html(html);

        var $info = $tableContainer.find('.rlg-preview-info');
        $info.html(
            '<span><span class="rlg-info-label">Files:</span> ' + files.length + '</span>' +
            '<span><span class="rlg-info-label">Party:</span> ' + party + '</span>' +
            '<span><span class="rlg-info-label">Title:</span> ' + ($('#index-title').val() || 'CLIENT NAME - DOCUMENTS') + '</span>'
        );
    };

    // Handle index source/party/title changes
    $(document).on('change input', 'input[name="index_source"], #index-party, #index-title', function() {
        RLG.updateIndexPreview();
    });

    // Handle file input for Index tool
    $(document).on('change', '#index-files', async function() {
        var inputFiles = this.files;

        if (!inputFiles || inputFiles.length === 0) {
            indexState.files = [];
            RLG.updateIndexPreview();
            return;
        }

        var firstFile = inputFiles[0];
        var fileName = firstFile.name.toLowerCase();

        if (fileName.endsWith('.zip')) {
            // Reset state and show initial loading
            indexState.files = [];
            indexState.isProcessing = true;
            RLG.updateIndexPreview();

            var reader = new FileReader();
            reader.onload = async function(e) {
                await RLG.processIndexZipWithBatesDetection(e.target.result, function(files, isDone) {
                    indexState.files = files;
                    indexState.isProcessing = !isDone;
                    RLG.updateIndexPreview();
                });
            };
            reader.readAsArrayBuffer(firstFile);
        } else {
            indexState.files = [];
            RLG.updateIndexPreview();
        }
    });

})(jQuery);
