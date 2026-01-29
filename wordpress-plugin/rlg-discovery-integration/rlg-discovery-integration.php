<?php
/**
 * Plugin Name: RLG Discovery Integration
 * Description: Integrates RLG Discovery Tools (Unlock, Organize, Bates, Index, Redact, OCR) via shortcodes.
 * Version: 1.5.0
 * Author: RLG
 */

if (!defined('ABSPATH')) {
    exit;
}

// Define constants
define('RLG_DISCOVERY_PATH', plugin_dir_path(__FILE__));
define('RLG_DISCOVERY_URL', plugin_dir_url(__FILE__));

// Include Admin Settings
require_once RLG_DISCOVERY_PATH . 'admin/settings-page.php';

// Include Shortcodes
require_once RLG_DISCOVERY_PATH . 'public/shortcodes.php';

// Enqueue Scripts & Styles
function rlg_discovery_enqueue_scripts() {
    $version = '1.5.0';
    $js_path = RLG_DISCOVERY_URL . 'public/js/';

    // CSS
    wp_enqueue_style('rlg-discovery-style', RLG_DISCOVERY_URL . 'public/css/style.css', array(), $version);

    // External CDN dependencies
    wp_enqueue_script('pdf-js', 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js', array(), '3.11.174', true);
    wp_enqueue_script('jszip', 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js', array(), '3.10.1', true);

    // Module loading order
    wp_enqueue_script('rlg-core', $js_path . 'rlg-core.js', array('jquery'), $version, true);
    wp_enqueue_script('rlg-file-handlers', $js_path . 'rlg-file-handlers.js', array('rlg-core', 'pdf-js', 'jszip'), $version, true);
    wp_enqueue_script('rlg-bates-detection', $js_path . 'rlg-bates-detection.js', array('rlg-core', 'pdf-js', 'jszip'), $version, true);
    wp_enqueue_script('rlg-bates-preview', $js_path . 'rlg-bates-preview.js', array('rlg-core', 'rlg-file-handlers', 'pdf-js'), $version, true);
    wp_enqueue_script('rlg-index-preview', $js_path . 'rlg-index-preview.js', array('rlg-core', 'rlg-bates-detection'), $version, true);
    wp_enqueue_script('rlg-ui-controls', $js_path . 'rlg-ui-controls.js', array('rlg-core', 'rlg-bates-preview', 'rlg-index-preview'), $version, true);
    wp_enqueue_script('rlg-form-handler', $js_path . 'rlg-form-handler.js', array('rlg-core', 'rlg-bates-preview', 'rlg-index-preview'), $version, true);

    // Localize settings on core module
    $api_url = get_option('rlg_discovery_api_url', 'https://rlg-discovery-app-render-api-and-w0b0.onrender.com');
    wp_localize_script('rlg-core', 'rlgSettings', array(
        'apiUrl' => rtrim($api_url, '/'),
        'pdfWorkerUrl' => 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
    ));
}
add_action('wp_enqueue_scripts', 'rlg_discovery_enqueue_scripts');
