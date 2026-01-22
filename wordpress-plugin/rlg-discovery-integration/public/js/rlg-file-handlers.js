/**
 * RLG Discovery - File Handlers Module
 * ZIP extraction and file loading functions
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;
    var state = RLG.batesPreviewState;

    /**
     * Extract files from a ZIP archive
     * @param {ArrayBuffer} zipData - ZIP file data
     * @returns {Promise<Array>} - Array of {name, fullPath, data} objects
     */
    RLG.extractFilesFromZip = async function(zipData) {
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
    };

    /**
     * Load a PDF from ArrayBuffer and render the first page
     * @param {ArrayBuffer} arrayBuffer - PDF file data
     * @param {string} fileName - Name of the file
     */
    RLG.loadPdfFromArrayBuffer = function(arrayBuffer, fileName) {
        // Clone the ArrayBuffer so it can be reused (PDF.js consumes the original)
        var loadingTask = pdfjsLib.getDocument({ data: arrayBuffer.slice(0) });

        loadingTask.promise.then(function(pdfDoc) {
            state.pdfDoc = pdfDoc;
            // Store page count in the current file object
            var currentFile = state.files[state.currentFileIndex];
            if (currentFile) {
                currentFile.pageCount = pdfDoc.numPages;
            }
            RLG.renderPdfPage(pdfDoc, 1);
            RLG.updateFileSelector();
            RLG.generateBatesIndexPreview();
        }).catch(function(error) {
            console.error('PDF loading error:', error);
            RLG.showPreviewError('Could not load PDF: ' + error.message);
        });
    };

    /**
     * Load an image from ArrayBuffer
     * @param {ArrayBuffer} arrayBuffer - Image file data
     * @param {string} fileName - Name of the file
     */
    RLG.loadImageFromArrayBuffer = function(arrayBuffer, fileName) {
        var blob = new Blob([arrayBuffer]);
        var url = URL.createObjectURL(blob);

        var img = new Image();
        img.onload = function() {
            state.renderedImage = img;
            state.pdfDoc = null;
            state.currentPage = 1;
            state.totalPages = 1;
            // Store page count as 1 for images
            var currentFile = state.files[state.currentFileIndex];
            if (currentFile) {
                currentFile.pageCount = 1;
            }
            RLG.showBatesPreview();
            RLG.updateFileSelector();
            RLG.updatePageControls();
            URL.revokeObjectURL(url);
        };
        img.onerror = function() {
            RLG.showPreviewError('Could not load image');
            URL.revokeObjectURL(url);
        };
        img.src = url;
    };

    /**
     * Load file at a specific index in the files array
     * @param {number} index - Index of file to load
     */
    RLG.loadFileAtIndex = function(index) {
        if (index < 0 || index >= state.files.length) return;

        state.currentFileIndex = index;
        var file = state.files[index];
        var fileName = file.name.toLowerCase();

        if (fileName.endsWith('.pdf')) {
            RLG.loadPdfFromArrayBuffer(file.data, file.name);
        } else if (/\.(jpg|jpeg|png|gif|bmp)$/.test(fileName)) {
            RLG.loadImageFromArrayBuffer(file.data, file.name);
        }
    };

    /**
     * Load page counts for all files in batesPreviewState.files
     */
    RLG.loadAllPageCounts = async function() {
        var files = state.files;
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
                        RLG.generateBatesIndexPreview();
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
    };

    // Handle file input for Bates preview
    $(document).on('change', '#bates-files', async function() {
        var inputFiles = this.files;

        // Hide final number from previous run
        $('#bates-final-number').hide();

        if (!inputFiles || inputFiles.length === 0) {
            var $preview = $('#bates-preview');
            $preview.find('.rlg-preview-placeholder').show().find('p').text('Upload a file to see preview');
            $preview.find('.rlg-preview-canvas-container').hide();
            $preview.find('.rlg-preview-file-selector').hide();
            // Reset Discovery Index preview
            var $indexPreview = $('#index-preview');
            $indexPreview.find('.rlg-preview-placeholder').show();
            $indexPreview.find('.rlg-preview-table-container').hide();
            state.files = [];
            state.renderedImage = null;
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
                var files = await RLG.extractFilesFromZip(e.target.result);

                if (files.length === 0) {
                    RLG.showPreviewError('No PDF or image files found in ZIP');
                    // Reset Discovery Index preview
                    var $indexPreview = $('#index-preview');
                    $indexPreview.find('.rlg-preview-placeholder').show();
                    $indexPreview.find('.rlg-preview-table-container').hide();
                    return;
                }

                state.files = files;
                state.currentFileIndex = 0;

                // Show index preview immediately (with loading indicators)
                RLG.generateBatesIndexPreview();

                // Load first file for visual preview
                RLG.loadFileAtIndex(0);

                // Load page counts for all files in background
                RLG.loadAllPageCounts();
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
                state.files = files;
                state.currentFileIndex = 0;

                // Show index preview immediately (with loading indicators)
                RLG.generateBatesIndexPreview();

                // Load first file for visual preview
                RLG.loadFileAtIndex(0);

                // Load page counts for all files in background
                RLG.loadAllPageCounts();
            });

        } else if (fileName.endsWith('.pdf')) {
            // Single PDF
            var reader = new FileReader();
            reader.onload = function(e) {
                state.files = [{ name: firstFile.name, data: e.target.result }];
                state.currentFileIndex = 0;
                RLG.loadPdfFromArrayBuffer(e.target.result, firstFile.name);
                // Show index preview after loading (pageCount set in loadPdfFromArrayBuffer)
            };
            reader.readAsArrayBuffer(firstFile);

        } else if (/\.(jpg|jpeg|png|gif|bmp)$/.test(fileName)) {
            // Single image
            var reader = new FileReader();
            reader.onload = function(e) {
                state.files = [{ name: firstFile.name, data: e.target.result, pageCount: 1 }];
                state.currentFileIndex = 0;
                RLG.loadImageFromArrayBuffer(e.target.result, firstFile.name);
                RLG.generateBatesIndexPreview();
            };
            reader.readAsArrayBuffer(firstFile);
        }
    });

    // Handle file selector change
    $(document).on('change', '#bates-file-select', function() {
        var index = parseInt($(this).val());
        RLG.loadFileAtIndex(index);
    });

})(jQuery);
