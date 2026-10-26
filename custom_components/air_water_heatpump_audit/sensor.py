"""Ergebnis-Sensoren: je zugeschaltetem Audit einer (Gesamturteil) und je Prüfung einer (Urteil, Wert, Text, Herkunft),
gebündelt in einem Gerät je Audit-Untereintrag. Der Zeitstrahl gehört zum Haupteintrag.

Zustand ist immer das Urteil (Enum). Große Attribute (Details, Zyklen) landen nicht im Recorder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .audit_core.help import CHECK_HELP
from .audit_core.audits import BY_ID
from .audit_core.registry import WINDOW
from .const import CONF_AUDIT, DOMAIN, SUBENTRY_AUDIT, VERDICTS, audit_title, language
from .coordinator import AirWaterAuditConfigEntry, AirWaterAuditCoordinator

MAX_CYCLES_IN_ATTRIBUTES = 200


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _main_device_info(entry: AirWaterAuditConfigEntry) -> DeviceInfo:
    """Hauptgerät des Eintrags (Zeitstrahl); die Audit-Geräte hängen darunter."""
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Luft-Wasser-Wärmepumpen-Audit",
                      manufacturer="air-water-heatpump-audit", model="Zeitstrahl", entry_type=DeviceEntryType.SERVICE)


def check_entity_id(check_id: str, key: str) -> str:
    return f"sensor.air_water_heatpump_audit_{check_id.lower()}_{key}"


async def async_setup_entry(hass: HomeAssistant, entry: AirWaterAuditConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    # Hauptgerät vorab anlegen: Die Audit-Geräte verweisen per via_device_id auf seine Registry-ID.
    main = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **_main_device_info(entry))
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_AUDIT or sub.data.get(CONF_AUDIT) not in BY_ID:
            continue
        spec = BY_ID[sub.data[CONF_AUDIT]]
        device = DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_{spec.audit_id}")},
                            name=audit_title(spec.audit_id, language(hass)), manufacturer="air-water-heatpump-audit",
                            model=spec.audit_id, via_device_id=main.id, entry_type=DeviceEntryType.SERVICE)
        entities: list[SensorEntity] = [AuditSensor(coordinator, spec.audit_id, device)]
        entities += [CheckSensor(coordinator, spec.audit_id, c.check_id, c.key, device) for c in spec.checks]
        async_add_entities(entities, config_subentry_id=sub.subentry_id)
    async_add_entities([TimelineSensor(coordinator)])


class _Entity(CoordinatorEntity[AirWaterAuditCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AirWaterAuditCoordinator, unique_key: str,
                 device: DeviceInfo | None = None) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_key}"
        self._attr_device_info = device or _main_device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None


class _Base(_Entity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = VERDICTS


class AuditSensor(_Base):
    _unrecorded_attributes = frozenset({"checks", "cycles", "heat", "points", "runtime_s", "source", "entry_id",
                                        "readiness", "audit", "audit_name", "color"})
    _attr_name = None  # Name = Gerät „Audit: …“

    def __init__(self, coordinator: AirWaterAuditCoordinator, audit: str, device: DeviceInfo) -> None:
        super().__init__(coordinator, audit, device)
        self._audit = audit
        self._attr_translation_key = audit
        self.entity_id = f"sensor.air_water_heatpump_audit_{audit}"

    @property
    def available(self) -> bool:
        return super().available and self._audit in self.coordinator.data["audits"]

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data["audits"][self._audit]["verdict"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        audit = data["audits"][self._audit]
        spec = BY_ID[self._audit]
        attrs: dict[str, Any] = {
            "audit": self._audit,
            "audit_name": spec.names[language(self.hass)],
            "color": spec.color,
            "dq": audit["dq"],
            "period_start": _iso(data["period"]["start"]),
            "period_end": _iso(data["period"]["end"]),
            "checks": [{"check_id": r["check_id"], "key": r["key"], "verdict": r["verdict"],
                        "entity_id": check_entity_id(r["check_id"], r["key"])} for r in audit["checks"]],
            "runtime_s": data.get("runtime_s"),
            "points": data.get("points"),
            "source": data.get("source"),
            "entry_id": self.coordinator.config_entry.entry_id,  # für Ereignisse aus der Karte (Stellgrößen)
        }
        if ready := data.get("readiness", {}).get(self._audit):
            # Datenreife (Hochrechnung): ab wann das Audit genug Daten hat; Balken oben in der Karte
            attrs["readiness"] = {"start": _iso(ready["start"]), "reached": ready["reached"],
                                  "eta": _iso(ready["eta"]) if ready["eta"] is not None else None,
                                  "checks": [c | {"eta": _iso(c["eta"]) if c["eta"] is not None else None}
                                             for c in ready["checks"]]}
        if BY_ID[self._audit].section != WINDOW and (event := data.get("section", {}).get("event")):
            # Audits 1–3 rechnen ab dem letzten Ereignis (Spezifikation 1.5)
            attrs["section"] = {"start": _iso(event["time"]), "kind": event["kind"], "title": event.get("title"),
                                "note": event.get("note")}
        if self._audit == "data_basis" and "heat" in data:
            attrs["heat"] = data["heat"]
        elif self._audit == "capacity" and "cycles" in data:
            attrs["cycles"] = [{k: c[k] for k in ("start", "end", "duration_min", "pause_before", "kind",
                                                  "open_start", "open_end", "defrost_stops")}
                               for c in data["cycles"][-MAX_CYCLES_IN_ATTRIBUTES:]]
        return attrs


class CheckSensor(_Base):
    _unrecorded_attributes = frozenset({"action", "details", "help", "text", "progress"})

    def __init__(self, coordinator: AirWaterAuditCoordinator, audit: str, check_id: str, key: str,
                 device: DeviceInfo) -> None:
        super().__init__(coordinator, f"{check_id.lower()}_{key}", device)
        self._audit, self._check_id = audit, check_id
        self._attr_translation_key = key
        self.entity_id = check_entity_id(check_id, key)

    def _result(self) -> dict | None:
        for r in self.coordinator.data["audits"].get(self._audit, {}).get("checks", []):
            if r["check_id"] == self._check_id:
                return r
        return None

    @property
    def available(self) -> bool:
        return super().available and self._result() is not None

    @property
    def native_value(self) -> str | None:
        return self._result()["verdict"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result()
        return {"check_id": r["check_id"], "audit": self._audit, "value": r["value"], "unit": r["unit"],
                "text": r["text"], "origin": r["origin"], "details": r["details"],
                "action": r.get("action"), "help": CHECK_HELP.get(r["check_id"]),
                "progress": r.get("progress")}


class TimelineSensor(_Entity):
    """Zeitstrahl für die Karte: Tageswerte je Audit, Ampel-Bänder und Ereignisse. Zustand = Zahl der Tage."""

    _attr_translation_key = "timeline"
    _unrecorded_attributes = frozenset({"days", "scales", "events", "entry_id", "audits"})

    def __init__(self, coordinator: AirWaterAuditCoordinator) -> None:
        super().__init__(coordinator, "timeline")
        self.entity_id = "sensor.air_water_heatpump_audit_timeline"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data["timeline"]["days"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        lang = language(self.hass)
        audits = [{"id": a, "name": BY_ID[a].names[lang], "color": BY_ID[a].color, "order": BY_ID[a].order,
                   "metric": BY_ID[a].timeline.metric_names.get(lang, ""), "entity_id": f"sensor.{DOMAIN}_{a}"}
                  for a in data["audits"] if BY_ID[a].timeline]
        return {"days": data["timeline"]["days"], "scales": data["timeline"]["scales"], "audits": audits,
                "events": [{"time": _iso(e["time"]), "kind": e["kind"], "note": e.get("note"),
                            "title": e.get("title"), "subentry_id": e.get("subentry_id")}
                           for e in data.get("events", [])],
                "entry_id": self.coordinator.config_entry.entry_id}
