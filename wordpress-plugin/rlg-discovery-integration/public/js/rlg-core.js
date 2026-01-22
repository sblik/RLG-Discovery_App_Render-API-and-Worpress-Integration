/**
 * RLG Discovery - Core Module
 * Global namespace, shared state, and utility functions
 */
(function($) {
    'use strict';

    // Initialize PDF.js worker
    if (typeof pdfjsLib !== 'undefined' && typeof rlgSettings !== 'undefined') {
        pdfjsLib.GlobalWorkerOptions.workerSrc = rlgSettings.pdfWorkerUrl;
    }

    // Global namespace
    window.RLGDiscovery = window.RLGDiscovery || {};

    // Shared state objects
    RLGDiscovery.batesPreviewState = {
        files: [],           // Array of {name, data, fullPath, pageCount} objects
        currentFileIndex: 0,
        pdfDoc: null,        // Current PDF document
        currentPage: 1,
        totalPages: 1,
        renderedImage: null  // Rendered page as Image object
    };

    RLGDiscovery.indexPreviewState = {
        files: [],           // Array of {name, fullPath, category, batesRange, isLoading}
        isProcessing: false
    };

    // Store last Bates output for use in Index tool
    RLGDiscovery.lastBates = {
        output: null,
        filename: null,
        files: []
    };

    // Simple event bus for cross-module communication
    RLGDiscovery.events = {
        _handlers: {},

        on: function(event, handler) {
            if (!this._handlers[event]) {
                this._handlers[event] = [];
            }
            this._handlers[event].push(handler);
        },

        off: function(event, handler) {
            if (!this._handlers[event]) return;
            var idx = this._handlers[event].indexOf(handler);
            if (idx !== -1) {
                this._handlers[event].splice(idx, 1);
            }
        },

        emit: function(event, data) {
            if (!this._handlers[event]) return;
            this._handlers[event].forEach(function(handler) {
                handler(data);
            });
        }
    };

    // Utility functions
    RLGDiscovery.formatBatesLabel = function(prefix, startNum, digits) {
        var numStr = String(startNum).padStart(parseInt(digits), '0');
        return prefix + ' ' + numStr;
    };

    RLGDiscovery.getColorName = function(hex) {
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
    };

    // Get API URL helper
    RLGDiscovery.getApiUrl = function() {
        return typeof rlgSettings !== 'undefined' ? rlgSettings.apiUrl : '';
    };

    console.log('RLG Discovery Core v1.4.0 initialized');

})(jQuery);
