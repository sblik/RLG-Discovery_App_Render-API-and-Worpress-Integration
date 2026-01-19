jQuery(document).ready(function ($) {
    'use strict';

    // Initialize PDF.js worker
    if (typeof pdfjsLib !== 'undefined' && typeof rlgSettings !== 'undefined') {
        pdfjsLib.GlobalWorkerOptions.workerSrc = rlgSettings.pdfWorkerUrl;
    }

    // Store last Bates output for use in Index tool
    var lastBatesOutput = null;
    var lastBatesFilename = null;
    var lastBatesFiles = [];

    // Store Index preview state for uploaded ZIP Bates detection
    var indexPreviewState = {
        files: [],           // Array of {name, fullPath, category, batesRange, isLoading}
        isProcessing: false
    };

    // =========================================================================
    // BATES PREVIEW FUNCTIONALITY
    // =========================================================================
    var batesPreviewState = {
        files: [],           // Array of {name, data} objects
        currentFileIndex: 0,
        pdfDoc: null,        // Current PDF document
        currentPage: 1,
        totalPages: 1,
        renderedImage: null  // Rendered page as Image object
    };

    function formatBatesLabel(prefix, startNum, digits) {
        var numStr = String(startNum).padStart(parseInt(digits), '0');
        return prefix + ' ' + numStr;
    }

    function generateBatesIndexPreview() {
        var $indexPreview = $('#index-preview');
        if (!$indexPreview.length) return;

        var files = batesPreviewState.files;
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
        var colorName = getColorName(colorHex);

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

            var firstLabel = formatBatesLabel(prefix, currentNum, digits);
            var lastLabel = formatBatesLabel(prefix, currentNum + pageCount - 1, digits);
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
    }

    function getColorName(hex) {
        var colors = {
            '#0000ff': 'Blue',
            '#ff0000': 'Red',
            '#00ff00': 'Green',
            '#008000': 'Green',
            '#000000': 'Black',
            '#ffffff': 'White',
            '#ffff00': 'Yellow',
            '#ffa500': 'Orange',
            '#800080': 'Purple',
            '#ffc0cb': 'Pink',
            '#a52a2a': 'Brown',
            '#808080': 'Gray'
        };
        var lowerHex = hex.toLowerCase();
        return colors[lowerHex] || hex;
    }

    function updateBatesPreview() {
        var $preview = $('#bates-preview');
        if (!$preview.length) return;

        var $canvasContainer = $preview.find('.rlg-preview-canvas-container');
        var canvas = document.getElementById('bates-preview-canvas');

        if (!canvas || !batesPreviewState.renderedImage) {
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

        var label = formatBatesLabel(prefix, startNum, digits);

        // Get rendered image
        var img = batesPreviewState.renderedImage;
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
        ctx.font = 'bold ' + scaledFontSize + 'px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
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
        var currentFile = batesPreviewState.files[batesPreviewState.currentFileIndex];
        var fileName = currentFile ? currentFile.name : 'document';

        $info.html(
            '<span><span class="rlg-info-label">File:</span> ' + fileName + '</span>' +
            '<span><span class="rlg-info-label">Page:</span> ' + batesPreviewState.currentPage + '/' + batesPreviewState.totalPages + '</span>' +
            '<span><span class="rlg-info-label">Label:</span> ' + label + '</span>' +
            '<span><span class="rlg-info-label">Zone:</span> ' + zone.replace(/ \(Z\d\)/, '') + '</span>'
        );
    }

    function updatePageControls() {
        var currentPage = batesPreviewState.currentPage;
        var totalPages = batesPreviewState.totalPages;

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
    }

    function renderPdfPage(pdfDoc, pageNum) {
        batesPreviewState.currentPage = pageNum;
        batesPreviewState.totalPages = pdfDoc.numPages;

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
                    batesPreviewState.renderedImage = img;
                    showBatesPreview();
                    updatePageControls();
                };
                img.src = tempCanvas.toDataURL();
            });
        });
    }

    function loadPdfFromArrayBuffer(arrayBuffer, fileName) {
        // Clone the ArrayBuffer so it can be reused (PDF.js consumes the original)
        var loadingTask = pdfjsLib.getDocument({ data: arrayBuffer.slice(0) });

        loadingTask.promise.then(function(pdfDoc) {
            batesPreviewState.pdfDoc = pdfDoc;
            // Store page count in the current file object
            var currentFile = batesPreviewState.files[batesPreviewState.currentFileIndex];
            if (currentFile) {
                currentFile.pageCount = pdfDoc.numPages;
            }
            renderPdfPage(pdfDoc, 1);
            updateFileSelector();
            generateBatesIndexPreview();
        }).catch(function(error) {
            console.error('PDF loading error:', error);
            showPreviewError('Could not load PDF: ' + error.message);
        });
    }

    function loadImageFromArrayBuffer(arrayBuffer, fileName) {
        var blob = new Blob([arrayBuffer]);
        var url = URL.createObjectURL(blob);

        var img = new Image();
        img.onload = function() {
            batesPreviewState.renderedImage = img;
            batesPreviewState.pdfDoc = null;
            batesPreviewState.currentPage = 1;
            batesPreviewState.totalPages = 1;
            // Store page count as 1 for images
            var currentFile = batesPreviewState.files[batesPreviewState.currentFileIndex];
            if (currentFile) {
                currentFile.pageCount = 1;
            }
            showBatesPreview();
            updateFileSelector();
            updatePageControls();
            URL.revokeObjectURL(url);
        };
        img.onerror = function() {
            showPreviewError('Could not load image');
            URL.revokeObjectURL(url);
        };
        img.src = url;
    }

    function showBatesPreview() {
        var $preview = $('#bates-preview');
        var $placeholder = $preview.find('.rlg-preview-placeholder');
        var $canvasContainer = $preview.find('.rlg-preview-canvas-container');

        $placeholder.hide();
        $canvasContainer.css('display', 'flex');

        setTimeout(function() {
            updateBatesPreview();
        }, 50);
    }

    function showPreviewError(message) {
        var $preview = $('#bates-preview');
        var $placeholder = $preview.find('.rlg-preview-placeholder');
        $placeholder.find('p').text(message);
        $placeholder.show();
        $preview.find('.rlg-preview-canvas-container').hide();
    }

    function updateFileSelector() {
        var $preview = $('#bates-preview');
        var $selector = $preview.find('.rlg-preview-file-selector');

        if (batesPreviewState.files.length <= 1) {
            $selector.hide();
            return;
        }

        var html = '<select id="bates-file-select">';
        batesPreviewState.files.forEach(function(file, index) {
            var selected = index === batesPreviewState.currentFileIndex ? ' selected' : '';
            html += '<option value="' + index + '"' + selected + '>' + file.name + '</option>';
        });
        html += '</select>';

        if (!$selector.length) {
            $preview.prepend('<div class="rlg-preview-file-selector">' + html + '</div>');
        } else {
            $selector.html(html).show();
        }
    }

    function loadFileAtIndex(index) {
        if (index < 0 || index >= batesPreviewState.files.length) return;

        batesPreviewState.currentFileIndex = index;
        var file = batesPreviewState.files[index];
        var fileName = file.name.toLowerCase();

        if (fileName.endsWith('.pdf')) {
            loadPdfFromArrayBuffer(file.data, file.name);
        } else if (/\.(jpg|jpeg|png|gif|bmp)$/.test(fileName)) {
            loadImageFromArrayBuffer(file.data, file.name);
        }
    }

    // Load page counts for all files in batesPreviewState.files
    async function loadAllPageCounts() {
        var files = batesPreviewState.files;
        if (!files || files.length === 0) return;

        var loadPromises = files.map(function(file, index) {
            return new Promise(function(resolve) {
                var fileName = file.name.toLowerCase();

                if (fileName.endsWith('.pdf') && file.data) {
                    // Load PDF to get page count
                    var loadingTask = pdfjsLib.getDocument({ data: file.data.slice(0) });
                    loadingTask.promise.then(function(pdfDoc) {
                        file.pageCount = pdfDoc.numPages;
                        resolve();
                        // Update index preview as each file loads
                        generateBatesIndexPreview();
                    }).catch(function() {
                        file.pageCount = 1; // Default on error
                        resolve();
                    });
                } else if (/\.(jpg|jpeg|png|gif|bmp)$/.test(fileName)) {
                    file.pageCount = 1;
                    resolve();
                } else {
                    file.pageCount = 1;
                    resolve();
                }
            });
        });

        await Promise.all(loadPromises);
    }

    async function extractFilesFromZip(zipData) {
        if (typeof JSZip === 'undefined') {
            console.error('JSZip not loaded');
            return [];
        }

        try {
            var zip = await JSZip.loadAsync(zipData);
            var files = [];

            for (var filename in zip.files) {
                var zipEntry = zip.files[filename];

                // Skip directories and macOS junk
                if (zipEntry.dir) continue;
                if (filename.startsWith('__MACOSX/')) continue;
                if (filename.startsWith('._')) continue;
                if (filename.toLowerCase().includes('.ds_store')) continue;

                var lowerName = filename.toLowerCase();
                if (lowerName.endsWith('.pdf') || /\.(jpg|jpeg|png|gif|bmp)$/.test(lowerName)) {
                    var data = await zipEntry.async('arraybuffer');
                    files.push({
                        name: filename.split('/').pop(), // Just the filename
                        fullPath: filename,
                        data: data
                    });
                }
            }

            // Sort files naturally
            files.sort(function(a, b) {
                return a.name.localeCompare(b.name, undefined, { numeric: true });
            });

            return files;
        } catch (error) {
            console.error('ZIP extraction error:', error);
            return [];
        }
    }

    // =========================================================================
    // CLIENT-SIDE BATES DETECTION FOR INDEX TOOL
    // =========================================================================

    /**
     * Extract text from a specific PDF page using PDF.js
     * @param {PDFDocumentProxy} pdfDoc - PDF.js document object
     * @param {number} pageIndex - Zero-based page index
     * @returns {Promise<string>} - Extracted text
     */
    async function extractTextFromPdfPage(pdfDoc, pageIndex) {
        try {
            var page = await pdfDoc.getPage(pageIndex + 1); // PDF.js uses 1-based indexing
            var textContent = await page.getTextContent();
            var textItems = textContent.items;

            // Concatenate text items with spaces
            var text = textItems.map(function(item) {
                return item.str;
            }).join(' ');

            return text;
        } catch (error) {
            console.warn('Failed to extract text from page ' + pageIndex + ':', error);
            return '';
        }
    }

    /**
     * Extract Bates label candidates from text using same regex as Python backend
     * @param {string} text - Text to search
     * @returns {Array<{prefix: string, number: string}>} - Array of candidates
     */
    function extractBatesCandidates(text) {
        if (!text) return [];

        // More restrictive regex - prefix cannot contain spaces (only letters, numbers, dots)
        // This prevents capturing random PDF text as part of the prefix
        var BATES_REGEX = /\b([A-Z][A-Z0-9.]{0,20})[\s\-–—]+([0-9]{6,10})\b/g;

        // Blacklist matching Python backend
        var BLACKLIST = ['MONTHLY', 'BOX', 'ID', 'TARGET', 'REQUESTED', 'MISC', 'PAGE', 'LOREM', 'IPSUM'];

        var candidates = [];
        var upperText = text.toUpperCase();
        var match;

        while ((match = BATES_REGEX.exec(upperText)) !== null) {
            var prefix = match[1].replace(/[.]+$/, '').trim(); // Remove trailing dots
            var number = match[2];

            // Skip if prefix is blacklisted or too short
            if (prefix.length >= 2 && BLACKLIST.indexOf(prefix) === -1) {
                candidates.push({
                    prefix: prefix,
                    number: number
                });
            }
        }

        return candidates;
    }

    /**
     * Get most common prefix from candidates
     */
    function getMostCommonPrefix(candidates) {
        var counts = {};
        candidates.forEach(function(c) {
            counts[c.prefix] = (counts[c.prefix] || 0) + 1;
        });

        var maxCount = 0;
        var bestPrefix = null;
        for (var prefix in counts) {
            if (counts[prefix] > maxCount) {
                maxCount = counts[prefix];
                bestPrefix = prefix;
            }
        }
        return bestPrefix;
    }

    /**
     * Choose the most likely Bates prefix from candidates
     * Prefers zero-padded numbers, then most common prefix
     */
    function chooseDominantPrefix(candidates) {
        if (!candidates || candidates.length === 0) return null;

        // Helper: check if number is zero-padded
        function isZeroPadded(num) {
            return num.length >= 6 && num[0] === '0';
        }

        // First try: zero-padded candidates
        var zeroPadded = candidates.filter(function(c) {
            return isZeroPadded(c.number);
        });

        if (zeroPadded.length > 0) {
            return getMostCommonPrefix(zeroPadded);
        }

        return getMostCommonPrefix(candidates);
    }

    /**
     * Get the best formatted Bates token for a given prefix
     */
    function getBestTokenForPrefix(candidates, wantPrefix) {
        // First try zero-padded
        for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            if (c.prefix === wantPrefix && c.number.length >= 6 && c.number[0] === '0') {
                return c.prefix + ' ' + c.number;
            }
        }

        // Then any match
        for (var j = 0; j < candidates.length; j++) {
            var c2 = candidates[j];
            if (c2.prefix === wantPrefix) {
                return c2.prefix + ' ' + c2.number;
            }
        }

        return null;
    }

    /**
     * Detect Bates labels from a PDF file
     * @param {ArrayBuffer} arrayBuffer - PDF file data
     * @returns {Promise<{first: string|null, last: string|null, pageCount: number}>}
     */
    async function detectBatesFromPdf(arrayBuffer) {
        try {
            var loadingTask = pdfjsLib.getDocument({ data: arrayBuffer.slice(0) });
            var pdfDoc = await loadingTask.promise;
            var pageCount = pdfDoc.numPages;

            // Extract text from first page
            var textFirst = await extractTextFromPdfPage(pdfDoc, 0);
            var candidatesFirst = extractBatesCandidates(textFirst);

            // Extract text from last page (if different from first)
            var textLast = '';
            var candidatesLast = [];
            var lastIndex = pageCount - 1;

            if (lastIndex > 0) {
                textLast = await extractTextFromPdfPage(pdfDoc, lastIndex);
                candidatesLast = extractBatesCandidates(textLast);
            } else {
                candidatesLast = candidatesFirst;
            }

            // Combine all candidates to find dominant prefix
            var allCandidates = candidatesFirst.concat(candidatesLast);
            var dominantPrefix = chooseDominantPrefix(allCandidates);

            if (!dominantPrefix) {
                return { first: null, last: null, pageCount: pageCount };
            }

            // Get best tokens for first and last
            var firstToken = getBestTokenForPrefix(candidatesFirst, dominantPrefix) ||
                             getBestTokenForPrefix(allCandidates, dominantPrefix);
            var lastToken = getBestTokenForPrefix(candidatesLast, dominantPrefix) ||
                            getBestTokenForPrefix(allCandidates.slice().reverse(), dominantPrefix);

            // Handle single-page or missing tokens
            if (!firstToken && !lastToken) {
                return { first: null, last: null, pageCount: pageCount };
            }
            if (firstToken && !lastToken) {
                lastToken = firstToken;
            }
            if (lastToken && !firstToken) {
                firstToken = lastToken;
            }

            // Ensure first <= last numerically
            var numFirstMatch = firstToken.match(/(\d{6,10})$/);
            var numLastMatch = lastToken.match(/(\d{6,10})$/);
            if (numFirstMatch && numLastMatch) {
                var numFirst = parseInt(numFirstMatch[1], 10);
                var numLast = parseInt(numLastMatch[1], 10);
                if (numLast < numFirst) {
                    var temp = firstToken;
                    firstToken = lastToken;
                    lastToken = temp;
                }
            }

            return { first: firstToken, last: lastToken, pageCount: pageCount };

        } catch (error) {
            console.warn('Bates detection failed:', error);
            return { first: null, last: null, pageCount: 1 };
        }
    }

    /**
     * Process a ZIP for Index tool with Bates detection
     * @param {ArrayBuffer} zipData - ZIP file data
     * @param {Function} progressCallback - Called with (files, isDone) to update UI
     */
    async function processIndexZipWithBatesDetection(zipData, progressCallback) {
        if (typeof JSZip === 'undefined') {
            console.error('JSZip not loaded');
            progressCallback([], true);
            return;
        }

        try {
            var zip = await JSZip.loadAsync(zipData);
            var pdfEntries = [];

            // Collect PDF entries
            for (var filename in zip.files) {
                var zipEntry = zip.files[filename];

                // Skip directories and macOS junk
                if (zipEntry.dir) continue;
                if (filename.startsWith('__MACOSX/')) continue;
                if (filename.startsWith('._')) continue;
                if (filename.toLowerCase().includes('.ds_store')) continue;

                var lowerName = filename.toLowerCase();
                if (lowerName.endsWith('.pdf')) {
                    pdfEntries.push({
                        entry: zipEntry,
                        filename: filename
                    });
                }
            }

            // Sort naturally
            pdfEntries.sort(function(a, b) {
                return a.filename.localeCompare(b.filename, undefined, { numeric: true });
            });

            if (pdfEntries.length === 0) {
                progressCallback([], true);
                return;
            }

            // Extract category from path
            function getCategoryFromPath(fullPath) {
                var parts = fullPath.split('/');
                if (parts.length > 1) {
                    return parts[parts.length - 2];
                }
                return '';
            }

            // Create initial file objects (with loading state)
            var files = pdfEntries.map(function(entry) {
                return {
                    name: entry.filename.split('/').pop(),
                    fullPath: entry.filename,
                    category: getCategoryFromPath(entry.filename),
                    batesRange: null,
                    isLoading: true
                };
            });

            // Show initial state with loading indicators
            progressCallback(files, false);

            // Process each PDF with concurrency limit
            var CONCURRENCY = 3;
            var currentIndex = 0;
            var completedCount = 0;

            async function processNext() {
                while (currentIndex < pdfEntries.length) {
                    var myIndex = currentIndex++;
                    var entry = pdfEntries[myIndex];
                    var file = files[myIndex];

                    try {
                        var data = await entry.entry.async('arraybuffer');
                        var detection = await detectBatesFromPdf(data);

                        file.pageCount = detection.pageCount;
                        file.isLoading = false;

                        if (detection.first && detection.last) {
                            if (detection.first === detection.last) {
                                file.batesRange = detection.first;
                            } else {
                                file.batesRange = detection.first + ' - ' + detection.last;
                            }
                        } else {
                            file.batesRange = 'Not detected';
                        }

                    } catch (error) {
                        file.isLoading = false;
                        file.batesRange = 'Error';
                        console.warn('Failed to process:', entry.filename, error);
                    }

                    completedCount++;
                    progressCallback(files, completedCount >= pdfEntries.length);
                }
            }

            // Start parallel processing
            var workers = [];
            for (var i = 0; i < Math.min(CONCURRENCY, pdfEntries.length); i++) {
                workers.push(processNext());
            }

            await Promise.all(workers);

        } catch (error) {
            console.error('ZIP processing error:', error);
            progressCallback([], true);
        }
    }

    // Handle file input for Bates preview
    $(document).on('change', '#bates-files', async function() {
        var inputFiles = this.files;

        if (!inputFiles || inputFiles.length === 0) {
            var $preview = $('#bates-preview');
            $preview.find('.rlg-preview-placeholder').show().find('p').text('Upload a file to see preview');
            $preview.find('.rlg-preview-canvas-container').hide();
            $preview.find('.rlg-preview-file-selector').hide();
            // Reset Discovery Index preview
            var $indexPreview = $('#index-preview');
            $indexPreview.find('.rlg-preview-placeholder').show();
            $indexPreview.find('.rlg-preview-table-container').hide();
            batesPreviewState.files = [];
            batesPreviewState.renderedImage = null;
            return;
        }

        var firstFile = inputFiles[0];
        var fileName = firstFile.name.toLowerCase();

        // Show loading state
        var $preview = $('#bates-preview');
        $preview.find('.rlg-preview-placeholder').find('p').text('Loading preview...');

        if (fileName.endsWith('.zip')) {
            // Extract files from ZIP
            var reader = new FileReader();
            reader.onload = async function(e) {
                var files = await extractFilesFromZip(e.target.result);

                if (files.length === 0) {
                    showPreviewError('No PDF or image files found in ZIP');
                    // Reset Discovery Index preview
                    var $indexPreview = $('#index-preview');
                    $indexPreview.find('.rlg-preview-placeholder').show();
                    $indexPreview.find('.rlg-preview-table-container').hide();
                    return;
                }

                batesPreviewState.files = files;
                batesPreviewState.currentFileIndex = 0;

                // Show index preview immediately (with loading indicators)
                generateBatesIndexPreview();

                // Load first file for visual preview
                loadFileAtIndex(0);

                // Load page counts for all files in background
                loadAllPageCounts();
            };
            reader.readAsArrayBuffer(firstFile);

        } else if (fileName.endsWith('.pdf')) {
            // Single PDF
            var reader = new FileReader();
            reader.onload = function(e) {
                batesPreviewState.files = [{ name: firstFile.name, data: e.target.result }];
                batesPreviewState.currentFileIndex = 0;
                loadPdfFromArrayBuffer(e.target.result, firstFile.name);
                // Show index preview after loading (pageCount set in loadPdfFromArrayBuffer)
            };
            reader.readAsArrayBuffer(firstFile);

        } else if (/\.(jpg|jpeg|png|gif|bmp)$/.test(fileName)) {
            // Single image
            var reader = new FileReader();
            reader.onload = function(e) {
                batesPreviewState.files = [{ name: firstFile.name, data: e.target.result, pageCount: 1 }];
                batesPreviewState.currentFileIndex = 0;
                loadImageFromArrayBuffer(e.target.result, firstFile.name);
                generateBatesIndexPreview();
            };
            reader.readAsArrayBuffer(firstFile);

        } else if (inputFiles.length > 1) {
            // Multiple files - load all
            var files = [];
            var loadPromises = [];

            Array.from(inputFiles).forEach(function(file) {
                var promise = new Promise(function(resolve) {
                    var reader = new FileReader();
                    reader.onload = function(e) {
                        files.push({ name: file.name, data: e.target.result });
                        resolve();
                    };
                    reader.readAsArrayBuffer(file);
                });
                loadPromises.push(promise);
            });

            Promise.all(loadPromises).then(function() {
                files.sort(function(a, b) {
                    return a.name.localeCompare(b.name, undefined, { numeric: true });
                });
                batesPreviewState.files = files;
                batesPreviewState.currentFileIndex = 0;
                loadFileAtIndex(0);
            });
        }
    });

    // Handle file selector change
    $(document).on('change', '#bates-file-select', function() {
        var index = parseInt($(this).val());
        loadFileAtIndex(index);
    });

    // Handle page navigation for multi-page PDFs
    $(document).on('click', '.rlg-page-nav', function() {
        var direction = $(this).data('direction');
        var newPage = batesPreviewState.currentPage + direction;

        if (newPage >= 1 && newPage <= batesPreviewState.totalPages && batesPreviewState.pdfDoc) {
            renderPdfPage(batesPreviewState.pdfDoc, newPage);
        }
    });

    // Update preview when form values change
    $(document).on('input change', '#bates-prefix, #bates-start, #bates-digits, #bates-color, #bates-fontsize, #bates-zone, #bates-padding', function() {
        if (batesPreviewState.renderedImage) {
            updateBatesPreview();
        }
        // Also update index preview when label settings change
        if (batesPreviewState.files && batesPreviewState.files.length > 0) {
            generateBatesIndexPreview();
        }
    });

    // =========================================================================
    // INDEX PREVIEW FUNCTIONALITY
    // =========================================================================
    function updateIndexPreview() {
        var $preview = $('#index-preview');
        if (!$preview.length) return;

        var $placeholder = $preview.find('.rlg-preview-placeholder');
        var $tableContainer = $preview.find('.rlg-preview-table-container');
        var $tbody = $('#index-preview-table tbody');

        var source = $('input[name="index_source"]:checked').val();
        var party = $('#index-party').val() || 'Client';
        var partyClass = party === 'Client' ? 'rlg-party-client' : 'rlg-party-op';

        var files = [];

        if (source === 'last_bates' && lastBatesFiles.length > 0) {
            files = lastBatesFiles;
        } else if (source === 'upload') {
            // Use detected files from indexPreviewState if available
            if (indexPreviewState.files && indexPreviewState.files.length > 0) {
                files = indexPreviewState.files;
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
    }

    $(document).on('change input', 'input[name="index_source"], #index-party, #index-title', function() {
        updateIndexPreview();
    });

    $(document).on('change', '#index-files', async function() {
        var inputFiles = this.files;

        if (!inputFiles || inputFiles.length === 0) {
            indexPreviewState.files = [];
            updateIndexPreview();
            return;
        }

        var firstFile = inputFiles[0];
        var fileName = firstFile.name.toLowerCase();

        if (fileName.endsWith('.zip')) {
            // Reset state and show initial loading
            indexPreviewState.files = [];
            indexPreviewState.isProcessing = true;
            updateIndexPreview();

            var reader = new FileReader();
            reader.onload = async function(e) {
                await processIndexZipWithBatesDetection(e.target.result, function(files, isDone) {
                    indexPreviewState.files = files;
                    indexPreviewState.isProcessing = !isDone;
                    updateIndexPreview();
                });
            };
            reader.readAsArrayBuffer(firstFile);
        } else {
            indexPreviewState.files = [];
            updateIndexPreview();
        }
    });

    // =========================================================================
    // TAB SWITCHING
    // =========================================================================
    $(document).on('click', '.rlg-tab', function () {
        var $this = $(this);
        var tabId = $this.data('tab');
        var $container = $this.closest('.rlg-discovery-tabs-container');

        $container.find('.rlg-tab').removeClass('active');
        $this.addClass('active');

        $container.find('.rlg-tab-pane').removeClass('active');
        $container.find('#rlg-pane-' + tabId).addClass('active');

        if (tabId === 'bates' && batesPreviewState.renderedImage) {
            setTimeout(updateBatesPreview, 50);
        } else if (tabId === 'index') {
            setTimeout(updateIndexPreview, 50);
        }
    });

    // =========================================================================
    // CHECKBOX TOGGLE FIELDS
    // =========================================================================
    $(document).on('change', 'input[data-target]', function () {
        var targetId = $(this).data('target');
        var $target = $('#' + targetId);
        var $input = $target.find('input');

        if ($(this).is(':checked')) {
            $target.slideDown(200);
        } else {
            $target.slideUp(200);
            $input.val(0);
        }
    });

    // =========================================================================
    // INDEX SOURCE SELECTOR
    // =========================================================================
    $(document).on('change', 'input[name="index_source"]', function () {
        var source = $(this).val();
        var $uploadGroup = $('#index-upload-group');
        var $lastBatesInfo = $('#last-bates-info');

        if (source === 'last_bates') {
            $uploadGroup.slideUp(200);
            if (lastBatesOutput) {
                $lastBatesInfo.html('<span style="color:#047857;">&#10003; Last Bates output ready (' + lastBatesFilename + ')</span>').slideDown(200);
            } else {
                $lastBatesInfo.html('<span style="color:#d97706;">&#9888; No Bates output yet. Run Bates Labeler first.</span>').slideDown(200);
            }
        } else {
            $uploadGroup.slideDown(200);
            $lastBatesInfo.slideUp(200);
        }

        updateIndexPreview();
    });

    // Initialize
    (function init() {
        var $checked = $('input[name="index_source"]:checked');
        if ($checked.length && $checked.val() === 'last_bates') {
            $('#index-upload-group').hide();
            if (!lastBatesOutput) {
                $('#last-bates-info').html('<span style="color:#d97706;">&#9888; No Bates output yet. Run Bates Labeler first.</span>').show();
            }
        }
    })();

    // =========================================================================
    // FORM SUBMISSION HANDLER
    // =========================================================================
    $(document).on('submit', '.rlg-discovery-form', function (e) {
        e.preventDefault();

        var $form = $(this);
        var $status = $form.find('.rlg-status');
        var $btn = $form.find('button[type="submit"]');

        var endpoint = $form.data('endpoint');
        var apiUrl = (typeof rlgSettings !== 'undefined' ? rlgSettings.apiUrl : '') + endpoint;

        var formData = new FormData(this);

        if (endpoint === '/index') {
            var source = $form.find('input[name="index_source"]:checked').val();
            if (source === 'last_bates') {
                if (!lastBatesOutput) {
                    $status.html('<span style="color:#dc2626;">No Bates output available. Please run Bates Labeler first or upload a ZIP.</span>');
                    return;
                }
                formData.delete('file');
                formData.append('file', lastBatesOutput, lastBatesFilename);
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
                    throw new Error('Network response was not ok: ' + response.statusText);
                }
                return response.blob();
            })
            .then(function(blob) {
                if (endpoint === '/bates') {
                    lastBatesOutput = blob;
                    lastBatesFilename = 'bates_labeled.zip';

                    // Use actual page counts from batesPreviewState if available
                    var prefix = $('#bates-prefix').val();
                    var startNum = parseInt($('#bates-start').val()) || 1;
                    var digits = parseInt($('#bates-digits').val()) || 8;

                    lastBatesFiles = [];
                    var currentNum = startNum;

                    if (batesPreviewState.files && batesPreviewState.files.length > 0) {
                        // Use preview state which has actual page counts
                        batesPreviewState.files.forEach(function(file) {
                            var pageCount = file.pageCount || 1;
                            var firstLabel = formatBatesLabel(prefix, currentNum, digits);
                            var lastLabel = formatBatesLabel(prefix, currentNum + pageCount - 1, digits);

                            lastBatesFiles.push({
                                name: file.name,
                                category: '',
                                batesRange: pageCount > 1 ? firstLabel + ' - ' + lastLabel : firstLabel
                            });
                            currentNum += pageCount;
                        });
                    }

                    if ($('input[name="index_source"][value="last_bates"]').is(':checked')) {
                        $('#last-bates-info').html('<span style="color:#047857;">&#10003; Last Bates output ready (' + lastBatesFilename + ')</span>');
                        updateIndexPreview();
                    }

                    // Generate and show the index preview
                    generateBatesIndexPreview();

                    $status.html('<span class="rlg-status success">Success! Download started.<br></span>');
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

    console.log('RLG Discovery Integration v1.2.0 initialized');
});
