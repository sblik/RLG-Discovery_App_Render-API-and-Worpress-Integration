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
                            <input type="number" name="digits" id="bates-digits" value="6" min="6" max="10">
                        </div>
                        <div class="rlg-form-group">
                            <label>Font Size (pt)</label>
                            <input type="number" name="font_size" id="bates-fontsize" value="12" min="6" max="36">
                        </div>
                        <div class="rlg-form-group">
                            <label>Bold</label>
                            <input type="checkbox" name="font_bold" id="bates-fontbold" >
                        </div>
                        <div class="rlg-form-group">
                            <label>Label Color</label>
                            <div class="rlg-color-presets" id="bates-color-presets">
                                <button type="button" class="rlg-color-swatch active" data-color="#0000FF" style="background-color:#0000FF" title="Blue"></button>
                                <button type="button" class="rlg-color-swatch" data-color="#FF0000" style="background-color:#FF0000" title="Red"></button>
                                <button type="button" class="rlg-color-swatch" data-color="#000000" style="background-color:#000000" title="Black"></button>
                            </div>
                            <input type="hidden" name="color_hex" id="bates-color" value="#0000FF">
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
                            <input type="number" name="left_punch_margin" value="36" min="0" max="72" disabled>
                        </div>
                        <div class="rlg-form-group rlg-checkbox-toggle">
                            <label>
                                <input type="checkbox" id="toggle-border" data-target="border-field">
                                Add all-sides safety border
                            </label>
                        </div>
                        <div class="rlg-form-group rlg-toggle-field" id="border-field" style="display: none;">
                            <label>Border (pt)</label>
                            <input type="number" name="border_all_pt" value="12" min="0" max="36" disabled>
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
                <div id="bates-final-number" class="rlg-final-number" style="display: none;"></div>
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
                <label>Upload PDF(s) or ZIP</label>
                <input type="file" name="files" multiple required accept=".pdf,.zip">
            </div>
            <section class="rlg-divider">
                <h4>Presets</h4>
                <div class="rlg-form-group">
                    <div class="rlg-checkbox-group">
                        <label><input type="checkbox" name="presets" value="SSN" checked>
                            Social Security Number (SSN)</label>
                        <label><input type="checkbox" name="presets" value="EIN">
                            Employer ID Number (EIN)</label>
                        <label><input type="checkbox" name="presets" value="Credit Card">
                            Credit Card Number</label>
                        <label><input type="checkbox" name="presets" value="Date of Birth">
                            Date of Birth (labeled)</label>
                        <label><input type="checkbox" name="presets" value="Phone">
                            Phone Number</label>
                        <label><input type="checkbox" name="presets" value="Email">
                            Email Address</label>
                        <label><input type="checkbox" name="presets" value="Date">
                            Date (MM/DD/YYYY and variants)</label>
                        <label><input type="checkbox" name="presets" value="8-digit number">
                            8-Digit Account / ID Number</label>
                    </div>
                </div>
            </section>
            <section class="rlg-section-flex rlg-divider">
                <h4>Custom Patterns</h4>
                <div class="rlg-form-group">
                    <label>Literal Patterns (comma separated)</label>
                    <input type="text" name="literal_patterns" placeholder="e.g., 000001, 000AB2">
                </div>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label>
                        <input type="checkbox" id="toggle-advanced-regex" data-target="advanced-regex-field">
                        Advanced: Use Regex
                    </label>
                </div>
                <div class="rlg-form-group rlg-toggle-field" id="advanced-regex-field" style="display: none;">
                    <label>Regex Patterns (one per line)</label>
                    <textarea name="regex_patterns" rows="3" placeholder="e.g., \b\d{4}-\d{4}\b"></textarea>
                </div>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label>
                        <input type="checkbox" name="case_sensitive">
                        Case Sensitive
                    </label>
                </div>
            </section>
            <section class="rlg-section-flex rlg-divider">
                <h4>Redaction Options</h4>
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
                                    <th class="rlg-sortable" id="index-sort-bates">Bates Range <span class="rlg-sort-icon">▲</span></th>
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

