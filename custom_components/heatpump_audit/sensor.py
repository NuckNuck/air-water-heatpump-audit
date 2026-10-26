"""Ergebnis-Sensoren: je Audit einer (Gesamturteil) und je Prüfung einer (Urteil, Wert, Text, Herkunft).

Zustand ist immer das Urteil (Enum). Große Attribute (Details, Zyklen) landen nicht im Recorder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .audit_core.help import CHECK_HELP
from .const import AUDITS, CHECKS, DOMAIN, VERDICTS
from .coordinator import HeatpumpAuditConfigEntry, HeatpumpAuditCoordinator

MAX_CYCLES_IN_ATTRIBUTES = 200


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def check_entity_id(check_id: str, key: str) -> str:
    return f"sensor.heatpump_audit_{check_id.lower()}_{key}"


async def async_setup_entry(hass: HomeAssistant, entry: HeatpumpAuditConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [AuditSensor(coordinator, audit) for audit in AUDITS]
    entities += [CheckSensor(coordinator, audit, check_id, key) for audit, check_id, key in CHECKS]
    entities.append(TimelineSensor(coordinator))
    async_add_entities(entities)


class _Entity(CoordinatorEntity[HeatpumpAuditCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatpumpAuditCoordinator, unique_key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="WP-Audit",
                                            manufacturer="ha-heatpump-audit", model="Audit 0–3",
                                            entry_type=DeviceEntryType.SERVICE)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None


class _Base(_Entity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = VERDICTS


class AuditSensor(_Base):
    _unrecorded_attributes = frozenset({"checks", "cycles", "heat", "points", "runtime_s", "source", "entry_id",
                                        "readiness"})

    def __init__(self, coordinator: HeatpumpAuditCoordinator, audit: str) -> None:
        super().__init__(coordinator, audit)
        self._audit = audit
        self._attr_translation_key = audit
        self.entity_id = f"sensor.heatpump_audit_{audit}"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data["audits"][self._audit]["verdict"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        audit = data["audits"][self._audit]
        attrs: dict[str, Any] = {
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
        if self._audit != "data_basis" and (event := data.get("section", {}).get("event")):
            # Audits 1–3 rechnen ab dem letzten Ereignis (Spezifikation 1.5)
            attrs["section"] = {"start": _iso(event["time"]), "kind": event["kind"], "title": event.get("title"),
                                "note": event.get("note")}
        if self._audit == "data_basis":
            attrs["heat"] = data["heat"]
        elif self._audit == "capacity":
            attrs["cycles"] = [{k: c[k] for k in ("start", "end", "duration_min", "pause_before", "kind",
                                                  "open_start", "open_end", "defrost_stops")}
                               for c in data["cycles"][-MAX_CYCLES_IN_ATTRIBUTES:]]
        return attrs


class CheckSensor(_Base):
    _unrecorded_attributes = frozenset({"action", "details", "help", "text", "progress"})

    def __init__(self, coordinator: HeatpumpAuditCoordinator, audit: str, check_id: str, key: str) -> None:
        super().__init__(coordinator, f"{check_id.lower()}_{key}")
        self._audit, self._check_id = audit, check_id
        self._attr_translation_key = key
        self.entity_id = check_entity_id(check_id, key)

    def _result(self) -> dict | None:
        for r in self.coordinator.data["audits"][self._audit]["checks"]:
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
    _unrecorded_attributes = frozenset({"days", "scales", "events", "entry_id"})

    def __init__(self, coordinator: HeatpumpAuditCoordinator) -> None:
        super().__init__(coordinator, "timeline")
        self.entity_id = "sensor.heatpump_audit_timeline"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data["timeline"]["days"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {"days": data["timeline"]["days"], "scales": data["timeline"]["scales"],
                "events": [{"time": _iso(e["time"]), "kind": e["kind"], "note": e.get("note"),
                            "title": e.get("title"), "subentry_id": e.get("subentry_id")}
                           for e in data.get("events", [])],
                "entry_id": self.coordinator.config_entry.entry_id}
