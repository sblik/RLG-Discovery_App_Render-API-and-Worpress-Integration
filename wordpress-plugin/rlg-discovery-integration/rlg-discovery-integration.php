<?php
/**
 * Plugin Name: RLG Discovery Integration
 * Description: Integrates RLG Discovery Tools (Unlock, Organize, Bates, Index, Redact, OCR, Pipeline) via shortcodes.
 * Version: 1.9.7
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
    $version = '1.9.7';
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

    // Pipeline shortcode script — drives the [rlg_pipeline] stepper UI.
    // Depends on rlg-core for RLGDiscovery.getApiUrl() / getApiKey().
    wp_enqueue_script('rlg-pipeline', $js_path . 'rlg-pipeline.js', array('rlg-core', 'jquery'), $version, true);

    // Localize settings on core module.
    // apiKey is passed to JS so every fetch() call can include it in the
    // X-API-Key header. The value is read-only from the browser's perspective
    // and is already visible in WP network traffic to authenticated portal
    // users — it protects against external callers, not insider threats.
    $api_url = get_option('rlg_discovery_api_url', 'https://discovery-one-stop.onrender.com');
    $api_key = get_option('rlg_discovery_api_key', '');
    wp_localize_script('rlg-core', 'rlgSettings', array(
        'apiUrl'     => rtrim($api_url, '/'),
        'apiKey'     => $api_key,
        'pdfWorkerUrl' => 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
    ));
}
add_action('wp_enqueue_scripts', 'rlg_discovery_enqueue_scripts');

// Single full-screen load splash, injected once at the top of <body> on any page
// that contains a discovery shortcode. Rendering it here (rather than inside each
// shortcode) guarantees exactly one splash when several tools and the pipeline
// share a page, and keeps it at body level so its fixed positioning reliably
// covers the viewport (a shortcode container can sit inside a transformed
// page-builder column). rlg-ui-controls.js fades and removes it on load.
function rlg_discovery_render_splash() {
    if (!is_singular()) {
        return;
    }
    $post = get_post();
    if (!$post) {
        return;
    }
    $shortcodes = array(
        'rlg_pipeline', 'rlg_discovery_tools', 'rlg_unlock', 'rlg_organize',
        'rlg_ocr', 'rlg_redact', 'rlg_bates', 'rlg_index',
    );
    $present = false;
    foreach ($shortcodes as $tag) {
        if (has_shortcode($post->post_content, $tag)) {
            $present = true;
            break;
        }
    }
    if (!$present) {
        return;
    }
    printf(
        '<div class="rlg-splash-overlay rlg-splash-fixed" id="rlg-splash"><img src="%spublic/images/SCOUT.png" alt="Scout"></div>',
        esc_url(RLG_DISCOVERY_URL)
    );
}
add_action('wp_body_open', 'rlg_discovery_render_splash');