function rlg_shortcode_ocr($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tool" id="rlg-ocr-tool">
        <h3>Make Searchable (OCR)</h3>
        <p>Convert scanned PDFs or images into searchable documents. Run this before redaction for best results.</p>
        <form class="rlg-discovery-form rlg-sectioned-form" data-endpoint="/ocr" data-response-type="blob">
            <div class="rlg-form-group rlg-divider">
                <label>Upload PDFs, images, or ZIP</label>
                <input type="file" name="files" multiple required accept=".pdf,.zip,.jpg,.jpeg,.png,.tif,.tiff">
            </div>
            <button type="submit" class="rlg-btn rlg-single-column-btn">Make Searchable</button>
            <div class="rlg-status"></div>
        </form>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_ocr', 'rlg_shortcode_ocr');

function rlg_shortcode_discovery_tools($atts) {
    ob_start();
    ?>
    <div class="rlg-discovery-tabs-container rlg-splash-active">

        <!--    Scout Loading Image    -->
        <div class="rlg-splash-overlay" id="rlg-splash">
            <img src="<?php echo RLG_DISCOVERY_URL; ?>public/images/SCOUT.png" alt="Scout">
        </div>

        <div class="rlg-tabs">
            <button class="rlg-tab active" data-tab="unlock">Unlock</button>
            <button class="rlg-tab" data-tab="organize">Organize</button>
            <button class="rlg-tab" data-tab="ocr">OCR</button>
            <button class="rlg-tab" data-tab="redact">Redact</button>
            <button class="rlg-tab" data-tab="bates">Bates</button>
            <button class="rlg-tab" data-tab="index">Index</button>
        </div>
        <div class="rlg-tab-content">
            <div class="rlg-tab-pane active" id="rlg-pane-unlock">
                <?php echo rlg_shortcode_unlock(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-organize">
                <?php echo rlg_shortcode_organize(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-ocr">
                <?php echo rlg_shortcode_ocr(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-redact">
                <?php echo rlg_shortcode_redact(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-bates">
                <?php echo rlg_shortcode_bates(array()); ?>
            </div>
            <div class="rlg-tab-pane" id="rlg-pane-index">
                <?php echo rlg_shortcode_index(array()); ?>
            </div>
        </div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_discovery_tools', 'rlg_shortcode_discovery_tools');

/**
 * [rlg_pipeline] — Full pipeline shortcode with built-in review step.
 *
 * Renders a self-contained guided workflow:
 *   Upload → Scan → Unlock → OCR → Bates → Redact → Review → Index → Download
 *
 * Progress is shown in a visual step indicator (circles + connecting line)
 * driven by real-time Server-Sent Events from the API.
 *
 * After the Redact stage completes, the UI pauses and shows a review panel
 * listing each document and its redaction hit count. The attorney can:
 *   - Add more patterns and click "Re-run Redaction" to catch anything missed.
 *   - Click "Approve & Finalize" to run the Index stage and download results.
 *
 * Usage: place [rlg_pipeline] on any WordPress page/post.
 */
function rlg_shortcode_pipeline($atts) {
    ob_start();
    ?>
    <div class="rlg-pipeline-tool" id="rlg-pipeline-tool">

        <div class="rlg-pl-header">
            <h3>All-in-One Processing</h3>
            <p>Run the full document workflow in one guided session — Unlock, OCR,
               Bates stamp, Redact, review, and generate the discovery index automatically.</p>
        </div>

        <!-- ===============================================================
             Step Indicator — populated at runtime by rlg-pipeline.js
             =============================================================== -->
        <div id="rlg-pipeline-stepper" class="rlg-pl-stepper"></div>

        <!-- Post-scan file manifest (shown after /pipeline/scan returns) -->
        <div id="rlg-pipeline-scan-info" class="rlg-pl-scan-info" style="display:none"></div>

        <!-- Password panel — shown when scan detects locked files and Unlock is enabled.
             Content is generated dynamically by rlg-pipeline.js _showPasswordPanel(). -->
        <div id="rlg-pl-password-panel" class="rlg-pl-pw-panel" style="display:none"></div>

        <!-- ===============================================================
             Settings Form  (hidden during a run)
             =============================================================== -->
        <form id="rlg-pipeline-form" class="rlg-discovery-form rlg-sectioned-form">

            <!-- FILE UPLOAD ------------------------------------------------ -->
            <div class="rlg-form-group rlg-divider">
                <label>Upload PDFs, images, or ZIP</label>
                <input type="file" name="files" multiple required
                       accept=".pdf,.zip,.jpg,.jpeg,.png,.tif,.tiff">
            </div>

            <!-- UNLOCK ----------------------------------------------------- -->
            <section class="rlg-section-flex rlg-divider">
                <h4>1 · Unlock</h4>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label class="rlg-pl-toggle-label">
                        <input type="checkbox" name="enable_unlock" id="pl-enable-unlock"
                               value="true">
                        <span class="rlg-pl-toggle-switch"></span>
                        Enable Unlock
                    </label>
                    <p class="rlg-pl-hint">Enable if any files are password protected.</p>
                </div>
                <div class="rlg-pl-toggle-target" id="pl-unlock-fields" style="display:none">
                    <div class="rlg-form-group">
                        <label>Password Mode</label>
                        <select name="password_mode">
                            <option value="none">None</option>
                            <option value="all">Same password for every file</option>
                        </select>
                    </div>
                    <div class="rlg-form-group">
                        <label>Password</label>
                        <input type="password" name="password_for_all">
                    </div>
                </div>
            </section>

            <!-- OCR -------------------------------------------------------- -->
            <section class="rlg-section-flex rlg-divider">
                <h4>2 · OCR</h4>
                <div class="rlg-form-group">
                    <label class="rlg-pl-toggle-label">
                        <input type="checkbox" name="enable_ocr" id="pl-enable-ocr"
                               value="true" checked>
                        <span class="rlg-pl-toggle-switch"></span>
                        Enable OCR
                    </label>
                    <p class="rlg-pl-hint">Makes PDFs and images text-searchable. Files already
                       scanned by Apple/Preview are detected and skipped automatically.</p>
                </div>
            </section>

            <!-- BATES ------------------------------------------------------ -->
            <section class="rlg-section-flex rlg-divider">
                <h4>3 · Bates Stamp</h4>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label class="rlg-pl-toggle-label">
                        <input type="checkbox" name="enable_bates" id="pl-enable-bates"
                               value="true" checked>
                        <span class="rlg-pl-toggle-switch"></span>
                        Enable Bates Stamping
                    </label>
                </div>
                <div class="rlg-pl-toggle-target" id="pl-bates-fields">
                    <div class="rlg-section-flex">
                        <div class="rlg-form-group">
                            <label>Prefix</label>
                            <input type="text" name="prefix" placeholder="e.g. RLG">
                        </div>
                        <div class="rlg-form-group">
                            <label>Start Number</label>
                            <input type="number" name="start_num" value="1" min="1">
                        </div>
                        <div class="rlg-form-group">
                            <label>Digits</label>
                            <input type="number" name="digits" value="6" min="6" max="10">
                        </div>
                        <div class="rlg-form-group">
                            <label>Zone</label>
                            <select name="zone">
                                <option value="Z3">Bottom Right</option>
                                <option value="Z2">Bottom Center</option>
                                <option value="Z1">Bottom Left</option>
                            </select>
                        </div>
                        <div class="rlg-form-group">
                            <label>Font Size (pt)</label>
                            <input type="number" name="font_size" value="8" min="6" max="36">
                        </div>
                        <div class="rlg-form-group">
                            <label>Label Color</label>
                            <div class="rlg-color-presets" id="pl-color-presets">
                                <button type="button" class="rlg-color-swatch active"
                                        data-color="#000000"
                                        style="background-color:#000000" title="Black"></button>
                                <button type="button" class="rlg-color-swatch"
                                        data-color="#0000FF"
                                        style="background-color:#0000FF" title="Blue"></button>
                                <button type="button" class="rlg-color-swatch"
                                        data-color="#FF0000"
                                        style="background-color:#FF0000" title="Red"></button>
                            </div>
                            <input type="hidden" name="color_hex" id="pl-color"
                                   value="#000000">
                        </div>
                    </div>
                </div>
            </section>

            <!-- REDACT ----------------------------------------------------- -->
            <section class="rlg-section-flex rlg-divider">
                <h4>4 · Redact</h4>
                <div class="rlg-form-group rlg-checkbox-toggle">
                    <label class="rlg-pl-toggle-label">
                        <input type="checkbox" name="enable_redact" id="pl-enable-redact"
                               value="true">
                        <span class="rlg-pl-toggle-switch"></span>
                        Enable Redaction
                    </label>
                    <p class="rlg-pl-hint">You will be able to add more patterns in the
                       Review step if anything is missed.</p>
                </div>
                <div class="rlg-pl-toggle-target" id="pl-redact-fields" style="display:none">
                    <div class="rlg-form-group">
                        <label>Presets</label>
                        <div class="rlg-checkbox-group">
                            <label><input type="checkbox" name="presets" value="SSN">
                                Social Security Number (SSN)</label>
                            <label><input type="checkbox" name="presets" value="EIN">
                                Employer ID Number (EIN)</label>
                            <label><input type="checkbox" name="presets" value="Credit Card">
                                Credit Card Number</label>
                            <label><input type="checkbox" name="presets" value="Date of Birth">
                                Date of Birth (labeled)</label>
                            <label><input type="checkbox" name="presets" value="Phone">
                                Phone Number</label>
                            <label><input type="checkbox" name="presets" value="Email">
                                Email Address</label>
                            <label><input type="checkbox" name="presets" value="Date">
                                Date (MM/DD/YYYY and variants)</label>
                            <label><input type="checkbox" name="presets" value="8-digit number">
                                8-Digit Account / ID Number</label>
                        </div>
                    </div>
                    <div class="rlg-form-group">
                        <label>Custom Regex (one per line)</label>
                        <textarea name="regex_patterns" rows="3"
                                  placeholder="e.g. \bACCT-\d{8}\b"></textarea>
                    </div>
                    <div class="rlg-form-group">
                        <label>Literal Phrases (comma separated)</label>
                        <input type="text" name="literal_patterns"
                               placeholder="e.g. John Smith, 123 Main St">
                    </div>
                </div>
            </section>

            <!-- INDEX ------------------------------------------------------ -->
            <section class="rlg-section-flex rlg-divider">
                <h4>5 · Discovery Index</h4>
                <div class="rlg-form-group">
                    <label>Party Name</label>
                    <input type="text" name="party" value="Client">
                </div>
                <div class="rlg-form-group">
                    <label>Report Title</label>
                    <input type="text" name="title_text"
                           value="CLIENT NAME - DOCUMENTS">
                </div>
            </section>

            <button type="submit" class="rlg-btn rlg-single-column-btn"
                    id="rlg-pipeline-submit">
                ▶ Run All-in-One Processing
            </button>

        </form><!-- end #rlg-pipeline-form -->

        <!-- ===============================================================
             REVIEW PANEL — shown after /pipeline/run emits review_ready
             Hidden until Phase 1 completes.
             =============================================================== -->
        <div id="rlg-pipeline-review" class="rlg-pl-review" style="display:none">

            <div class="rlg-pl-review-header">
                <h4>🔍 Review Before Finalizing</h4>
                <p>Inspect the documents below. If anything was missed, add
                   additional patterns and click <strong>Re-run Redaction</strong>.
                   When satisfied, click <strong>Approve &amp; Finalize</strong>.</p>
            </div>

            <!-- File table — populated by rlg-pipeline.js from hits_by_file -->
            <div id="rlg-pl-review-table-wrap"></div>

            <!-- Optional: add more redaction patterns before approving -->
            <details class="rlg-pl-review-extra" id="rlg-pl-extra-redact">
                <summary>Add more redaction patterns (optional)</summary>
                <div class="rlg-pl-review-extra-body">
                    <div class="rlg-form-group">
                        <label>Presets</label>
                        <div class="rlg-checkbox-group">
                            <label><input type="checkbox" name="re_presets" value="SSN">
                                SSN</label>
                            <label><input type="checkbox" name="re_presets" value="EIN">
                                EIN</label>
                            <label><input type="checkbox" name="re_presets" value="Credit Card">
                                Credit Card</label>
                            <label><input type="checkbox" name="re_presets" value="Date of Birth">
                                Date of Birth</label>
                            <label><input type="checkbox" name="re_presets" value="Phone">
                                Phone</label>
                            <label><input type="checkbox" name="re_presets" value="Email">
                                Email</label>
                            <label><input type="checkbox" name="re_presets" value="Date">
                                Date</label>
                            <label><input type="checkbox" name="re_presets" value="8-digit number">
                                8-Digit Number</label>
                        </div>
                    </div>
                    <div class="rlg-form-group">
                        <label>Custom Regex (one per line)</label>
                        <textarea id="re-regex" rows="3"
                                  placeholder="e.g. \bACCT-\d{8}\b"></textarea>
                    </div>
                    <div class="rlg-form-group">
                        <label>Literal Phrases (comma separated)</label>
                        <input type="text" id="re-literals"
                               placeholder="e.g. Jane Doe, 555-1234">
                    </div>
                    <button type="button" class="rlg-btn rlg-pl-rerun-btn"
                            id="rlg-pl-rerun-btn">
                        🔄 Re-run Redaction
                    </button>
                </div>
            </details>

            <div class="rlg-pl-review-actions">
                <button type="button" class="rlg-btn rlg-pl-approve-btn"
                        id="rlg-pl-approve-btn">
                    ✅ Approve &amp; Finalize
                </button>
            </div>

        </div><!-- end #rlg-pipeline-review -->

        <!-- Activity log — live messages during both phases -->
        <div id="rlg-pipeline-log" class="rlg-pl-log" aria-live="polite"></div>

        <!-- Persistent download button — appears after a successful finalize -->
        <a id="rlg-pipeline-download" class="rlg-btn rlg-pl-download-btn"
           style="display:none">
            ⬇ Download Results
        </a>

    </div><!-- end .rlg-pipeline-tool -->

    <!-- ===================================================================
         Scoped styles for the pipeline UI.
         Placed inline here so the shortcode is fully self-contained.
         =================================================================== -->
    <style>
    /* ---- Outer shell ---- */
    .rlg-pipeline-tool { max-width: 860px; margin: 0 auto; font-family: inherit; }
    .rlg-pl-header h3  { margin: 0 0 4px; }
    .rlg-pl-header p   { color: #555; margin: 0 0 20px; }
    .rlg-pl-hint       { color: #6b7280; font-size: 12px; margin: 0 0 8px; font-style: italic; }

    /* ---- Stepper track ---- */
    .rlg-pl-stepper  { margin: 0 0 20px; }
    .rlg-pl-track    { display: flex; align-items: flex-start;
                        justify-content: center; flex-wrap: nowrap; }
    .rlg-pl-step     { display: flex; flex-direction: column; align-items: center;
                        width: 72px; flex-shrink: 0; }
    .rlg-pl-connector { flex: 1; height: 2px; background: #ddd; margin-top: 19px;
                         min-width: 8px; max-width: 40px; transition: background 0.3s; }

    /* ---- Circle ---- */
    .rlg-pl-circle {
        width: 38px; height: 38px; border-radius: 50%;
        border: 2px solid #d1d5db; background: #fff;
        display: flex; align-items: center; justify-content: center;
        font-size: 17px; transition: border-color 0.25s, background 0.25s;
    }
    .rlg-pl-step.active   .rlg-pl-circle { border-color: #2563eb; }
    .rlg-pl-step.complete .rlg-pl-circle { border-color: #16a34a; background: #16a34a; }
    .rlg-pl-step.error    .rlg-pl-circle { border-color: #ea580c; }
    .rlg-pl-step.skip     .rlg-pl-circle { border-color: #d1d5db; opacity: 0.5; }
    .rlg-pl-step.review   .rlg-pl-circle { border-color: #d97706; background: #fef3c7; }

    /* Connector tints */
    .rlg-pl-step.complete + .rlg-pl-connector { background: #16a34a; }
    .rlg-pl-step.error    + .rlg-pl-connector { background: #fca5a5; }
    .rlg-pl-step.review   + .rlg-pl-connector { background: #fcd34d; }

    /* ---- Spinner ---- */
    .rlg-pl-spinner {
        width: 18px; height: 18px; border-radius: 50%;
        border: 2px solid #dbeafe; border-top-color: #2563eb;
        animation: rlg-spin 0.7s linear infinite;
    }
    @keyframes rlg-spin { to { transform: rotate(360deg); } }

    /* ---- Icon states ---- */
    .rlg-pl-check { color: #fff; font-size: 15px; font-weight: 700; }
    .rlg-pl-warn  { color: #ea580c; font-size: 16px; }
    .rlg-pl-eye   { font-size: 16px; }  /* Review step waiting icon */

    /* ---- Step label + detail ---- */
    .rlg-pl-label  { margin-top: 5px; font-size: 11px; font-weight: 600;
                      text-align: center; color: #374151; }
    .rlg-pl-detail { font-size: 10px; color: #6b7280; text-align: center;
                      max-width: 70px; word-break: break-word; min-height: 13px; }
    .rlg-pl-step.active   .rlg-pl-label { color: #2563eb; }
    .rlg-pl-step.complete .rlg-pl-label { color: #16a34a; }
    .rlg-pl-step.error    .rlg-pl-label { color: #ea580c; }
    .rlg-pl-step.skip     .rlg-pl-label,
    .rlg-pl-step.skip     .rlg-pl-detail { color: #9ca3af; }
    .rlg-pl-step.review   .rlg-pl-label { color: #b45309; }

    /* ---- Activity log ---- */
    .rlg-pl-log {
        margin-top: 16px; padding: 10px 14px; max-height: 180px;
        overflow-y: auto; background: #f8fafc; border: 1px solid #e2e8f0;
        border-radius: 6px; font-size: 12px; font-family: monospace;
    }
    .rlg-pl-log-line  { padding: 1px 0; }
    .rlg-pl-log-ok    { color: #16a34a; }
    .rlg-pl-log-warn  { color: #92400e; }
    .rlg-pl-log-error { color: #b91c1c; }
    .rlg-pl-log-skip  { color: #9ca3af; }

    /* ---- Password panel ---- */
    .rlg-pl-pw-panel {
        margin: 16px 0; padding: 16px 20px;
        border: 2px solid #fcd34d; border-radius: 8px; background: #fffbeb;
    }
    .rlg-pl-pw-panel h4  { margin: 0 0 6px; color: #92400e; }
    .rlg-pl-pw-panel > p { margin: 0 0 14px; font-size: 13px; color: #78350f; }

    .rlg-pl-pw-file {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 10px; flex-wrap: wrap;
    }
    .rlg-pl-pw-file label {
        flex: 1 1 200px; font-size: 13px; font-weight: 600;
        word-break: break-all; color: #374151;
    }
    .rlg-pl-pw-input {
        flex: 1 1 180px; padding: 5px 8px; border: 1px solid #d1d5db;
        border-radius: 4px; font-size: 13px;
    }
    .rlg-pl-pw-input.pw-error { border-color: #ef4444; background: #fef2f2; }
    .rlg-pl-pw-err-msg  { font-size: 12px; color: #b91c1c; flex-basis: 100%; }

    .rlg-pl-pw-actions  { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .rlg-pl-pw-continue { background: #16a34a; color: #fff; }
    .rlg-pl-pw-continue:hover { background: #15803d; }
    .rlg-pl-pw-skip     { background: #6b7280; color: #fff; font-size: 13px; }
    .rlg-pl-pw-skip:hover { background: #4b5563; }

    /* ---- Review panel ---- */
    .rlg-pl-review {
        margin: 20px 0; padding: 16px 20px;
        border: 2px solid #fcd34d; border-radius: 8px; background: #fffbeb;
    }
    .rlg-pl-review-header h4 { margin: 0 0 6px; color: #92400e; }
    .rlg-pl-review-header p  { margin: 0 0 14px; font-size: 13px; color: #78350f; }

    /* Review file table */
    .rlg-pl-review-table { width: 100%; border-collapse: collapse;
                            font-size: 13px; margin-bottom: 14px; }
    .rlg-pl-review-table th,
    .rlg-pl-review-table td { border: 1px solid #fde68a; padding: 5px 10px; }
    .rlg-pl-review-table th { background: #fef3c7; font-weight: 600; text-align: left; }
    .rlg-pl-review-table .hits-zero  { color: #16a34a; }
    .rlg-pl-review-table .hits-some  { color: #b45309; font-weight: 600; }
    .rlg-pl-rt-name { max-width: 300px; word-break: break-all; }

    /* Extra patterns accordion */
    .rlg-pl-review-extra { margin-bottom: 14px; }
    .rlg-pl-review-extra summary {
        cursor: pointer; font-size: 13px; font-weight: 600;
        color: #2563eb; padding: 4px 0;
    }
    .rlg-pl-review-extra-body { padding: 10px 0 0; }

    /* Review action buttons */
    .rlg-pl-review-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .rlg-pl-rerun-btn   { background: #2563eb; color: #fff; }
    .rlg-pl-rerun-btn:hover { background: #1d4ed8; }
    .rlg-pl-approve-btn { background: #16a34a; color: #fff; font-size: 15px; padding: 10px 28px; }
    .rlg-pl-approve-btn:hover { background: #15803d; }

    /* ---- Download button ---- */
    .rlg-pl-download-btn {
        display: inline-block; margin-top: 16px; padding: 10px 24px;
        background: #16a34a; color: #fff; border-radius: 6px;
        text-decoration: none; font-weight: 600; font-size: 15px; cursor: pointer;
    }
    .rlg-pl-download-btn:hover { background: #15803d; color: #fff; }

    /* ---- Scan manifest ---- */
    .rlg-pl-scan-info   { margin: 10px 0; font-size: 13px; }
    .rlg-pl-details-link { font-size: 12px; color: #2563eb; text-decoration: none; }
    .rlg-pl-details-link:hover { text-decoration: underline; }
    .rlg-pl-manifest-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
    .rlg-pl-manifest-table th,
    .rlg-pl-manifest-table td { border: 1px solid #e2e8f0; padding: 4px 8px; }
    .rlg-pl-manifest-table th { background: #f1f5f9; font-weight: 600; }
    .rlg-pl-mf-name { max-width: 260px; word-break: break-all; }

    /* ---- Toggle logic ---- */
    .rlg-pl-toggle-target { overflow: hidden; }

    /* ---- CSS Toggle Switch ---- */
    .rlg-pl-toggle-label {
        display: inline-flex; align-items: center; gap: 10px;
        cursor: pointer; font-size: 14px; font-weight: 600; user-select: none;
        margin-bottom: 4px;
    }
    /* Hide the native checkbox visually but keep it accessible */
    .rlg-pl-toggle-label input[type="checkbox"] {
        position: absolute; opacity: 0; width: 0; height: 0;
    }
    /* The pill track */
    .rlg-pl-toggle-switch {
        position: relative; display: inline-block;
        width: 44px; height: 24px; flex-shrink: 0;
    }
    .rlg-pl-toggle-switch::before {
        content: ''; position: absolute; inset: 0;
        background: #d1d5db; border-radius: 9999px; transition: background 0.2s;
    }
    /* The knob */
    .rlg-pl-toggle-switch::after {
        content: ''; position: absolute;
        top: 3px; left: 3px; width: 18px; height: 18px;
        background: #fff; border-radius: 50%;
        box-shadow: 0 1px 3px rgba(0,0,0,.25);
        transition: transform 0.2s;
    }
    /* Checked state — blue track + knob slides right */
    .rlg-pl-toggle-label input[type="checkbox"]:checked ~ .rlg-pl-toggle-switch::before {
        background: #2563eb;
    }
    .rlg-pl-toggle-label input[type="checkbox"]:checked ~ .rlg-pl-toggle-switch::after {
        transform: translateX(20px);
    }
    /* Focus ring for keyboard accessibility */
    .rlg-pl-toggle-label input[type="checkbox"]:focus-visible ~ .rlg-pl-toggle-switch::before {
        outline: 2px solid #2563eb; outline-offset: 2px;
    }

    /* ---- Color swatch active state for pipeline ---- */
    #pl-color-presets .rlg-color-swatch.active { outline: 2px solid #2563eb; outline-offset: 2px; }
    </style>
    <?php
    return ob_get_clean();
}
add_shortcode('rlg_pipeline', 'rlg_shortcode_pipeline');
