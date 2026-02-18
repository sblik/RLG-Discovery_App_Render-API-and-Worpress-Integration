/**
 * RLG Discovery - UI Controls Module
 * Tab switching, checkbox toggles, and index source selector
 */
(function($) {
    'use strict';

    var RLG = window.RLGDiscovery;
    var lastBates = RLG.lastBates;

    // Tab switching
    $(document).on('click', '.rlg-tab', function() {
        var $this = $(this);
        var tabId = $this.data('tab');
        var $container = $this.closest('.rlg-discovery-tabs-container');

        $container.find('.rlg-tab').removeClass('active');
        $this.addClass('active');

        $container.find('.rlg-tab-pane').removeClass('active');
        $container.find('#rlg-pane-' + tabId).addClass('active');

        if (tabId === 'bates' && RLG.batesPreviewState.renderedImage) {
            setTimeout(RLG.updateBatesPreview, 50);
        } else if (tabId === 'index') {
            setTimeout(RLG.updateIndexPreview, 50);
        }
    });

    // Checkbox toggle fields
    $(document).on('change', 'input[data-target]', function() {
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

    // Index source selector
    $(document).on('change', 'input[name="index_source"]', function() {
        var source = $(this).val();
        var $uploadGroup = $('#index-upload-group');
        var $lastBatesInfo = $('#last-bates-info');

        if (source === 'last_bates') {
            $uploadGroup.slideUp(200);
            if (lastBates.output) {
                $lastBatesInfo.html('<span style="color:#047857;">&#10003; Last Bates output ready (' + lastBates.filename + ')</span>').slideDown(200);
            } else {
                $lastBatesInfo.html('<span style="color:#d97706;">&#9888; No Bates output yet. Run Bates Labeler first.</span>').slideDown(200);
            }
        } else {
            $uploadGroup.slideDown(200);
            $lastBatesInfo.slideUp(200);
        }

        RLG.updateIndexPreview();
    });

    // Initialize UI state on DOM ready
    $(document).ready(function() {
        var $checked = $('input[name="index_source"]:checked');
        if ($checked.length && $checked.val() === 'last_bates') {
            $('#index-upload-group').hide();
            if (!lastBates.output) {
                $('#last-bates-info').html('<span style="color:#d97706;">&#9888; No Bates output yet. Run Bates Labeler first.</span>').show();
            }
        }
        var splash = document.getElementById('rlg-splash')
        if (splash) {
            var splashImg = splash.querySelector('img');
            var startFadeTimer = function() {
                setTimeout(function() {
                    splash.classList.add('rlg-splash-fade-out')
                }, 2400);
            };

            if (splashImg && splashImg.complete) {
                startFadeTimer();
            } else if (splashImg) {
                splashImg.addEventListener('load', startFadeTimer);
                splashImg.addEventListener('error', startFadeTimer);
            } else {
                startFadeTimer();
            }

            splash.addEventListener('animationend', function() {
                splash.parentElement.classList.remove('rlg-splash-active');
                splash.remove();
            })
        }
    });

    $(document).on('click', '.rlg-color-swatch', function() {
        var $this = $(this);
        var $container = $this.closest('.rlg-color-presets');
        var color = $this.data('color');

        // update active state
        $container.find('.rlg-color-swatch').removeClass('active');
        $this.addClass('active');

        // update hidden input value
        var inputId = $container.attr('id').replace('-presets', '');
        $('#' + inputId).val(color);

        // Refresh bates labeler with new selected color
        if (typeof RLG.updateBatesPreview === 'function') {
            RLG.updateBatesPreview();
        }
    });

})(jQuery);
