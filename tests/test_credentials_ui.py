from pathlib import Path

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "monitoring_center" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
STATE = (STATIC / "state.js").read_text(encoding="utf-8")


def _function_source(name: str, next_name: str) -> str:
    return APP.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_credentials_view_and_dialog_are_available() -> None:
    assert 'data-tab="credentials"' in HTML
    assert 'id="credentials" class="view"' in HTML
    assert 'id="credentialDialog"' in HTML
    assert 'id="credentialForm"' in HTML
    assert "credentials: []" in STATE
    assert ".credential-grid" in CSS


def test_credential_edit_never_populates_secret_fields() -> None:
    source = _function_source("openCredentialForm(credential = null)", "renderCredentialSecretFields()")
    assert "form.reset()" in source
    assert "credential?.password" not in source
    assert "credential?.private_key" not in source
    assert "credential?.private_key_passphrase" not in source
    assert "hasPassword" in source
    assert "hasPrivateKey" in source


def test_monitor_credential_options_use_backend_compatibility_metadata() -> None:
    source = _function_source("renderMonitorCredentialOptions(type)", "renderSelectedMonitorCredential()")
    assert "typeMetadata?.credential_kinds" in source
    assert "allowedKinds.includes(credential.kind)" in source
    assert "Wybrany profil nie jest kompatybilny" in source
    assert "SSH_CONFIG_TYPES" not in source


def test_selected_profile_hides_direct_fields_and_stays_out_of_config() -> None:
    selected = _function_source("renderSelectedMonitorCredential()", "buildMonitorConfig(form, type)")
    ssh = _function_source("addSshConfig(config, form)", "addDockerConfig(config, form)")
    payload = _function_source("buildMonitorPayload(form)", "updateConfigPreview()")
    assert '$$(".direct-credential-field"' in selected
    assert 'classList.toggle("hidden", hasProfile)' in selected
    assert "if (!form.elements.credential_id.value)" in ssh
    assert "credential_id:" in payload


def test_credential_secret_clear_is_explicit() -> None:
    save = APP.split("async function saveCredential", 1)[1].split("async function deleteCredential", 1)[0]
    assert "clear_secret_fields" in save
    assert "clear_password.checked" in save
    assert "clear_private_key.checked" in save
    assert "clear_private_key_passphrase.checked" in save
    assert "********" not in save


def test_export_contains_only_safe_credential_metadata() -> None:
    export = _function_source("exportConfig()", "withoutMaskedSecrets(value)")
    assert "credential_profiles" in export
    assert "secrets_exported: false" in export
    assert "credential.password" not in export
    assert "credential.private_key" not in export
    assert "withoutMaskedSecrets" in export
