"""Config Flow, Recorder-Adapter und Ergebnis-Sensoren gegen ein echtes HA im Testmodus."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.air_water_heatpump_audit.const import CHECKS, DEFAULT_OPTIONS, DOMAIN, OPTION_SECTIONS, ROLE_STEPS
from custom_components.air_water_heatpump_audit.audit_core.audits import BY_ID, REGISTRY
from custom_components.air_water_heatpump_audit.profiles import COMMON_ROLE_SUGGESTIONS, INTERFACE_PROFILES, MODEL_PROFILES
from custom_components.air_water_heatpump_audit.recorder_source import to_series

AUDIT_SUBENTRY = lambda a: {"subentry_type": "audit", "data": {"audit": a}, "title": a, "unique_id": a}
ALL_AUDITS = [AUDIT_SUBENTRY(a) for a in ("data_basis", "efficiency", "flow_temperature", "capacity")]
MAHTANAR = ({"interface_profile": "esphome_ecodan", "electricity_meter": "sensor.wp_zaehler_bezug"}
            | COMMON_ROLE_SUGGESTIONS | INTERFACE_PROFILES["esphome_ecodan"])


def test_to_series_converts_states():
    states = [State("binary_sensor.x", "on"), State("binary_sensor.x", "unavailable"), State("binary_sensor.x", "off")]
    assert [v for _, v in to_series("compressor_running", states)] == [1.0, 0.0]
    assert [v for _, v in to_series("flow_temp", [State("sensor.t", "31.5"), State("sensor.t", "x")])] == [31.5]
    assert [v for _, v in to_series("controller_date", [State("sensor.d", "2026-10-24")])] == ["2026-10-24"]
    weather = State("weather.home", "cloudy", {"temperature": 9.5})
    assert [v for _, v in to_series("outdoor_temp_reference", [weather])] == [9.5]


async def test_config_flow_prefills_and_creates_entry(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.heatpump_compressor", "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "setup"  # ohne Vorgängerin kein Menü
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"interface_profile": "esphome_ecodan", "model_profile": "mitsubishi_pud_shwm140",
                            "audits": ["efficiency", "capacity"]})
    assert result["step_id"] == "signals"
    schema = {str(k): k.description for k in result["data_schema"].schema}
    assert schema["compressor_running"] == {"suggested_value": "binary_sensor.heatpump_compressor"}
    assert schema["defrost"] is None  # existiert hier nicht → keine Vorbelegung

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"compressor_running": "binary_sensor.heatpump_compressor"})
    assert result["step_id"] == "measurements"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "controller"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "circuit"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "dhw"
    schema = {str(k): k.description for k in result["data_schema"].schema}
    assert schema["dhw_tank_temp"] is None  # Speicherfühler existiert hier nicht
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "tariff"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "controls"
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["compressor_running"] == "binary_sensor.heatpump_compressor"
    assert result["options"]["capacity_min_table"] == MODEL_PROFILES["mitsubishi_pud_shwm140"]["capacity_min_table"]
    assert result["options"]["immersion_heater_kw"] == 3.0  # aus dem Modell-Profil
    assert result["options"]["heating_hours"] is None  # kein Standort-Profil
    assert sorted(sub["data"]["audit"] for sub in result["subentries"]) == ["capacity", "efficiency"]


async def test_config_flow_without_profile_has_no_suggestions(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.heatpump_compressor", "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"interface_profile": "none", "model_profile": "none", "audits": ["data_basis"]})
    schema = {str(k): k.description for k in result["data_schema"].schema}
    assert schema["compressor_running"] is None


async def test_config_flow_suggests_default_german_entity_ids(hass: HomeAssistant):
    """Frisch eingerichtete Firmware mit deutschen Labels heißt „ecodan_heatpump_…“ – das Profil findet sie trotzdem."""
    hass.states.async_set("binary_sensor.ecodan_heatpump_kompressor", "off")
    hass.states.async_set("sensor.ecodan_heatpump_feed_temp", "30")  # englische Labels
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"interface_profile": "esphome_ecodan", "model_profile": "none", "audits": ["data_basis"]})
    schema = {str(k): k.description for k in result["data_schema"].schema}
    assert schema["compressor_running"] == {"suggested_value": "binary_sensor.ecodan_heatpump_kompressor"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    schema = {str(k): k.description for k in result["data_schema"].schema}
    assert schema["flow_temp"] == {"suggested_value": "sensor.ecodan_heatpump_feed_temp"}
    assert schema["return_temp"] is None  # gibt es in dieser Instanz in keiner Schreibweise


async def test_import_from_legacy_wp_audit(hass: HomeAssistant, hass_storage):
    """Übernahme aus „WP-Audit“ (Domain heatpump_audit, Rollen noch mit ftc_*): Rollen, Optionen, Ereignisse, Zeitstrahl."""
    old = MockConfigEntry(domain="heatpump_audit", title="WP-Audit", version=1,
                          data={"compressor_running": "binary_sensor.heatpump_compressor",
                                "ftc_heating_consumed": "sensor.heatpump_heating_consumed",
                                "ftc_controller_date": "sensor.d"},
                          options=DEFAULT_OPTIONS | {"heating_hours": 6279},
                          subentries_data=[{"subentry_type": "event", "title": "Pumpe", "unique_id": None,
                                            "data": {"time": "2026-10-25 19:31:00", "kind": "pump_setting", "note": ""}}])
    old.add_to_hass(hass)
    hass_storage[f"heatpump_audit.timeline.{old.entry_id}"] = {"version": 1, "key": "x",
                                                               "data": {"days": [{"day": "2020-01-01"}]}}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "import_legacy"})
    assert result["step_id"] == "import_legacy"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.data["controller_heating_consumed"] == "sensor.heatpump_heating_consumed"
    assert entry.data["controller_date"] == "sensor.d" and "ftc_controller_date" not in entry.data
    assert entry.data["interface_profile"] == "esphome_ecodan"
    assert entry.options["heating_hours"] == 6279
    kinds = sorted(sub.subentry_type for sub in entry.subentries.values())
    assert kinds == ["audit"] * len(REGISTRY) + ["event"]
    days = await entry.runtime_data._merge_timeline([])
    assert days[0] == {"day": "2020-01-01"}  # Tag aus dem Speicher der Vorgängerin


async def test_add_audit_subentry_and_entities_follow(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"},
                            subentries_data=[AUDIT_SUBENTRY("capacity")])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.air_water_heatpump_audit_capacity") is not None
    assert hass.states.get("sensor.air_water_heatpump_audit_efficiency") is None
    assert list(entry.runtime_data.data["audits"]) == ["capacity"]
    assert set(entry.runtime_data._roles()) <= set(BY_ID["capacity"].roles)

    result = await hass.config_entries.subentries.async_init((entry.entry_id, "audit"),
                                                             context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"audit": "efficiency"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.air_water_heatpump_audit_efficiency") is not None
    assert hass.states.get("sensor.air_water_heatpump_audit_e3_carnot_efficiency") is not None
    timeline = hass.states.get("sensor.air_water_heatpump_audit_timeline").attributes["audits"]
    assert [a["id"] for a in timeline] == ["efficiency", "capacity"]


async def test_audit_devices_hang_below_main_device(hass: HomeAssistant, caplog):
    """Audit-Geräte verweisen per via_device_id auf das Hauptgerät (via_device ist ab HA 2027.8 entfernt)."""
    from homeassistant.helpers import device_registry as dr

    entry = MockConfigEntry(domain=DOMAIN, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"},
                            subentries_data=[AUDIT_SUBENTRY("capacity")])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    devices = {ident[1]: d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
               for ident in d.identifiers}
    main, audit = devices.get(entry.entry_id), devices.get(f"{entry.entry_id}_capacity")
    assert main is not None and audit is not None and audit.via_device_id == main.id
    assert "via_device" not in caplog.text


async def test_add_audit_warns_about_missing_roles(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={"compressor_running": "binary_sensor.c"}, options=DEFAULT_OPTIONS,
                            subentries_data=[AUDIT_SUBENTRY("capacity")])
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await hass.config_entries.subentries.async_init((entry.entry_id, "audit"),
                                                                 context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"audit": "efficiency"})
        assert result["errors"] == {"base": "missing_roles"}
        result = await hass.config_entries.subentries.async_configure(result["flow_id"],
                                                                      {"audit": "efficiency", "confirmed": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_sensors_from_recorder(hass: HomeAssistant):
    for eid, state in {"binary_sensor.heatpump_compressor": "on", "sensor.heatpump_feed_temp": "33.5",
                       "sensor.heatpump_return_temp": "29.0", "sensor.heatpump_flow_rate": "14",
                       "sensor.heatpump_esp_uptime": "100", "binary_sensor.heatpump_water_pump_status": "on"}.items():
        hass.states.async_set(eid, state)
    hass.states.async_set("sensor.heatpump_esp_uptime", "160")
    await async_wait_recording_done(hass)

    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success, coordinator.last_exception

    audit = hass.states.get("sensor.air_water_heatpump_audit_data_basis")
    assert audit is not None and audit.state in ("ok", "hint", "warn", "info", "not_assessable")
    assert audit.attributes["dq"] in ("high", "medium", "low")
    assert {c["entity_id"] for c in audit.attributes["checks"]} <= {
        f"sensor.air_water_heatpump_audit_{cid.lower()}_{key}" for _, cid, key in CHECKS}
    d1 = hass.states.get("sensor.air_water_heatpump_audit_d1_history_depth")
    assert d1.state == "hint"  # nur Recorder mit 10 Tagen
    assert d1.attributes["origin"] == "derived"
    assert d1.attributes["action"]["who"] == "owner"
    assert coordinator.data["points"]["compressor_running"] >= 1
    assert hass.states.get("sensor.air_water_heatpump_audit_capacity").attributes["cycles"][0]["open_start"] is True


INFLUX = {"api_version": "2", "url": "http://influx.test:8086", "token": "t", "organization": "o", "bucket": "b",
          "verify_ssl": True}
CSV_VALUE = (",result,table,_time,_value,domain,entity_id\r\n"
             ",_result,0,2000-01-01T00:00:00Z,1,binary_sensor,heatpump_compressor\r\n"
             ",_result,0,2000-01-01T00:00:05.123456789Z,30.5,sensor,heatpump_feed_temp\r\n"
             ",_result,0,2000-01-01T00:00:06Z,31,sensor,heatpump_feed_temp\r\n"
             "\r\n,result,table,_time,_value,domain,entity_id\r\n"  # zweite Tabelle mit wiederholtem Kopf
             ",_result,1,2000-01-01T00:01:00Z,0,binary_sensor,heatpump_compressor\r\n")


def test_parse_csv_and_trim():
    from custom_components.air_water_heatpump_audit.influx_source import parse_csv, trim_before

    roles = {"compressor_running": "binary_sensor.heatpump_compressor", "flow_temp": "sensor.heatpump_feed_temp"}
    out = parse_csv(CSV_VALUE, roles)
    assert [v for _, v in out["compressor_running"]] == [1.0, 0.0]
    assert [v for _, v in out["flow_temp"]] == [30.5, 31.0]
    t0 = out["flow_temp"][0][0]
    assert trim_before(out["flow_temp"], t0 + 2) == out["flow_temp"][-1:]  # beide vor start → nur der jüngste
    assert len(trim_before(out["flow_temp"], t0 + 0.5)) == 2


def test_build_query_filters_domain_and_entity():
    from custom_components.air_water_heatpump_audit.influx_source import build_query

    q = build_query("b", "value", ["sensor.a", "select.a"], 0, 3600)
    assert '(r.domain == "select" and r.entity_id == "a")' in q and '(r.domain == "sensor" and r.entity_id == "a")' in q
    assert 'r._field == "value"' in q and "last()" in q


async def _setup_with_influx(hass: HomeAssistant):
    MockConfigEntry(domain="influxdb", data=INFLUX).add_to_hass(hass)  # nur gelesen, nicht eingerichtet
    hass.states.async_set("sensor.heatpump_flow_rate", "14")
    await async_wait_recording_done(hass)
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success, coordinator.last_exception
    return coordinator


async def test_influx_source_used_and_missing_roles_from_recorder(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post("http://influx.test:8086/api/v2/query", text=CSV_VALUE)
    coordinator = await _setup_with_influx(hass)
    source = coordinator.data["source"]
    assert source["used"] == "influxdb" and source["note"] is None
    assert "flow_rate" in source["roles_from_recorder"] and "flow_temp" not in source["roles_from_recorder"]
    assert coordinator.data["points"]["flow_temp"] == 1  # Testdaten liegen vor dem Fenster: nur der gültige Wert
    assert coordinator.data["points"]["flow_rate"] == 1  # aus dem Recorder
    assert hass.states.get("sensor.air_water_heatpump_audit_d1_history_depth").state == "ok"  # Langzeitquelle angebunden
    assert hass.states.get("sensor.air_water_heatpump_audit_data_basis").attributes["source"]["used"] == "influxdb"
    sent = aioclient_mock.mock_calls[0]
    assert sent[3]["Authorization"] == "Token t"


async def test_influx_error_falls_back_to_recorder(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post("http://influx.test:8086/api/v2/query", status=401, text="unauthorized")
    coordinator = await _setup_with_influx(hass)
    source = coordinator.data["source"]
    assert source["used"] == "recorder" and "HTTP 401" in source["note"]
    assert hass.states.get("sensor.air_water_heatpump_audit_d1_history_depth").state == "hint"


async def test_recorder_option_ignores_influx(hass: HomeAssistant, aioclient_mock):
    MockConfigEntry(domain="influxdb", data=INFLUX).add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR,
                            options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00", "data_source": "recorder"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data["source"]["used"] == "recorder"
    assert aioclient_mock.call_count == 0


async def test_reconfigure_adds_new_roles_and_keeps_cleared(hass: HomeAssistant):
    hass.states.async_set("sensor.heatpump_z1_feed_temp", "33")
    hass.states.async_set("binary_sensor.heatpump_defrost", "off")
    hass.states.async_set("select.heatpump_short_cycle_lockout_duration_min", "0", {"options": ["0", "30"]})
    old = {r: e for r, e in MAHTANAR.items() if r not in ROLE_STEPS["circuit"] and r not in ROLE_STEPS["controls"]
           } | {"defrost": ""}
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=old, options=DEFAULT_OPTIONS, unique_id="binary_sensor.heatpump_compressor")
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "signals"
        schema = {str(k): k.description for k in result["data_schema"].schema}
        assert schema["defrost"] is None  # bewusst geleert, bleibt leer
        for _ in range(3):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "circuit"
        schema = {str(k): k.description for k in result["data_schema"].schema}
        assert schema["circuit_flow_temp"] == {"suggested_value": "sensor.heatpump_z1_feed_temp"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"circuit_flow_temp": "sensor.heatpump_z1_feed_temp"})
        assert result["step_id"] == "dhw"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "tariff"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "controls"
        schema = {str(k): k.description for k in result["data_schema"].schema}
        assert schema["short_cycle_lockout"] == {"suggested_value": "select.heatpump_short_cycle_lockout_duration_min"}
        assert schema["heating_curve_shift"] is None  # Mahtanar kann die Heizkurve nicht schreiben
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"short_cycle_lockout": "select.heatpump_short_cycle_lockout_duration_min"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert entry.data["circuit_flow_temp"] == "sensor.heatpump_z1_feed_temp"


async def test_reconfigure_leaves_reload_to_update_listener(hass: HomeAssistant, caplog):
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=dict(MAHTANAR), options=DEFAULT_OPTIONS,
                            unique_id="binary_sensor.heatpump_compressor")
    entry.add_to_hass(hass)
    updated = []

    async def listener(hass, entry):
        updated.append(entry.data.get("controller_heat_today"))

    entry.add_update_listener(listener)
    result = await entry.start_reconfigure_flow(hass)
    while result["type"] is FlowResultType.FORM:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"controller_heat_today": "sensor.heat_today"} if result["step_id"] == "controller" else {})
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert updated == ["sensor.heat_today"]
    assert "update listener" not in caplog.text


def _sections(values: dict) -> dict:
    """Optionen flach → Eingabe des Options-Formulars mit Abschnitten."""
    return {name: {k: values[k] for k in keys if values.get(k) is not None} for name, keys in OPTION_SECTIONS.items()}


async def test_options_flow_master_data(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        values = DEFAULT_OPTIONS | {"hydraulic_separation": "parallel_buffer", "flow_rate_min_lpm": 14.3,
                                    "room_temp_target": 21.5, "heating_hours": None}
        result = await hass.config_entries.options.async_configure(result["flow_id"], _sections(values))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["hydraulic_separation"] == "parallel_buffer" and entry.options["flow_rate_min_lpm"] == 14.3
    assert entry.options["heating_hours"] is None  # geleert → unbekannt, nicht der alte Wert
    assert entry.options["capacity_min_table"] == DEFAULT_OPTIONS["capacity_min_table"]
    assert "plant" not in entry.options  # flach gespeichert


async def test_options_flow_keeps_zero_values(hass: HomeAssistant):
    """0 kW ist ein Wert („keine Zusatzheizung“), nicht „unbekannt“: Er wird vorbelegt und bleibt beim Speichern."""
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR,
                            options=DEFAULT_OPTIONS | {"booster_heater_kw": 0.0})
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    plant = next(v for k, v in result["data_schema"].schema.items() if str(k) == "plant").schema
    fields = {str(k): k.description for k in plant.schema}
    assert fields["booster_heater_kw"] == {"suggested_value": 0.0}


async def test_options_flow_suggests_price_from_energy_dashboard(hass: HomeAssistant):
    """Steht der WP-Zähler im Energie-Dashboard, schlägt der Options Flow dessen Arbeitspreis vor."""
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    manager = type("M", (), {"data": {"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.other", "number_energy_price": 0.30},
        {"type": "grid", "stat_energy_from": MAHTANAR["electricity_meter"], "number_energy_price": 0.25}]}})()
    with patch("homeassistant.components.energy.data.async_get_manager", new=AsyncMock(return_value=manager)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    cost = next(v for k, v in result["data_schema"].schema.items() if str(k) == "cost").schema
    fields = {str(k): k.description for k in cost.schema}
    assert fields["tariff_price"] == {"suggested_value": 0.25}


async def test_options_flow_rejects_bad_capacity_table(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _sections(DEFAULT_OPTIONS | {"capacity_min_table": {"35": "viel"}}))
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_capacity_table"}


async def test_event_subentry_starts_new_section(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    when = (dt_util.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:00")
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "event"),
                                                             context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"time": when, "kind": "heating_curve", "note": "Parallelverschiebung −1 K"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"].endswith("· Heating curve changed")
    await hass.async_block_till_done()  # Update-Listener lädt neu
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    section = hass.states.get("sensor.air_water_heatpump_audit_capacity").attributes["section"]
    assert section["kind"] == "heating_curve" and section["note"] == "Parallelverschiebung −1 K"
    assert "section" not in hass.states.get("sensor.air_water_heatpump_audit_data_basis").attributes
    events = hass.states.get("sensor.air_water_heatpump_audit_timeline").attributes["events"]
    assert [e["kind"] for e in events] == ["heating_curve"]
    assert events[0]["subentry_id"] in entry.subentries


async def test_timeline_keeps_stored_days(hass: HomeAssistant, hass_storage):
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    old_day = {"day": "2000-01-01", "start": 0, "end": 86400, "capacity": {"value": 12, "verdict": "hint"}}
    hass_storage[f"{DOMAIN}.timeline.{entry.entry_id}"] = {"version": 1, "key": f"{DOMAIN}.timeline.{entry.entry_id}",
                                                           "data": {"days": [old_day]}}
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.air_water_heatpump_audit_timeline")
    assert state.attributes["days"][0] == old_day
    assert set(state.attributes["scales"]) == {"data_basis", "efficiency", "flow_temperature", "capacity"}
    assert state.attributes["entry_id"] == entry.entry_id


async def test_flow_temperature_sensors(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    audit = hass.states.get("sensor.air_water_heatpump_audit_flow_temperature")
    assert audit is not None and audit.state == "not_assessable"
    assert len(audit.attributes["checks"]) == 6 and "cycles" not in audit.attributes
    t6 = hass.states.get("sensor.air_water_heatpump_audit_t6_heating_curve_headroom")
    assert t6.state == "not_assessable" and "Raumfühler" in t6.attributes["text"]
    efficiency = hass.states.get("sensor.air_water_heatpump_audit_efficiency")
    assert efficiency is not None and efficiency.state == "not_assessable"
    assert [c["check_id"] for c in efficiency.attributes["checks"]] == ["E1", "E2", "E3", "E4"]
    assert hass.states.get("sensor.air_water_heatpump_audit_e3_carnot_efficiency").state == "not_assessable"


async def test_card_creates_event_via_rest(hass: HomeAssistant, hass_client):
    """Der Weg der Zeitstrahl-Karte: Subentry-Flow per REST mit dem Format eines datetime-local-Felds."""
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.post("/api/config/config_entries/subentries/flow", json={"handler": [entry.entry_id, "event"]})
    assert resp.status == 200, await resp.text()
    flow_id = (await resp.json())["flow_id"]
    resp = await client.post(f"/api/config/config_entries/subentries/flow/{flow_id}",
                             json={"time": "2026-10-25 14:30:00", "kind": "valves", "note": "Bad auf 4"})
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()
    (sub,) = [x for x in entry.subentries.values() if x.subentry_type == "event"]
    assert sub.data == {"time": "2026-10-25 14:30:00", "kind": "valves", "note": "Bad auf 4"}


async def test_controls_read_from_mapped_entities(hass: HomeAssistant):
    hass.states.async_set("select.heatpump_short_cycle_lockout_duration_min", "0", {"options": ["0", "15", "30"]})
    hass.states.async_set("number.heatpump_short_cycle_minimum_on_time", "5.0",
                          {"min": 1.0, "max": 20.0, "step": 1.0, "unit_of_measurement": "min"})
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=ALL_AUDITS, data=MAHTANAR, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controls = entry.runtime_data._controls()
    assert set(controls) == {"short_cycle_lockout", "short_cycle_min_run"}  # Heizkurve/Pumpe nicht zugeordnet
    assert controls["short_cycle_lockout"]["options"] == ["0", "15", "30"]
    assert controls["short_cycle_min_run"] == {"entity_id": "number.heatpump_short_cycle_minimum_on_time",
                                               "state": "5.0", "min": 1.0, "max": 20.0, "step": 1.0,
                                               "options": None, "unit": "min"}
    assert hass.states.get("sensor.air_water_heatpump_audit_capacity").attributes["entry_id"] == entry.entry_id


async def test_card_is_served(hass: HomeAssistant, hass_client):
    """Die Karte liegt unter CARD_URL (Dateiname und URL passen zusammen)."""
    from custom_components.air_water_heatpump_audit.const import CARD_URL

    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == 200
    assert "air-water-heatpump-audit-card" in await resp.text()


def test_translation_placeholders_match_english():
    """Geschweifte Klammern sind Platzhalter: Jede Sprache braucht genau die Platzhalter des englischen Texts,
    sonst verwirft HA den Text (Log „Validation of translation placeholders“)."""
    import json
    import string
    from pathlib import Path

    def flat(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from flat(value, f"{prefix}.{key}" if prefix else key)
        else:
            yield prefix, node

    def placeholders(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}

    base = Path(__file__).parents[1] / "custom_components" / DOMAIN
    english = dict(flat(json.loads((base / "strings.json").read_text(encoding="utf-8"))))
    for path in sorted((base / "translations").glob("*.json")):
        for key, text in flat(json.loads(path.read_text(encoding="utf-8"))):
            assert placeholders(text) == placeholders(english.get(key, "")), (path.name, key)
            assert all(name.isidentifier() for name in placeholders(text)), (path.name, key, text)


def test_translations_cover_registry():
    """Jede Prüfung und jedes Audit der Registry hat Texte in allen Sprachdateien (statt Generator, siehe Entwurf)."""
    import json
    from pathlib import Path

    from custom_components.air_water_heatpump_audit.audit_core.audits import REGISTRY

    base = Path(__file__).parents[1] / "custom_components" / DOMAIN
    for path in [base / "strings.json", *sorted((base / "translations").glob("*.json"))]:
        data = json.loads(path.read_text(encoding="utf-8"))
        sensors = data["entity"]["sensor"]
        for spec in REGISTRY:
            assert spec.audit_id in sensors and spec.audit_id in data["selector"]["audits"]["options"], (path, spec)
            for check in spec.checks:
                assert check.key in sensors, (path.name, check.key)


async def test_card_resource_registered_and_updated(hass: HomeAssistant):
    """Die Integration trägt ihre Karte selbst als Lovelace-Ressource ein und hält die Version aktuell."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    from custom_components.air_water_heatpump_audit.const import CARD_URL

    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_get_info()
    await resources.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.0.1"})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    urls = [r["url"] for r in resources.async_items() if r["url"].startswith(CARD_URL)]
    assert len(urls) == 1 and not urls[0].endswith("v=0.0.1")


