/**
 * RLG Discovery - Bates Detection Module
 * Client-side Bates label detection for PDF files
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;

    /**
     * Extract text from a specific PDF page using PDF.js
     * @param {PDFDocumentProxy} pdfDoc - PDF.js document object
     * @param {number} pageIndex - Zero-based page index
     * @returns {Promise<string>} - Extracted text
     */
    RLG.extractTextFromPdfPage = async function(pdfDoc, pageIndex) {
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
    };

    /**
     * Extract Bates label candidates from text using same regex as Python backend
     * @param {string} text - Text to search
     * @returns {Array<{prefix: string, number: string}>} - Array of candidates
     */
    RLG.extractBatesCandidates = function(text) {
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
    };

    /**
     * Get most common prefix from candidates
     * @param {Array} candidates - Array of candidate objects
     * @returns {string|null} - Most common prefix or null
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
     * @param {Array} candidates - Array of candidate objects
     * @returns {string|null} - Chosen prefix or null
     */
    RLG.chooseDominantPrefix = function(candidates) {
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
    };

    /**
     * Get the best formatted Bates token for a given prefix
     * @param {Array} candidates - Array of candidate objects
     * @param {string} wantPrefix - The prefix to match
     * @returns {string|null} - Formatted Bates token or null
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
    RLG.detectBatesFromPdf = async function(arrayBuffer) {
        try {
            var loadingTask = pdfjsLib.getDocument({ data: arrayBuffer.slice(0) });
            var pdfDoc = await loadingTask.promise;
            var pageCount = pdfDoc.numPages;

            // Extract text from first page
            var textFirst = await RLG.extractTextFromPdfPage(pdfDoc, 0);
            var candidatesFirst = RLG.extractBatesCandidates(textFirst);

            // Extract text from last page (if different from first)
            var textLast = '';
            var candidatesLast = [];
            var lastIndex = pageCount - 1;

            if (lastIndex > 0) {
                textLast = await RLG.extractTextFromPdfPage(pdfDoc, lastIndex);
                candidatesLast = RLG.extractBatesCandidates(textLast);
            } else {
                candidatesLast = candidatesFirst;
            }

            // Combine all candidates to find dominant prefix
            var allCandidates = candidatesFirst.concat(candidatesLast);
            var dominantPrefix = RLG.chooseDominantPrefix(allCandidates);

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
    };

    /**
     * Process a ZIP for Index tool with Bates detection
     * @param {ArrayBuffer} zipData - ZIP file data
     * @param {Function} progressCallback - Called with (files, isDone) to update UI
     */
    RLG.processIndexZipWithBatesDetection = async function(zipData, progressCallback) {
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
                        var detection = await RLG.detectBatesFromPdf(data);

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
    };

})(jQuery);
