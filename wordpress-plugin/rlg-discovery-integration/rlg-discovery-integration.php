<?php
/**
 * Plugin Name: RLG Discovery Integration
 * Description: Integrates RLG Discovery Tools (Unlock, Organize, Bates, Redact) via shortcodes.
 * Version: 1.2.0
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
    wp_enqueue_style('rlg-discovery-style', RLG_DISCOVERY_URL . 'public/css/style.css', array(), '1.2.0');

    // PDF.js from CDN for rendering actual PDF content
    wp_enqueue_script('pdf-js', 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js', array(), '3.11.174', true);

    // JSZip for extracting ZIP files client-side
    wp_enqueue_script('jszip', 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js', array(), '3.10.1', true);

    wp_enqueue_script('rlg-discovery-client', RLG_DISCOVERY_URL . 'public/js/api-client.js', array('jquery', 'pdf-js', 'jszip'), '1.2.0', true);

    // Pass API URL and PDF.js worker URL to JS
    $api_url = get_option('rlg_discovery_api_url', 'https://rlg-discovery-app-render-api-and-w0b0.onrender.com');
    wp_localize_script('rlg-discovery-client', 'rlgSettings', array(
        'apiUrl' => rtrim($api_url, '/'),
        'pdfWorkerUrl' => 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
    ));
}
add_action('wp_enqueue_scripts', 'rlg_discovery_enqueue_scripts');