async def test_person_subentry_with_rotation_reaches_core(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=MAHTANAR, options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"},
                            subentries_data=[AUDIT_SUBENTRY("dhw")])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init((entry.entry_id, "person"),
                                                             context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {
        "name": "Kind 1", "birth_year": 2015, "presence": "rotation", "shower_time": "evening"})
    assert result["step_id"] == "presence"
    assert set(result["data_schema"].schema) == {"weeks_present", "weeks_absent", "rotation_start"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {
        "weeks_present": 1, "weeks_absent": 1, "rotation_start": "2026-11-02"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = [x for x in entry.subentries.values() if x.subentry_type == "person"]
    assert sub.title == "Kind 1"
    assert sub.data == {"name": "Kind 1", "birth_year": 2015, "presence": "rotation", "shower_time": "evening",
                        "weeks_present": 1, "weeks_absent": 1, "rotation_start": "2026-11-02"}

    # Ändern auf „immer“: der zweite Schritt entfällt, die Wechselwochen verschwinden aus den Daten
    result = await entry.start_subentry_reconfigure_flow(hass, sub.subentry_id)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {
        "name": "Kind 1", "birth_year": 2015, "presence": "always", "shower_time": "evening",
        "showers_per_week": 4})
    assert result["type"] is FlowResultType.ABORT
    sub = entry.subentries[sub.subentry_id]
    assert sub.data == {"name": "Kind 1", "birth_year": 2015, "presence": "always", "shower_time": "evening",
                        "showers_per_week": 4}
    await hass.async_block_till_done()
    coordinator = hass.config_entries.async_get_entry(entry.entry_id).runtime_data
    with patch("custom_components.air_water_heatpump_audit.coordinator.run_audits", return_value={}) as run:
        coordinator._compute({}, 0, 1, 10, None, {})
    assert run.call_args.kwargs["master"]["household"] == [sub.data]
    assert run.call_args.kwargs["master"]["dhw_disinfection_interval_days"] == 7
