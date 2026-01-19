<?php
if (!defined('ABSPATH')) {
    exit;
}

function rlg_shortcode_unlock($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool" id="rlg-unlock-tool">
        <h3>Unlock PDFs</h3>
        <p>Remove encryption from PDFs you are authorized to access.</p>
        <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/unlock" data-response-type="blob">
            <div class="rlg-form-group rlg-divider">
                <label>Upload PDFs or ZIP</label>
                <input type="file" name="files" multiple required accept=".pdf,.zip">
            </div>
            <section class="rlg-section-flex rlg-divider">
                <h4>Password Options</h4>
                <div class="rlg-form-group">
                    <label>Password Mode</label>
                    <select name="password_mode">
                        <option value="Single password for all">Single password for all</option>
                        <option value="Try no password (for unencrypted files)">Try no password</option>
                    </select>
                </div>
                <div class="rlg-form-group">
                    <label>Password (if single)</label>
                    <input type="password" name="password_for_all">
                </div>
            </section>
            <button type="submit" class="rlg-btn rlg-single-column-btn">Unlock Files</button>
            <div class="rlg-status"></div>
        </form>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_unlock', 'rlg_shortcode_unlock');

function rlg_shortcode_organize($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool" id="rlg-organize-tool">
        <h3>Organize by Year</h3>
        <p>Sort files into folders based on year detected in filename, metadata, or content.</p>
        <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/organize" data-response-type="blob">
            <div class="rlg-form-group rlg-divider">
                <label>Upload PDFs or ZIP</label>
                <input type="file" name="files" multiple required accept=".pdf,.zip">
            </div>
            <section class="rlg-section-flex rlg-divider">
                <h4>Year Settings</h4>
                <div class="rlg-form-group">
                    <label>Min Year</label>
                    <input type="number" name="min_year" value="1900">
                </div>
                <div class="rlg-form-group">
                    <label>Max Year</label>
                    <input type="number" name="max_year" value="2099">
                </div>
                <div class="rlg-form-group">
                    <label>Folder for files without a year</label>
                    <input type="text" name="unknown_folder" value="Unknown">
                </div>
            </section>
            <button type="submit" class="rlg-btn rlg-single-column-btn">Organize Files</button>
            <div class="rlg-status"></div>
        </form>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_organize', 'rlg_shortcode_organize');

function rlg_shortcode_bates($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool rlg-two-column-tool" id="rlg-bates-tool">
        <div class="rlg-tool-header">
            <h3>Bates Labeler</h3>
            <p>Sequential labeling across the entire folder tree.</p>
        </div>
        <div class="rlg-tool-columns">
            <!-- Left Column: Form Controls -->
            <div class="rlg-tool-form-column">
                <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/bates" data-response-type="blob" id="rlg-bates-form">
                    <div class="rlg-form-group rlg-divider">
                        <label>Upload PDFs or ZIP</label>
                        <input type="file" name="files" id="bates-files" multiple required accept=".pdf,.zip,.jpg,.png">
                    </div>
                    <section class="rlg-divider">
                        <h4>Label</h4>
                        <div class="rlg-form-group">
                            <label>Prefix</label>
                            <input type="text" name="prefix" id="bates-prefix" value="">
                        </div>
                        <div class="rlg-form-group">
                            <label>Start Number</label>
                            <input type="number" name="start_num" id="bates-start" value="1">
                        </div>
                        <div class="rlg-form-group">
                            <label>Digits</label>
                            <input type="number" name="digits" id="bates-digits" value="8" min="6" max="10">
                        </div>
                        <div class="rlg-form-group">
                            <label>Font Size (pt)</label>
                            <input type="number" name="font_size" id="bates-fontsize" value="12" min="6" max="36">
                        </div>
                        <div class="rlg-form-group">
                            <label>Label Color</label>
                            <input type="color" name="color_hex" id="bates-color" value="#0000FF">
                        </div>
                    </section>
                    <section class="rlg-divider">
                        <h4>Placement</h4>
                        <div class="rlg-form-group">
                            <label>Zone</label>
                            <select name="zone" id="bates-zone">
                                <option value="Bottom Right (Z3)">Bottom Right</option>
                                <option value="Bottom Center (Z2)">Bottom Center</option>
                                <option value="Bottom Left (Z1)">Bottom Left</option>
                            </select>
                        </div>
                        <div class="rlg-form-group">
                            <label>Padding (pt)</label>
                            <input type="number" name="zone_padding" id="bates-padding" value="18" min="1" max="144">
                        </div>
                    </section>
                    <section class="rlg-section-flex rlg-divider">
                        <h4>Page Options</h4>
                        <div class="rlg-form-group rlg-checkbox-toggle">
                            <label>
                                <input type="checkbox" id="toggle-punch-margin" data-target="punch-margin-field">
                                Add left margin for 3-hole punch
                            </label>
                        </div>
                        <div class="rlg-form-group rlg-toggle-field" id="punch-margin-field" style="display: none;">
                            <label>Punch Margin (pt)</label>
                            <input type="number" name="left_punch_margin" value="36" min="0" max="72">
                        </div>
                        <div class="rlg-form-group rlg-checkbox-toggle">
                            <label>
                                <input type="checkbox" id="toggle-border" data-target="border-field">
                                Add all-sides safety border
                            </label>
                        </div>
                        <div class="rlg-form-group rlg-toggle-field" id="border-field" style="display: none;">
                            <label>Border (pt)</label>
                            <input type="number" name="border_all_pt" value="12" min="0" max="36">
                        </div>
                    </section>
                    <button type="submit" class="rlg-btn">Label Files</button>
                    <div class="rlg-status"></div>
                </form>
            </div>
            <!-- Right Column: Preview -->
            <div class="rlg-tool-preview-column">
                <div class="rlg-preview-header">
                    <h4>Preview</h4>
                </div>
                <div class="rlg-preview-content" id="bates-preview">
                    <div class="rlg-preview-placeholder">
                        <div class="rlg-preview-icon">
                            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <rect x="3" y="3" width="18" height="18" rx="2"/>
                                <path d="M3 15l6-6 4 4 8-8"/>
                            </svg>
                        </div>
                        <p>Upload a file to see preview</p>
                    </div>
                    <div class="rlg-preview-canvas-container" style="display: none;">
                        <canvas id="bates-preview-canvas"></canvas>
                        <div class="rlg-preview-controls">
                            <button type="button" class="rlg-page-nav" data-direction="-1" title="Previous page">&larr;</button>
                            <span class="rlg-page-indicator">
                                <span id="bates-current-page">1</span> / <span id="bates-total-pages">1</span>
                            </span>
                            <button type="button" class="rlg-page-nav" data-direction="1" title="Next page">&rarr;</button>
                        </div>
                        <div class="rlg-preview-info"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_bates', 'rlg_shortcode_bates');

function rlg_shortcode_redact($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool" id="rlg-redact-tool">
        <h3>Redaction Tool</h3>
        <p>Automatically redact sensitive information from PDFs.</p>
        <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/redact" data-response-type="blob">
            <div class="rlg-form-group rlg-divider">
                <label>Upload PDF or ZIP</label>
                <input type="file" name="file" required accept=".pdf,.zip">
            </div>
            <section class="rlg-divider">
                <h4>Presets</h4>
                <div class="rlg-form-group">
                    <div class="rlg-checkbox-group">
                        <label><input type="checkbox" name="presets" value="SSN" checked> SSN</label>
                        <label><input type="checkbox" name="presets" value="Email"> Email</label>
                        <label><input type="checkbox" name="presets" value="Phone"> Phone</label>
                        <label><input type="checkbox" name="presets" value="Date"> Date</label>
                    </div>
                </div>
            </section>
            <section class="rlg-section-flex rlg-divider">
                <h4>Custom Patterns</h4>
                <div class="rlg-form-group">
                    <label>Regex Patterns (one per line)</label>
                    <textarea name="regex_patterns" rows="3" placeholder="e.g., \b\d{4}-\d{4}\b"></textarea>
                </div>
                <div class="rlg-form-group">
                    <label>Literal Patterns (comma separated)</label>
                    <input type="text" name="literal_patterns" placeholder="e.g., CONFIDENTIAL, SECRET">
                </div>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label>
                        <input type="checkbox" name="case_sensitive">
                        Case Sensitive
                    </label>
                </div>
            </section>
            <section class="rlg-section-flex rlg-divider">
                <h4>SSN Options</h4>
                <div class="rlg-form-group">
                    <label>Keep Last N Digits</label>
                    <input type="number" name="keep_last_digits" value="0" min="0" max="4">
                </div>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label>
                        <input type="checkbox" name="require_ssn_context" checked>
                        Require SSN Context Words
                    </label>
                </div>
            </section>
            <button type="submit" class="rlg-btn rlg-single-column-btn">Redact Files</button>
            <div class="rlg-status"></div>
        </form>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_redact', 'rlg_shortcode_redact');

function rlg_shortcode_index($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool rlg-two-column-tool" id="rlg-index-tool">
        <div class="rlg-tool-header">
            <h3>Discovery Index</h3>
            <p>Create an Excel matching the Master Discovery Spreadsheet style.</p>
        </div>
        <div class="rlg-tool-columns">
            <!-- Left Column: Form Controls -->
            <div class="rlg-tool-form-column">
                <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/index" data-response-type="blob" id="rlg-index-form">
                    <section class="rlg-divider">
                        <h4>Source</h4>
                        <div class="rlg-form-group">
                            <div class="rlg-radio-group">
                                <label>
                                    <input type="radio" name="index_source" value="last_bates" checked>
                                    Use last Bates output
                                </label>
                                <label>
                                    <input type="radio" name="index_source" value="upload">
                                    Upload labeled ZIP
                                </label>
                            </div>
                            <div id="last-bates-info" class="rlg-source-info"></div>
                        </div>
                        <div class="rlg-form-group" id="index-upload-group" style="display: none;">
                            <label>Upload ZIP of Labeled Files</label>
                            <input type="file" name="file" id="index-files" accept=".zip">
                        </div>
                    </section>
                    <section class="rlg-divider">
                        <h4>Formatting</h4>
                        <div class="rlg-form-group">
                            <label>Party Name</label>
                            <select name="party" id="index-party">
                                <option value="Client" selected>Client (light green rows)</option>
                                <option value="OP">OP (light blue rows)</option>
                            </select>
                        </div>
                        <div class="rlg-form-group">
                            <label>Title Text</label>
                            <input type="text" name="title_text" id="index-title" value="CLIENT NAME - DOCUMENTS">
                        </div>
                    </section>
                    <button type="submit" class="rlg-btn">Generate Index</button>
                    <div class="rlg-status"></div>
                </form>
            </div>
            <!-- Right Column: Preview -->
            <div class="rlg-tool-preview-column">
                <div class="rlg-preview-header">
                    <h4>Preview</h4>
                </div>
                <div class="rlg-preview-content" id="index-preview">
                    <div class="rlg-preview-placeholder">
                        <div class="rlg-preview-icon">
                            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <rect x="3" y="3" width="18" height="18" rx="2"/>
                                <path d="M3 9h18M9 3v18"/>
                            </svg>
                        </div>
                        <p>Index preview will appear here</p>
                    </div>
                    <div class="rlg-preview-table-container" style="display: none;">
                        <table class="rlg-index-preview-table" id="index-preview-table">
                            <thead>
                                <tr>
                                    <th>Date Produced</th>
                                    <th>Category</th>
                                    <th>Document Name</th>
                                    <th>Bates Range</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                        <div class="rlg-preview-info"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_index', 'rlg_shortcode_index');

function rlg_shortcode_discovery_tools($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tabs-container">
        <div class="rlg-tabs">
            <button class="rlg-tab active" data-tab="bates">Bates</button>
            <button class="rlg-tab" data-tab="index">Index</button>
            <button class="rlg-tab" data-tab="organize">Organize</button>
            <button class="rlg-tab" data-tab="redact">Redact</button>
            <button class="rlg-tab" data-tab="unlock">Unlock</button>
        </div>
        <div class="rlg-tab-content">
            <div class="rlg-tab-pane active" id="rlg-pane-bates">
                <?php echo rlg_shortcode_bates(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-index">
                <?php echo rlg_shortcode_index(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-organize">
                <?php echo rlg_shortcode_organize(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-redact">
                <?php echo rlg_shortcode_redact(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-unlock">
                <?php echo rlg_shortcode_unlock(array()); ?>
            </div>
        </div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_discovery_tools', 'rlg_shortcode_discovery_tools');
