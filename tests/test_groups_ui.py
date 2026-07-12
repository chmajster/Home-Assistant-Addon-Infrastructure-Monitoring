import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "monitoring_center" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")


def _function_source(name: str, next_name: str) -> str:
    return APP.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def _run_group_helpers() -> dict[str, object]:
    module_uri = (STATIC / "components" / "groups.js").resolve().as_uri()
    script = f"""
      import {{ groupStatusLabel, incidentCountLabel, sloUptimeLabel }} from {json.dumps(module_uri)};
      console.log(JSON.stringify({{
        statuses: ["EMPTY", "OK", "ONLINE", "WARNING", "ERROR", "OFFLINE", "MAINTENANCE"]
          .map(groupStatusLabel),
        incidents: [0, 1, 2, 4, 5, 12, 22].map(incidentCountLabel),
        noData: [sloUptimeLabel(null), sloUptimeLabel(undefined), sloUptimeLabel("")],
        uptime: sloUptimeLabel(99.95),
      }}));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_group_helpers_translate_statuses_and_format_slo() -> None:
    result = _run_group_helpers()
    assert result["statuses"] == [
        "Pusta",
        "Aktywna",
        "Aktywna",
        "Ostrzeżenie",
        "Problem",
        "Problem",
        "Serwis",
    ]
    assert result["noData"] == ["—", "—", "—"]
    assert result["uptime"] == "99.95%"


def test_incident_count_polish_inflection() -> None:
    result = _run_group_helpers()
    assert result["incidents"] == [
        "0 incydentów",
        "1 incydent",
        "2 incydenty",
        "4 incydenty",
        "5 incydentów",
        "12 incydentów",
        "22 incydenty",
    ]


def test_group_cards_cover_empty_online_offline_and_selection() -> None:
    render = _function_source("renderGroups()", "renderGroupSummary()")
    assert "Brak grup" in render
    assert "group-card--selected" in render
    assert "group.status" in render
    assert "group.online" in render
    assert "group.offline" in render
    assert "groupStatusLabel" in render
    assert "sloUptimeLabel" in APP


def test_group_filter_action_is_handled_in_the_right_function() -> None:
    handler = APP.split("async function handleGroupAction", 1)[1].split("async function saveGroup", 1)[0]
    monitor_maintenance = APP.split("async function saveMaintenanceFromDialog", 1)[1].split(
        "function renderGroupMonitorList", 1
    )[0]
    assert 'action === "filter"' in handler
    assert "selectGroup(id)" in handler
    assert 'action === "filter"' not in monitor_maintenance
    assert "setMonitorMaintenanceUntil" in monitor_maintenance


def test_group_selection_does_not_implicitly_change_view() -> None:
    selection = _function_source("selectGroup(id, { scroll = true } = {})", "resetGroupForm()")
    handler = APP.split("async function handleGroupAction", 1)[1].split("async function saveGroup", 1)[0]
    assert "state.selectedGroupId" in selection
    assert "group-card--selected" in selection
    assert "renderGroupMonitorList(id)" in selection
    assert "showView(" not in handler


def test_group_form_supports_edit_and_cancel_modes() -> None:
    assert 'id="groupFormTitle">Nowa grupa' in HTML
    assert 'id="saveGroupBtn"' in HTML
    assert 'id="cancelGroupEditBtn"' in HTML
    reset = _function_source("resetGroupForm()", "syncGroupColorFromPicker(event)")
    assert 'elements.id.value = ""' in reset
    assert 'textContent = "Dodaj grupę"' in reset
    assert "hidden = true" in reset
    assert 'textContent = "Zapisz zmiany"' in APP


def test_maintenance_menu_and_delete_confirmation_are_accessible() -> None:
    assert '<details class="group-action-menu">' in APP
    assert 'aria-expanded="false"' in APP
    assert 'event.key !== "Escape"' in APP
    assert 'data-group-action="maint-30"' in APP
    assert 'data-group-action="maint-120"' in APP
    assert 'data-group-action="maint-manual"' in APP
    assert 'data-group-action="maint-clear"' in APP
    assert "confirmGroupDelete(group)" in APP
    assert 'class="danger-action" data-group-action="delete"' in APP


def test_group_layout_has_required_responsive_contract() -> None:
    assert "repeat(auto-fit, minmax(min(100%, 320px), 1fr))" in CSS
    assert "@media (max-width: 699px)" in CSS
    assert "@media (min-width: 700px) and (max-width: 1199px)" in CSS
    assert "grid-template-columns: 1fr;" in CSS
    assert "overflow-wrap: anywhere" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    for class_name in (
        "group-card__header",
        "group-card__stats",
        "group-card__slo",
        "group-card__actions",
        "group-maintenance",
        "group-card--selected",
    ):
        assert f".{class_name}" in CSS
