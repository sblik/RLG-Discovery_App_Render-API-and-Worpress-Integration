<?php
if (!defined('ABSPATH')) {
    exit;
}

function rlg_discovery_add_admin_menu() {
    add_options_page(
        'RLG Discovery Settings',
        'RLG Discovery',
        'manage_options',
        'rlg-discovery',
        'rlg_discovery_options_page'
    );
}
add_action('admin_menu', 'rlg_discovery_add_admin_menu');

function rlg_discovery_settings_init() {
    register_setting('rlg_discovery', 'rlg_discovery_api_url');
    register_setting('rlg_discovery', 'rlg_discovery_api_key');

    add_settings_section(
        'rlg_discovery_section_developers',
        'API Configuration',
        'rlg_discovery_section_developers_cb',
        'rlg_discovery'
    );

    add_settings_field(
        'rlg_discovery_api_url',
        'API URL',
        'rlg_discovery_api_url_cb',
        'rlg_discovery',
        'rlg_discovery_section_developers'
    );

    add_settings_field(
        'rlg_discovery_api_key',
        'API Key',
        'rlg_discovery_api_key_cb',
        'rlg_discovery',
        'rlg_discovery_section_developers'
    );
}
add_action('admin_init', 'rlg_discovery_settings_init');

function rlg_discovery_section_developers_cb($args) {
    echo '<p>Enter the URL and API key for your deployed FastAPI service. Both values must match what is configured on Render.</p>';
}

function rlg_discovery_api_url_cb() {
    $setting = get_option('rlg_discovery_api_url');
    ?>
    <input type="text" name="rlg_discovery_api_url" value="<?php echo isset($setting) ? esc_attr($setting) : ''; ?>" class="regular-text">
    <?php
}

function rlg_discovery_api_key_cb() {
    $setting = get_option('rlg_discovery_api_key');
    ?>
    <input type="password" name="rlg_discovery_api_key" value="<?php echo isset($setting) ? esc_attr($setting) : ''; ?>" class="regular-text">
    <p class="description">Sent as the <code>X-API-Key</code> header on every request. Must match the <code>API_KEY</code> environment variable set on Render. Leave blank only in local development.</p>
    <?php
}

function rlg_discovery_options_page() {
    ?>
    <div class="wrap">
        <h2>RLG Discovery Settings</h2>
        <form action="options.php" method="post">
            <?php
            settings_fields('rlg_discovery');
            do_settings_sections('rlg_discovery');
            submit_button();
            ?>
        </form>
    </div>
    <?php
}
