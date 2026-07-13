from pathlib import Path

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "monitoring_center" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
STATE = (STATIC / "state.js").read_text(encoding="utf-8")


def _function_source(name: str, next_name: str) -> str:
    return APP.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_discovery_ui_sends_source_and_total_timeouts() -> None:
    scan = APP.split("async function runDiscoveryScan", 1)[1].split("function renderDiscoveryResults", 1)[0]
    assert "timeout_seconds:" in scan
    assert "total_timeout_seconds:" in scan
    assert "network_cidr:" in scan
    assert "max_hosts:" in scan
    assert "state.discoveryReport = { scanning: true" in scan


def test_discovery_ui_handles_structured_and_legacy_responses() -> None:
    scan = APP.split("async function runDiscoveryScan", 1)[1].split("function renderDiscoveryResults", 1)[0]
    assert "Array.isArray(response)" in scan
    assert "response.proposals || []" in scan
    assert "discoveryReport: null" in STATE
    assert "catch (error)" in scan
    assert "Skan nieudany" in APP


def test_discovery_ui_renders_every_source_status_and_message_safely() -> None:
    source_render = _function_source("renderDiscoverySourceResults(sources)", "discoverySourceLabel(source)")
    labels = _function_source("discoverySourceStatusLabel(status)", "discoverySourceTone(status)")
    assert "sources.map" in source_render
    assert "escapeHtml(source.message" in source_render
    assert "source.duration_ms" in source_render
    for status in ("success", "empty", "partial", "skipped", "error"):
        assert status in labels


def test_discovery_ui_distinguishes_no_scan_empty_success_and_failure() -> None:
    render = _function_source("renderDiscoveryResults()", "renderDiscoverySourceResults(sources)")
    assert "Uruchom skanowanie" in render
    assert "Skan wykonano poprawnie" in render
    assert "Sprawdź błędy źródeł" in render
    assert "Skanowanie…" in render
    assert "summary.className = `badge" in render


def test_discovery_dialog_exposes_accessible_source_results() -> None:
    assert 'id="discoverySourceResults"' in HTML
    assert 'id="discoveryResults" class="list empty" aria-live="polite"' in HTML
    assert 'name="total_timeout_seconds"' in HTML
    assert ".discovery-source--success" in CSS
    assert ".discovery-source--error" in CSS
    assert ".discovery-source--skipped" in CSS


def test_discovery_import_is_disabled_without_selectable_proposals() -> None:
    button_update = _function_source("updateDiscoveryImportButton()", "discoveryTypeOptions(current)")
    input_update = _function_source("updateDiscoveryProposalFromInput(event)", "importDiscoverySelection()")
    assert "importButton.disabled" in button_update
    assert "!proposal.duplicate_of_monitor_id" in button_update
    assert "updateDiscoveryImportButton()" in input_update


def test_discovery_results_can_be_searched_across_proposal_fields() -> None:
    render = _function_source("renderDiscoveryResults()", "discoveryProposalMatches(proposal, query)")
    matcher = _function_source("discoveryProposalMatches(proposal, query)", "renderDiscoverySourceResults(sources)")
    assert 'id="discoverySearch" type="search"' in HTML
    assert "filteredProposals" in render
    assert "proposal.name" in matcher
    assert "proposal.type" in matcher
    assert "proposal.target" in matcher
    assert "proposal.reason" in matcher
    assert "proposal.hostname" in matcher
    assert "proposal.mac_address" in matcher
    assert "proposal.vendor" in matcher
    assert "JSON.stringify(proposal.config" in matcher
    assert ".discovery-search" in CSS


def test_discovery_results_show_device_identity_and_icon() -> None:
    render = _function_source("renderDiscoveryResults()", "discoveryProposalMatches(proposal, query)")
    assert "discovery-device-icon" in render
    assert "discoveryIdentityText(proposal)" in render
    assert "discoveryDeviceKindLabel(proposal.device_kind)" in render
    assert ".discovery-identity" in CSS


def test_discovery_result_has_live_test_action_and_safe_http_preview() -> None:
    render = _function_source("renderDiscoveryResults()", "startDiscoveryTestRun(proposal)")
    test_run = _function_source("startDiscoveryTestRun(proposal)", "discoveryProposalMatches(proposal, query)")
    preview = _function_source("renderDiscoveryHttpPreview(test, result)", "definitionRows(rows)")
    assert "data-discovery-test" in render
    assert 'api("/api/monitors/test"' in test_run
    assert 'returnView: "discovery"' in test_run
    assert 'sandbox=""' in preview
    assert 'rel="noopener noreferrer"' in preview
    assert '["http:", "https:"]' in preview
    assert ".discovery-http-preview iframe" in CSS
