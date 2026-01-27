/**
 * RLG Discovery - Bates Preview Module
 * Canvas preview rendering with Bates label overlay
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;
    var state = RLG.batesPreviewState;

    /**
     * Generate the Bates index preview table (summary of files with Bates ranges)
     */
    RLG.generateBatesIndexPreview = function() {
        var $indexPreview = $('#index-preview');
        if (!$indexPreview.length) return;

        var files = state.files;
        if (!files || files.length === 0) {
            $indexPreview.find('.rlg-preview-placeholder').show();
            $indexPreview.find('.rlg-preview-table-container').hide();
            return;
        }

        var prefix = $('#bates-prefix').val();
        var startNum = parseInt($('#bates-start').val()) || 1;
        var digits = parseInt($('#bates-digits').val()) || 8;
        var colorHex = $('#bates-color').val() || '#0000FF';

        // Get color name from hex
        var colorName = RLG.getColorName(colorHex);

        // Get today's date
        var today = new Date();
        var dateStr = today.toISOString().split('T')[0];

        var currentNum = startNum;
        var rows = [];
        var hasLoadingFiles = false;

        files.forEach(function(file) {
            var pageCount = file.pageCount;
            var isLoading = (pageCount === undefined);
            if (isLoading) {
                hasLoadingFiles = true;
                pageCount = 1; // Assume 1 for now
            }

            var firstLabel = RLG.formatBatesLabel(prefix, currentNum, digits);
            var lastLabel = RLG.formatBatesLabel(prefix, currentNum + pageCount - 1, digits);
            var batesRange;

            if (isLoading) {
                batesRange = firstLabel + ' - ...';
            } else {
                batesRange = pageCount > 1 ? firstLabel + ' - ' + lastLabel : firstLabel;
            }

            // Extract category from folder path
            var category = '';
            if (file.fullPath) {
                var parts = file.fullPath.split('/');
                if (parts.length > 1) {
                    category = parts[parts.length - 2]; // Parent folder name
                }
            }

            rows.push({
                date: dateStr,
                color: colorName,
                colorHex: colorHex,
                category: category,
                filename: file.name,
                batesRange: batesRange,
                isLoading: isLoading
            });

            currentNum += pageCount;
        });

        // Build table rows
        var $tbody = $indexPreview.find('#index-preview-table tbody');
        $tbody.empty();

        rows.forEach(function(row) {
            var rowClass = row.isLoading ? 'rlg-loading' : '';
            var colorCell = '<span class="rlg-color-badge" style="background-color: ' + row.colorHex + ';"></span>' + row.color;
            var tr = '<tr class="' + rowClass + '">' +
                '<td>' + row.date + '</td>' +
                '<td>' + (row.category || '-') + '</td>' +
                '<td>' + row.filename + '</td>' +
                '<td>' + row.batesRange + '</td>' +
                '</tr>';
            $tbody.append(tr);
        });

        // Update info
        var infoText = files.length + ' file' + (files.length !== 1 ? 's' : '');
        if (hasLoadingFiles) {
            infoText += ' (loading page counts...)';
        }
        $indexPreview.find('.rlg-preview-info').html(infoText);

        // Show table, hide placeholder
        $indexPreview.find('.rlg-preview-placeholder').hide();
        $indexPreview.find('.rlg-preview-table-container').show();
    };

    /**
     * Update the Bates preview canvas with label overlay
     */
    RLG.updateBatesPreview = function() {
        var $preview = $('#bates-preview');
        if (!$preview.length) return;

        var $canvasContainer = $preview.find('.rlg-preview-canvas-container');
        var canvas = document.getElementById('bates-preview-canvas');

        if (!canvas || !state.renderedImage) {
            return;
        }

        var ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Get form values
        var prefix = $('#bates-prefix').val();
        var startNum = parseInt($('#bates-start').val()) || 1;
        var digits = parseInt($('#bates-digits').val()) || 8;
        var colorHex = $('#bates-color').val() || '#0000FF';
        var fontSize = parseInt($('#bates-fontsize').val()) || 12;
        var zone = $('#bates-zone').val() || 'Bottom Right (Z3)';
        var zonePadding = parseFloat($('#bates-padding').val()) || 18;

        var label = RLG.formatBatesLabel(prefix, startNum, digits);

        // Get rendered image
        var img = state.renderedImage;
        var aspectRatio = img.width / img.height;

        // Calculate canvas dimensions
        var containerWidth = $canvasContainer.width() || 400;
        var canvasWidth = Math.max(200, containerWidth - 32);
        var canvasHeight = canvasWidth / aspectRatio;

        if (canvasHeight > 600) {
            canvasHeight = 600;
            canvasWidth = canvasHeight * aspectRatio;
        }

        canvas.width = canvasWidth;
        canvas.height = canvasHeight;

        // Draw the document
        ctx.drawImage(img, 0, 0, canvasWidth, canvasHeight);

        // Calculate label positioning (simulate PDF points)
        var scale = canvasWidth / 612; // 612 = US Letter width in points
        var scaledFontSize = Math.max(10, fontSize * scale * 1.2);
        var padding = zonePadding * scale;

        // Set font and measure text
        var boldSelect = document.getElementById('bates-fontbold')

        if (boldSelect.checked) {
            ctx.font = 'bold ' + scaledFontSize + 'px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
        } else {
            ctx.font = scaledFontSize + 'px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
        }
        var textMetrics = ctx.measureText(label);
        var textWidth = textMetrics.width;

        // Calculate position based on zone
        var x, y;
        if (zone.indexOf('Left') !== -1) {
            x = padding;
        } else if (zone.indexOf('Center') !== -1) {
            x = (canvasWidth - textWidth) / 2;
        } else {
            x = canvasWidth - textWidth - padding;
        }
        y = canvasHeight - padding;

        // Draw white outline for visibility
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.strokeText(label, x, y);

        // Draw the label
        ctx.fillStyle = colorHex;
        ctx.fillText(label, x, y);

        // Update preview info
        var $info = $canvasContainer.find('.rlg-preview-info');
        var currentFile = state.files[state.currentFileIndex];
        var fileName = currentFile ? currentFile.name : 'document';

        $info.html(
            '<span><span class="rlg-info-label">File:</span> ' + fileName + '</span>' +
            '<span><span class="rlg-info-label">Page:</span> ' + state.currentPage + '/' + state.totalPages + '</span>' +
            '<span><span class="rlg-info-label">Label:</span> ' + label + '</span>' +
            '<span><span class="rlg-info-label">Zone:</span> ' + zone.replace(/ \(Z\d\)/, '') + '</span>'
        );
    };

    /**
     * Update page navigation controls
     */
    RLG.updatePageControls = function() {
        var currentPage = state.currentPage;
        var totalPages = state.totalPages;

        // Update page indicator text
        $('#bates-current-page').text(currentPage);
        $('#bates-total-pages').text(totalPages);

        // Enable/disable navigation buttons
        var $prevBtn = $('.rlg-page-nav[data-direction="-1"]');
        var $nextBtn = $('.rlg-page-nav[data-direction="1"]');

        $prevBtn.prop('disabled', currentPage <= 1);
        $nextBtn.prop('disabled', currentPage >= totalPages);

        // Show/hide controls based on total pages
        if (totalPages <= 1) {
            $('.rlg-preview-controls').hide();
        } else {
            $('.rlg-preview-controls').show();
        }
    };

    /**
     * Render a specific PDF page
     * @param {PDFDocumentProxy} pdfDoc - PDF.js document
     * @param {number} pageNum - Page number (1-based)
     */
    RLG.renderPdfPage = function(pdfDoc, pageNum) {
        state.currentPage = pageNum;
        state.totalPages = pdfDoc.numPages;

        pdfDoc.getPage(pageNum).then(function(page) {
            // Render at 1.5x scale for good quality
            var scale = 1.5;
            var viewport = page.getViewport({ scale: scale });

            // Create temporary canvas for PDF rendering
            var tempCanvas = document.createElement('canvas');
            var tempCtx = tempCanvas.getContext('2d');
            tempCanvas.width = viewport.width;
            tempCanvas.height = viewport.height;

            var renderContext = {
                canvasContext: tempCtx,
                viewport: viewport
            };

            page.render(renderContext).promise.then(function() {
                // Convert to image for overlay drawing
                var img = new Image();
                img.onload = function() {
                    state.renderedImage = img;
                    RLG.showBatesPreview();
                    RLG.updatePageControls();
                };
                img.src = tempCanvas.toDataURL();
            });
        });
    };

    /**
     * Show the Bates preview canvas
     */
    RLG.showBatesPreview = function() {
        var $preview = $('#bates-preview');
        var $placeholder = $preview.find('.rlg-preview-placeholder');
        var $canvasContainer = $preview.find('.rlg-preview-canvas-container');

        $placeholder.hide();
        $canvasContainer.css('display', 'flex');

        setTimeout(function() {
            RLG.updateBatesPreview();
        }, 50);
    };

    /**
     * Show preview error message
     * @param {string} message - Error message to display
     */
    RLG.showPreviewError = function(message) {
        var $preview = $('#bates-preview');
        var $placeholder = $preview.find('.rlg-preview-placeholder');
        $placeholder.find('p').text(message);
        $placeholder.show();
        $preview.find('.rlg-preview-canvas-container').hide();
    };

    /**
     * Update file selector dropdown
     */
    RLG.updateFileSelector = function() {
        var $preview = $('#bates-preview');
        var $selector = $preview.find('.rlg-preview-file-selector');

        if (state.files.length <= 1) {
            $selector.hide();
            return;
        }

        var html = '<select id="bates-file-select">';
        state.files.forEach(function(file, index) {
            var selected = index === state.currentFileIndex ? ' selected' : '';
            html += '<option value="' + index + '"' + selected + '>' + file.name + '</option>';
        });
        html += '</select>';

        if (!$selector.length) {
            $preview.prepend('<div class="rlg-preview-file-selector">' + html + '</div>');
        } else {
            $selector.html(html).show();
        }
    };

    // Handle page navigation for multi-page PDFs
    $(document).on('click', '.rlg-page-nav', function() {
        var direction = $(this).data('direction');
        var newPage = state.currentPage + direction;

        if (newPage >= 1 && newPage <= state.totalPages && state.pdfDoc) {
            RLG.renderPdfPage(state.pdfDoc, newPage);
        }
    });

    // Update preview when form values change
    $(document).on('input change', '#bates-prefix, #bates-start, #bates-digits, #bates-color, #bates-fontsize, #bates-zone, #bates-padding, #bates-fontbold', function() {
        if (state.renderedImage) {
            RLG.updateBatesPreview();
        }
        // Also update index preview when label settings change
        if (state.files && state.files.length > 0) {
            RLG.generateBatesIndexPreview();
        }
    });

})(jQuery);
