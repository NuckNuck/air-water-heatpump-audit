// Audit-Karte: Ampel eines Audits und Tabelle seiner Prüfungen. Keine Fremdbibliotheken.
// Konfiguration:  type: custom:air-water-heatpump-audit-card
//                 entity: sensor.air_water_heatpump_audit_data_basis      (ein Audit)
//                 entities: [sensor.air_water_heatpump_audit_efficiency, …] (mehrere Audits in einer Tabelle)

const COLORS = {
  ok: "var(--success-color, #43a047)",
  hint: "var(--warning-color, #ffa600)",
  warn: "var(--error-color, #db4437)",
  info: "var(--info-color, #039be5)",
  not_assessable: "var(--disabled-color, #9e9e9e)",
};

// Datenreife-Balken: feste Farbe je Audit (bewusst keine Ampelfarben, die stehen für Urteile). Die Farbe liefert
// der Audit-Sensor (Attribut `color`, aus der Registry der Integration); hier nur der Rückfall.
const AUDIT_COLORS = {
  efficiency: "#8e24aa", flow_temperature: "#00897b", capacity: "#d81b60", data_basis: "#6d4c41", dhw: "#3949ab",
  cost: "#546e7a",
};
// Zeitstrahl-Sensor: kennt die zugeschalteten Audits (Attribut `audits`), daraus entsteht die Karte ohne `entities`.
const TIMELINE_ENTITY = "sensor.air_water_heatpump_audit_timeline";

function enabledAudits(hass) {
  return [...(hass?.states[TIMELINE_ENTITY]?.attributes?.audits ?? [])].sort((a, b) => a.order - b.order);
}

const TEXT = {
  de: {
    dq: "Datenqualität",
    dqLevels: { high: "hoch", medium: "mittel", low: "niedrig" },
    period: "Zeitraum",
    source: (s) => `Daten: ${s.used === "influxdb" ? "InfluxDB" : "Recorder"}`
      + (s.roles_from_recorder?.length ? ` (${s.roles_from_recorder.length} Eingänge aus dem Recorder)` : "")
      + (s.note ? ` · ${s.note}` : ""),
    columns: ["ID", "Prüfung", "Urteil", "Aktion", "Wert", "Erläuterung", "Herkunft"],
    who: { owner: "Selbst", installer: "Fachbetrieb", none: "Nichts nötig" },
    target: "Ziel",
    steps: { show: (n) => `▸ So geht's (${n} Schritte)`, hide: "▾ Schritte ausblenden" },
    impact: { save: (eur, kwh) => `Bringt ≈ ${eur} €/Jahr` + (kwh ? ` (≈ ${kwh} kWh Strom)` : ""),
      cost: (eur, kwh) => `Kostet ≈ ${eur} €/Jahr` + (kwh ? ` (≈ ${kwh} kWh Strom)` : ""),
      kwhOnly: (kwh, save) => `${save ? "Spart" : "Kostet"} ≈ ${kwh} kWh Strom im Jahr`, basis: "Grobe Schätzung" },
    conflict: "Zielkonflikt",
    priorities: { title: "Was am meisten bringt", note: "Grobe Schätzungen aus Hochrechnung und Faustwerten; zum Sortieren, nicht als Versprechen." },
    ctl: { via: "Über die Schnittstelle einstellbar", apply: "Übernehmen", done: "eingestellt",
      adminOnly: "ein Admin kann das hier übernehmen",
      confirm: (p, f) => `${p.label}: ${f(p.current)} → ${f(p.value)}${p.unit ? " " + p.unit : ""}\n\n`
        + "Das ändert die Einstellung der Wärmepumpe und trägt ein Ereignis ein. Übernehmen?",
      note: (p, f) => `${p.label}: ${f(p.current)} → ${f(p.value)}${p.unit ? " " + p.unit : ""} (über die Audit-Karte)`,
      ok: "Übernommen und als Ereignis eingetragen; die Audits rechnen neu.", failed: "Fehlgeschlagen" },
    origin: { sourced: "belegt", derived: "abgeleitet", physical: "physikalisch", descriptive: "beschreibend" },
    heat: (h) => `Wärme ${h.raw_kwh} kWh roh, ${h.corrected_kwh} kWh mit Offset ${h.offset_k >= 0 ? "+" : ""}${h.offset_k} K`
      + (h.offset_robust ? "" : " (vorläufig)") + (h.electricity_kwh != null ? ` · Zählerstrom ${h.electricity_kwh} kWh` : ""),
    kinds: { heating_curve: "Heizkurve geändert", valves: "Heizkörperventile verstellt",
      hydraulic_balancing: "Hydraulischer Abgleich", pump_setting: "Pumpe verstellt",
      dhw_setting: "Warmwasser-Einstellung", hardware: "Umbau an der Anlage", other: "Sonstiges" },
    section: (sec, fmt, kind) => `Bewertet ab ${fmt(sec.start)}: ${kind}${sec.note ? ` – ${sec.note}` : ""}`,
    missing: "Entität nicht gefunden",
    waiting: "Noch keine Auswertung (erste Rechnung nach dem Start von Home Assistant).",
    help: { what: "Was wird geprüft", rating: "Bewertung", source: "Grundlage", label: "Erklärung zu dieser Prüfung" },
    days: { show: (n) => `▸ Tageswerte (${n})`, hide: "▾ Tageswerte ausblenden", total: "Summe",
      cols: { day: "Tag", outdoor: "Außen Ø", electricity: "Strom (Zähler)", heat: "Wärme", heat_raw: "Wärme roh",
        cop: "Arbeitszahl", cop_raw: "AZ roh", carnot: "Gütegrad", dhw: "Warmwasser" },
      note: "Wärme mit Fühler-Offset korrigiert, „roh“ ohne. Strom vom Zähler, bei manchen Zählern nur ganze kWh.",
      gap: (min, pct, how) => `Datenlücke ${min} min, ${pct} % der Wärme aufgefüllt (${how})`,
      gapNote: "* Tag mit aufgefüllter Datenlücke (Überfahren zeigt Details).",
      gapHow: { counter: "Wärmezähler der Steuerung", load: "nach Heizlast geschätzt", time: "nach Zeitanteil geschätzt" } },
    ready: {
      title: "Datenreife",
      left: (n, unit) => `noch ${n} ${unit === "d" ? (n === 1 ? "Tag" : "Tage") : "h"}`,
      all: "alle Audits haben genug Daten",
      allFrom: (d) => `ab ~${d} alle bewertbar`,
      unknown: "Termin noch nicht absehbar",
      reached: "genug Daten",
      from: (d) => `ab ~${d}`,
      open: "noch nicht absehbar",
      of: (h, n, u) => `${h} von ${n} ${u}`,
      units: { days: "vollen Tagen", heating_days: "Heiztagen", hours: "Stunden", heating_hours: "h Heizbetrieb",
        cycles: "Zyklen", windows: "Messfenstern", charges: "Ladungen", nights: "ruhigen Nächten" },
      note: "Hochrechnung: Fällt ein Tag durch (Datenlücke, zu wenig Strom), rückt der Termin nach hinten. "
        + "Ein neues Ereignis startet alle Audits außer der Datenbasis neu.",
    },
  },
  en: {
    dq: "Data quality",
    dqLevels: { high: "high", medium: "medium", low: "low" },
    period: "Period",
    source: (s) => `Data: ${s.used === "influxdb" ? "InfluxDB" : "recorder"}`
      + (s.roles_from_recorder?.length ? ` (${s.roles_from_recorder.length} inputs from the recorder)` : "")
      + (s.note ? ` · ${s.note}` : ""),
    columns: ["ID", "Check", "Verdict", "Action", "Value", "Explanation", "Origin"],
    who: { owner: "Yourself", installer: "Installer", none: "Nothing needed" },
    target: "Target",
    steps: { show: (n) => `▸ How to (${n} steps)`, hide: "▾ Hide steps" },
    impact: { save: (eur, kwh) => `Saves ≈ €${eur}/year` + (kwh ? ` (≈ ${kwh} kWh electricity)` : ""),
      cost: (eur, kwh) => `Costs ≈ €${eur}/year` + (kwh ? ` (≈ ${kwh} kWh electricity)` : ""),
      kwhOnly: (kwh, save) => `${save ? "Saves" : "Costs"} ≈ ${kwh} kWh electricity per year`, basis: "Rough estimate" },
    conflict: "Trade-off",
    priorities: { title: "What helps most", note: "Rough estimates from the projection and rules of thumb; for ranking, not a promise." },
    ctl: { via: "Adjustable via the interface", apply: "Apply", done: "set",
      adminOnly: "an admin can apply this here",
      confirm: (p, f) => `${p.label}: ${f(p.current)} → ${f(p.value)}${p.unit ? " " + p.unit : ""}\n\n`
        + "This changes the heat pump setting and records an event. Apply?",
      note: (p, f) => `${p.label}: ${f(p.current)} → ${f(p.value)}${p.unit ? " " + p.unit : ""} (from the audit card)`,
      ok: "Applied and recorded as an event; the audits are recalculated.", failed: "Failed" },
    origin: { sourced: "sourced", derived: "derived", physical: "physical", descriptive: "descriptive" },
    heat: (h) => `Heat ${h.raw_kwh} kWh raw, ${h.corrected_kwh} kWh with offset ${h.offset_k >= 0 ? "+" : ""}${h.offset_k} K`
      + (h.offset_robust ? "" : " (preliminary)") + (h.electricity_kwh != null ? ` · metered electricity ${h.electricity_kwh} kWh` : ""),
    kinds: { heating_curve: "Heating curve changed", valves: "Radiator valves adjusted",
      hydraulic_balancing: "Hydraulic balancing", pump_setting: "Pump setting changed",
      dhw_setting: "Hot water setting", hardware: "Hardware change", other: "Other" },
    section: (sec, fmt, kind) => `Assessed from ${fmt(sec.start)}: ${kind}${sec.note ? ` – ${sec.note}` : ""}`,
    missing: "Entity not found",
    waiting: "No evaluation yet (first run after Home Assistant has started).",
    help: { what: "What is checked", rating: "Rating", source: "Basis", label: "About this check" },
    days: { show: (n) => `▸ Daily values (${n})`, hide: "▾ Hide daily values", total: "Total",
      cols: { day: "Day", outdoor: "Outdoor avg", electricity: "Electricity (meter)", heat: "Heat", heat_raw: "Heat raw",
        cop: "COP", cop_raw: "COP raw", carnot: "Carnot eff.", dhw: "Hot water" },
      note: "Heat corrected by the sensor offset, “raw” without. Electricity from the meter.",
      gap: (min, pct, how) => `Data gap ${min} min, ${pct} % of the heat filled in (${how})`,
      gapNote: "* Day with a filled data gap (hover for details).",
      gapHow: { counter: "controller heat counter", load: "estimated from heating load", time: "estimated from time share" } },
    ready: {
      title: "Data readiness",
      left: (n, unit) => `${n} ${unit === "d" ? (n === 1 ? "day" : "days") : "h"} to go`,
      all: "all audits have enough data",
      allFrom: (d) => `all assessable from ~${d}`,
      unknown: "date not yet foreseeable",
      reached: "enough data",
      from: (d) => `from ~${d}`,
      open: "not yet foreseeable",
      of: (h, n, u) => `${h} of ${n} ${u}`,
      units: { days: "full days", heating_days: "heating days", hours: "hours", heating_hours: "h of heating",
        cycles: "cycles", windows: "measuring windows", charges: "charges", nights: "quiet nights" },
      note: "Projection: if a day drops out (data gap, too little electricity), the date moves back. "
        + "A new event restarts all audits except the data basis.",
    },
  },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function formatValue(value, unit, locale) {
  if (value === null || value === undefined || typeof value === "object") return "";
  const text = typeof value === "number" ? value.toLocaleString(locale, { maximumFractionDigits: 2 }) : value;
  return unit ? `${text} ${unit}` : String(text);
}

class AirWaterAuditCard extends HTMLElement {
  // `entities`: mehrere Audits in einer gemeinsamen Tabelle (gleiche Spaltenbreiten, Audit-Titel als Zwischenzeile).
  // `entity`: ein einzelnes Audit. Ohne beides: alle zugeschalteten Audits in Registry-Reihenfolge.
  setConfig(config) {
    this._config = config;
    this._configured = config.entities ?? (config.entity ? [config.entity] : []);
    this._signature = null;
    this._open ??= new Set();  // aufgeklappte Tagestabellen und Schrittlisten, bleiben beim Neuzeichnen offen
    this._ctl ??= new Map();  // Stellgrößen-Vorschläge der aktuellen Darstellung: Schlüssel → {p}
    this._ctlStatus ??= new Map();  // Rückmeldung je Vorschlag, überlebt das Neuzeichnen
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this._wireHelp();
    }
  }

  // „?“ je Prüfung und Datenreife-Block (data-tip): Hilfe beim Überfahren oder Fokussieren; ein Klick hält sie offen,
  // damit man sie markieren kann.
  _wireHelp() {
    const TIP = ".q, [data-tip]";
    const root = this.shadowRoot;
    const show = (q, pin) => {
      const tip = root.getElementById("tip");
      if (!tip) return;
      if (q.dataset.tip === "ready") {
        if (!this._readyTip) return;
        tip.innerHTML = this._readyTip;
      } else {
        const h = this._hass?.states[q.dataset.entity]?.attributes?.help;
        if (!h) return;
        const t = TEXT[(this._hass.language || "en").startsWith("de") ? "de" : "en"].help;
        tip.innerHTML = `<div><b>${t.what}:</b> ${esc(h.what)}</div><div><b>${t.rating}:</b> ${esc(h.rating)}</div>`
          + `<div class="src"><b>${t.source}:</b> ${esc(h.source)}</div>`;
      }
      tip.hidden = false;
      const r = q.getBoundingClientRect();
      const w = Math.min(360, window.innerWidth - 16);
      tip.style.width = `${w}px`;
      tip.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
      const below = r.bottom + 6;
      tip.style.top = `${below + tip.offsetHeight > window.innerHeight ? Math.max(8, r.top - tip.offsetHeight - 6) : below}px`;
      this._tipPinned = pin ? q : null;
    };
    const hide = () => { const tip = root.getElementById("tip"); if (tip && !this._tipPinned) tip.hidden = true; };
    root.addEventListener("mouseover", (ev) => { const q = ev.target.closest?.(TIP); if (q && !this._tipPinned) show(q, false); });
    root.addEventListener("mouseout", (ev) => { if (ev.target.closest?.(TIP)) hide(); });
    root.addEventListener("focusin", (ev) => { const q = ev.target.closest?.(TIP); if (q && !this._tipPinned) show(q, false); });
    root.addEventListener("focusout", (ev) => { if (ev.target.closest?.(TIP)) hide(); });
    root.addEventListener("click", (ev) => {
      const toggle = ev.target.closest?.("[data-days]");
      if (toggle) {
        const id = toggle.dataset.days;
        this._open.has(id) ? this._open.delete(id) : this._open.add(id);
        this._render();
        return;
      }
      const ctl = ev.target.closest?.("[data-ctl]");
      if (ctl) { this._applyControl(ctl.dataset.ctl); return; }
      const q = ev.target.closest?.(TIP);
      if (q) { ev.stopPropagation(); if (this._tipPinned === q) { this._tipPinned = null; hide(); } else show(q, true); return; }
      if (!ev.target.closest?.("#tip")) { this._tipPinned = null; hide(); }
    });
    window.addEventListener("scroll", () => { this._tipPinned = null; hide(); }, { passive: true, capture: true });
  }

  set hass(hass) {
    this._hass = hass;
    const audits = this._entities.map((e) => hass.states[e]);
    const checks = audits.flatMap((a) => a?.attributes?.checks ?? []);
    const checkStates = checks.map((c) => hass.states[c.entity_id]);
    // Stellgrößen der Vorschläge: ändert sich ihr Zustand, zeigt die Karte „eingestellt“.
    const controls = checkStates.flatMap((s) => s?.attributes?.action?.controls ?? []).map((p) => hass.states[p.entity_id]);
    // Nur neu zeichnen, wenn sich eine der beteiligten Entitäten geändert hat.
    const signature = [...audits, ...checkStates, ...controls].map((s) => s?.last_updated).join("|")
      + hass.language + (hass.user?.is_admin ? "A" : "");
    if (signature === this._signature) return;
    this._signature = signature;
    this._render();
  }

  _checkRow(c, t) {
    const hass = this._hass;
    const st = hass.states[c.entity_id];
    const at = st?.attributes ?? {};
    const verdict = st?.state ?? c.verdict;
    const action = at.action ? this._action(c, at.action, t) : "";
    // Anzeigename ohne Gerätenamen und Prüf-ID: „Audit: Effizienz E3 Gütegrad“ → „Gütegrad“
    const name = this._checkName(c, at);
    const rows = c.check_id === "E1" ? at.details?.days ?? [] : [];
    const open = rows.length && this._open.has(c.check_id);
    const toggle = rows.length ? `<div><span class="toggle" role="button" tabindex="0" data-days="${esc(c.check_id)}">${open ? t.days.hide : t.days.show(rows.length)}</span></div>` : "";
    const days = open ? `<tr class="sub"><td></td><td colspan="${t.columns.length - 1}"><div class="scroll">${this._dayTable(rows, t)}</div></td></tr>` : "";
    const help = at.help ? ` <span class="q" tabindex="0" role="button" aria-label="${esc(t.help.label)}" data-entity="${esc(c.entity_id)}">?</span>` : "";
    return `<tr>
      <td class="id">${esc(c.check_id)}</td>
      <td>${esc(name)}${help}</td>
      <td>${this._pill(verdict, st, at.progress, t)}</td>
      <td class="action">${action}</td>
      <td class="num">${esc(formatValue(at.value, at.unit, hass.language))}</td>
      <td class="text">${esc(at.text)}${toggle}</td>
      <td class="origin">${esc(t.origin[at.origin] ?? at.origin)}</td>
    </tr>${days}`;
  }

  // Urteils-Marker; „nicht bewertbar“ füllt sich mit dem Datenstand grün, bis die Prüfung ihr Urteil hat.
  _pill(verdict, st, prog, t) {
    const hass = this._hass;
    const label = esc(st ? hass.formatEntityState(st) : verdict);
    if (verdict !== "not_assessable" || !prog?.need) {
      return `<span class="pill" style="background:${COLORS[verdict] ?? COLORS.not_assessable}">${label}</span>`;
    }
    const pct = Math.max(0, Math.min(100, Math.floor((100 * prog.have) / prog.need)));
    const loc = hass.locale?.language || hass.language;
    const num = (v) => Number(v).toLocaleString(loc, { maximumFractionDigits: 1 });
    const tip = `${pct} % – ${t.ready.of(num(prog.have), num(prog.need), t.ready.units[prog.unit] ?? prog.unit)}`;
    return `<span class="pill" title="${esc(tip)}" style="background:linear-gradient(to right, ${COLORS.ok} ${pct}%, `
      + `${COLORS.not_assessable} ${pct}%)">${label}</span>`;
  }

  // Aktion: wer und was, Zielwert, aufklappbare Schritte, Vorschläge für Stellgrößen der Schnittstelle.
  _action(c, a, t) {
    const hass = this._hass;
    let html = `<b>${esc(t.who[a.who] ?? a.who)}:</b> ${esc(a.text)}`;
    if (a.target) html += `<div class="target">${t.target}: <b>${esc(a.target)}</b></div>`;
    if (a.impact) html += `<div class="impact" title="${esc(t.impact.basis + ": " + a.impact.basis)}">${esc(this._impact(a.impact, t))}</div>`;
    for (const x of a.conflicts ?? []) html += `<div class="conflict"><b>${t.conflict}:</b> ${esc(x)}</div>`;
    for (const p of a.controls ?? []) {
      const key = `${c.check_id}|${p.role}`;
      this._ctl.set(key, { p });
      const now = hass.states[p.entity_id]?.state;
      const f = (v) => this._fmtCtl(v);
      const reached = now !== undefined && String(now) === String(p.value)
        || (Number.isFinite(Number(now)) && Number(now) === Number(p.value));
      const button = reached ? `<span class="done">✓ ${t.ctl.done}</span>`
        : hass.user?.is_admin ? `<button type="button" data-ctl="${esc(key)}">${t.ctl.apply}</button>`
          : `<span class="muted">(${t.ctl.adminOnly})</span>`;
      const status = this._ctlStatus.get(key);
      html += `<div class="ctl"><div class="muted">${t.ctl.via}:</div>`
        + `<div>${esc(p.label)}: ${esc(f(now ?? p.current))} → <b>${esc(f(p.value))}${p.unit ? " " + esc(p.unit) : ""}</b> ${button}</div>`
        + (status ? `<div class="muted">${esc(status)}</div>` : "") + `</div>`;
    }
    if (a.steps?.length) {
      const key = `steps|${c.check_id}`;
      const open = this._open.has(key);
      html += `<div><span class="toggle" role="button" tabindex="0" data-days="${esc(key)}">${open ? t.steps.hide : t.steps.show(a.steps.length)}</span></div>`;
      if (open) html += `<ol class="steps">${a.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>`;
    }
    return html;
  }

  // Wirkung einer Aktion als Satz; Beträge ohne Vorzeichen, die Richtung steckt im Verb.
  _impact(m, t) {
    const loc = this._hass.locale?.language || this._hass.language;
    const n = (v) => Math.abs(v).toLocaleString(loc, { maximumFractionDigits: 0 });
    if (m.eur_year != null) return (m.eur_year >= 0 ? t.impact.save : t.impact.cost)(n(m.eur_year), m.kwh_year != null ? n(m.kwh_year) : null);
    return t.impact.kwhOnly(n(m.kwh_year), m.kwh_year >= 0);
  }

  // Aktionen aller gezeigten Audits mit Ersparnis, nach Euro (ersatzweise kWh) sortiert.
  _priorities(t) {
    const hass = this._hass;
    const items = this._entities.flatMap((e) => hass.states[e]?.attributes?.checks ?? []).map((c) => {
      const at = hass.states[c.entity_id]?.attributes ?? {};
      const m = at.action?.impact;
      return m && ((m.eur_year ?? m.kwh_year) > 0) ? { c, at, m } : null;
    }).filter(Boolean).sort((x, y) => (y.m.eur_year ?? y.m.kwh_year / 4) - (x.m.eur_year ?? x.m.kwh_year / 4));
    if (!items.length) return "";
    const li = items.slice(0, 5).map(({ c, at, m }) =>
      `<li><b>${esc(c.check_id)} ${esc(this._checkName(c, at))}:</b> ${esc(this._impact(m, t))} – ${esc(at.action.text)}</li>`).join("");
    return `<div class="prio"><div class="rtitle">${t.priorities.title}</div><ol>${li}</ol><div class="meta">${t.priorities.note}</div></div>`;
  }

  _checkName(c, at) {
    return (at.friendly_name || c.key).replace(new RegExp(`^.*?\\b${c.check_id}\\s+`), "");
  }

  _fmtCtl(v) {
    const n = Number(v);
    return v !== null && v !== "" && Number.isFinite(n)
      ? n.toLocaleString(this._hass.locale?.language || this._hass.language, { maximumFractionDigits: 2 }) : String(v ?? "–");
  }

  // Stellgröße schreiben (nach Rückfrage) und die Änderung als Ereignis eintragen, damit Audits 1–3 neu ansetzen.
  async _applyControl(key) {
    const hass = this._hass;
    const entry = this._ctl.get(key);
    if (!entry || !hass.user?.is_admin) return;
    const { p } = entry;
    const t = TEXT[(hass.language || "en").startsWith("de") ? "de" : "en"];
    const f = (v) => this._fmtCtl(v);
    if (!window.confirm(t.ctl.confirm(p, f))) return;
    const select = p.domain === "select" || p.domain === "input_select";
    this._ctlStatus.set(key, "…");
    this._render();
    try {
      await hass.callService(p.domain, select ? "select_option" : "set_value",
        { entity_id: p.entity_id, ...(select ? { option: String(p.value) } : { value: p.value }) });
      const entryId = this._entities.map((e) => hass.states[e]?.attributes?.entry_id).find((x) => x);
      if (entryId) {
        const n = new Date();
        const time = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())} ${pad(n.getHours())}:${pad(n.getMinutes())}:00`;
        const flow = await hass.callApi("POST", "config/config_entries/subentries/flow", { handler: [entryId, "event"] });
        await hass.callApi("POST", `config/config_entries/subentries/flow/${flow.flow_id}`,
          { time, kind: p.event_kind, note: t.ctl.note(p, f) });
      }
      this._ctlStatus.set(key, t.ctl.ok);
    } catch (err) {
      this._ctlStatus.set(key, `${t.ctl.failed}: ${err?.body?.message ?? err?.message ?? err}`);
    }
    this._render();
  }

  // Tagestabelle unter einer Prüfung (bisher E1): neuester Tag oben, Summenzeile über alle Tage.
  _dayTable(rows, t) {
    const loc = this._hass.locale?.language || this._hass.language;
    const f = (v, d) => (v === null || v === undefined || !Number.isFinite(v) ? "–"
      : v.toLocaleString(loc, { minimumFractionDigits: d, maximumFractionDigits: d }));
    const c = t.days.cols;
    const line = (label, r) => `<tr><td>${label}</td><td>${f(r.outdoor_mean, 1)} °C</td><td>${f(r.electricity_kwh, 0)} kWh</td>`
      + `<td>${f(r.heat_kwh, 1)} kWh</td><td>${f(r.heat_raw_kwh, 1)} kWh</td><td><b>${f(r.heat_kwh / r.electricity_kwh, 2)}</b></td>`
      + `<td>${f(r.heat_raw_kwh / r.electricity_kwh, 2)}</td><td>${f(r.ideal_kwh / r.electricity_kwh, 2)}</td>`
      + `<td>${f(r.heat_kwh ? 100 * r.dhw_heat_kwh / r.heat_kwh : null, 0)} %</td></tr>`;
    const day = (iso) => esc(new Date(`${iso}T12:00:00`).toLocaleDateString(loc, { weekday: "short", day: "2-digit", month: "2-digit" }));
    const sum = (k) => rows.reduce((n, r) => n + (r[k] ?? 0), 0);
    const temps = rows.map((r) => r.outdoor_mean).filter((v) => v !== null && v !== undefined);
    const total = { electricity_kwh: sum("electricity_kwh"), heat_kwh: sum("heat_kwh"), heat_raw_kwh: sum("heat_raw_kwh"),
      ideal_kwh: sum("ideal_kwh"), dhw_heat_kwh: sum("dhw_heat_kwh"),
      outdoor_mean: temps.length ? temps.reduce((a, b) => a + b, 0) / temps.length : null };
    return `<table class="days"><thead><tr>${["day", "outdoor", "electricity", "heat", "heat_raw", "cop", "cop_raw", "carnot", "dhw"]
      .map((k) => `<th>${c[k]}</th>`).join("")}</tr></thead><tbody>
      ${[...rows].reverse().map((r) => line(day(r.day) + (r.gap_min ? ` <span class="gap" title="${esc(t.days.gap(r.gap_min,
        f(r.gap_share_pct, 0), t.days.gapHow[r.gap_method] ?? r.gap_method))}">*</span>` : ""), r)).join("")}
      ${rows.length > 1 ? line(`<b>${t.days.total}</b>`, total).replace("<tr>", '<tr class="total">') : ""}
      </tbody></table><div class="msg">${t.days.note}${rows.some((r) => r.gap_min) ? ` ${t.days.gapNote}` : ""}</div>`;
  }

  // Datenreife: ein Balken vom frühesten Zählbeginn bis zum spätesten Termin, je Audit ein Marker (Hochrechnung).
  _readiness(t) {
    const hass = this._hass;
    const r = t.ready;
    const loc = hass.locale?.language || hass.language;
    const ms = (iso) => (iso ? Date.parse(iso) : null);
    const date = (v) => new Date(v).toLocaleDateString(loc, { day: "2-digit", month: "2-digit" });
    const num = (v) => Number(v).toLocaleString(loc, { maximumFractionDigits: 1 });
    const items = this._entities.map((e) => {
      const st = hass.states[e];
      const rd = st?.attributes?.readiness;
      if (!rd) return null;
      const key = st.attributes.audit ?? e.replace(/^sensor\.air_water_heatpump_audit_/, "");
      return { key, rd, eta: ms(rd.eta), color: st.attributes.color ?? AUDIT_COLORS[key],
               name: st.attributes.audit_name ?? st.attributes.friendly_name ?? key };
    }).filter((x) => x);
    if (!items.length) return "";
    const now = Date.now();
    const start = Math.min(...items.map((x) => ms(x.rd.start)));
    const known = items.filter((x) => x.eta !== null);
    const end = Math.max(now, ...known.map((x) => x.eta));
    const pos = (v) => Math.max(0, Math.min(100, ((v - start) / (end - start || 1)) * 100));
    const pending = items.filter((x) => !x.rd.reached);
    const unknown = pending.some((x) => x.eta === null);
    let left = "", summary = r.all;
    if (pending.length) {
      const h = Math.max(0, (end - now) / 3600000);
      left = h >= 48 ? r.left(Math.ceil(h / 24), "d") : r.left(Math.ceil(h), "h");
      summary = unknown ? r.unknown : r.allFrom(date(end));
    }
    // Prüfungen mit gleicher Datenmenge zusammenfassen: „E2, E3, E4: 0 von 7 vollen Tagen“
    const missing = (x) => {
      const groups = new Map();
      for (const c of x.rd.checks.filter((c) => !c.reached)) {
        const k = `${c.have}|${c.need}|${c.unit}`;
        groups.set(k, [...(groups.get(k) ?? []), c]);
      }
      return [...groups.values()].map((g) => `${g.map((c) => c.check_id).join(", ")}: `
        + r.of(num(g[0].have), num(g[0].need), r.units[g[0].unit] ?? g[0].unit)).join(" · ");
    };
    const order = [...items].sort((a, b) => (a.eta ?? Infinity) - (b.eta ?? Infinity));
    // Stand je Audit und Hinweis zur Hochrechnung stehen im Tooltip, damit der Block nur Titelzeile und Balken braucht.
    this._readyTip = order.map((x) => `<div><span class="dot${x.rd.reached ? " done" : ""}" `
      + `style="--c:${x.color ?? "var(--primary-color)"}"></span><b>${esc(x.name)}</b> – `
      + (x.rd.reached ? r.reached : `${x.eta !== null ? r.from(date(x.eta)) : r.open} · ${esc(missing(x))}`) + `</div>`).join("")
      + `<div class="src">${r.note}</div>`;
    const markers = known.map((x) => `<div class="mk${x.rd.reached ? " done" : ""}" style="left:${pos(x.eta)}%;`
      + `--c:${x.color ?? "var(--primary-color)"}"></div>`).join("");
    return `<div class="ready" data-tip="ready">
        <div class="rhead"><span class="rtitle">${r.title}</span>${left ? `<b>${left}</b>` : ""}<span class="muted">${esc(summary)}</span><span class="q" tabindex="0" role="button" aria-label="${esc(r.title)}" data-tip="ready">?</span></div>
        <div class="bar"><div class="fill" style="width:${pos(now)}%"></div>${markers}</div>
      </div>`;
  }

  _auditRows(entityId, t, single) {
    const hass = this._hass;
    const audit = hass.states[entityId];
    const span = t.columns.length;
    if (!audit) return `<tr><td colspan="${span}" class="msg">${t.missing}: ${esc(entityId)}</td></tr>`;
    const a = audit.attributes;
    const title = (single && this._config.title) || a.audit_name || a.friendly_name || "";
    const head = `<tr class="audit"><td colspan="${span}"><div class="head">
        <div class="light" style="background:${COLORS[audit.state] ?? COLORS.not_assessable}"></div>
        <div class="title">${esc(title)}</div>
        <div class="state">${esc(hass.formatEntityState(audit))}</div>
      </div>${a.heat ? `<div class="heat">${esc(t.heat(a.heat))}</div>` : ""}</td></tr>`;
    if (audit.state === "unavailable" || audit.state === "unknown") {
      return head + `<tr><td colspan="${span}" class="msg">${t.waiting}</td></tr>`;
    }
    return head + (a.checks ?? []).map((c) => this._checkRow(c, t)).join("");
  }

  _render() {
    const hass = this._hass;
    this._ctl.clear();
    const t = TEXT[(hass.language || "en").startsWith("de") ? "de" : "en"];
    const fmtDate = (iso) => new Date(iso).toLocaleString(hass.locale?.language || hass.language,
      { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    // Datenqualität, Zeitraum und Quelle sind für alle Audits eines Laufs gleich: einmal oben.
    const first = this._entities.map((e) => hass.states[e]).find((s) => s?.attributes?.period_start);
    const a = first?.attributes;
    const sec = this._entities.map((e) => hass.states[e]?.attributes?.section).find((x) => x);
    const meta = a ? `<div class="meta">${t.dq}: <b>${esc(t.dqLevels[a.dq] ?? a.dq)}</b> · ${t.period}: ${esc(fmtDate(a.period_start))} – ${esc(fmtDate(a.period_end))}${a.source ? ` · ${esc(t.source(a.source))}` : ""}</div>`
      + (sec ? `<div class="meta">${esc(t.section(sec, fmtDate, t.kinds[sec.kind] ?? sec.kind))}</div>` : "") : "";
    const single = this._entities.length === 1;
    const body = this._entities.map((e) => `<tbody>${this._auditRows(e, t, single)}</tbody>`).join("");

    this.shadowRoot.innerHTML = `
      <style>
        /* hui-root setzt user-select: none; alle Texte der Karte sollen markier- und kopierbar sein. */
        ha-card { padding: 16px; user-select: text; -webkit-user-select: text; }
        .head { display: flex; align-items: center; gap: 12px; }
        .light { width: 24px; height: 24px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
        .title { font-size: 1.15em; font-weight: 500; flex: 1; }
        .state { font-weight: 500; }
        .meta, .heat { color: var(--secondary-text-color); font-size: .9em; }
        .meta { margin-bottom: 6px; }
        .heat { margin-top: 4px; }
        .impact { margin-top: 4px; font-weight: 500; cursor: help; }
        .conflict { margin-top: 4px; color: var(--secondary-text-color); font-size: .9em; }
        .prio { margin: 8px 0 12px; } .prio ol { margin: 4px 0; padding-left: 20px; }
        .scroll { overflow-x: auto; }
        /* Feste Spaltenbreiten: alle Audits nutzen dieselben Spalten, nichts springt beim Aktualisieren. */
        table { width: 100%; min-width: 960px; table-layout: fixed; border-collapse: collapse; font-size: .92em; }
        col.id { width: 44px; } col.name { width: 13%; } col.verdict { width: 115px; } col.action { width: 21%; }
        col.num { width: 85px; } col.origin { width: 112px; }
        th { text-align: left; color: var(--secondary-text-color); font-weight: 500; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); }
        td { padding: 6px; border-bottom: 1px solid var(--divider-color); vertical-align: top; overflow-wrap: anywhere; }
        /* Audit-Zwischenzeile hervorgehoben: Primärfarbe als Tönung über dem Kartenhintergrund, damit sie im dunklen
           wie im hellen Theme passt (volle Primärfarbe war im dunklen Theme zu hell); Akzentstreifen links. */
        tbody + tbody tr.audit td { border-top: 16px solid var(--ha-card-background, var(--card-background-color, #fff)); }
        tr.audit td { padding: 10px 8px; color: var(--primary-text-color);
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 22%, var(--ha-card-background, var(--card-background-color, #fff))); }
        tr.audit td:first-child { box-shadow: inset 4px 0 0 var(--primary-color, #03a9f4); }
        tr.audit .heat { color: inherit; opacity: .9; }
        tr.audit .light { box-shadow: 0 0 0 2px var(--primary-text-color); }
        td.id { font-family: var(--code-font-family, monospace); }
        td.num { text-align: right; overflow-wrap: normal; }
        .target { margin-top: 4px; }
        ol.steps { margin: 4px 0 0; padding-left: 18px; }
        ol.steps li + li { margin-top: 3px; }
        .ctl { margin-top: 6px; padding: 4px 6px; border-left: 3px solid var(--primary-color); }
        .ctl button { margin-left: 4px; font: inherit; padding: 1px 8px; cursor: pointer; border-radius: 4px;
          border: 1px solid var(--primary-color); background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .done { color: var(--success-color, #43a047); white-space: nowrap; }
        .muted { color: var(--secondary-text-color); }
        td.origin { color: var(--secondary-text-color); overflow-wrap: normal; white-space: nowrap; }
        .pill { color: #fff; border-radius: 10px; padding: 1px 8px; white-space: nowrap; font-size: .9em; }
        .msg { color: var(--secondary-text-color); }
        .q { display: inline-flex; align-items: center; justify-content: center; width: 15px; height: 15px; margin-left: 3px;
          border-radius: 50%; font-size: 11px; font-weight: 600; line-height: 1; cursor: help; vertical-align: 1px;
          color: var(--secondary-text-color); border: 1px solid var(--secondary-text-color); }
        .q:hover, .q:focus { color: var(--primary-color); border-color: var(--primary-color); outline: none; }
        #tip { position: fixed; z-index: 10; padding: 10px 12px; border-radius: 8px; font-size: .9em; line-height: 1.4;
          background: var(--card-background-color, #fff); color: var(--primary-text-color);
          box-shadow: 0 4px 16px rgba(0,0,0,.25); border: 1px solid var(--divider-color); }
        #tip div + div { margin-top: 6px; }
        #tip .src { color: var(--secondary-text-color); }
        .toggle { display: inline-block; margin-top: 4px; color: var(--primary-color); cursor: pointer; }
        tr.sub > td { background: var(--secondary-background-color, #f5f5f5); }
        table.days { min-width: 0; width: auto; table-layout: auto; font-size: .95em; }
        table.days th, table.days td { padding: 3px 10px 3px 0; border-bottom: 1px solid var(--divider-color); white-space: nowrap; text-align: right; }
        table.days th:first-child, table.days td:first-child { text-align: left; }
        table.days .gap { cursor: help; color: var(--secondary-text-color); }
        table.days tr.total td { border-top: 2px solid var(--divider-color); }
        .ready { margin: 6px 0 10px; }
        .rhead { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; margin-bottom: 6px; }
        .rtitle { font-weight: 500; }
        .bar { position: relative; height: 10px; border-radius: 5px; background: var(--divider-color); }
        .bar .fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; background: var(--primary-color); opacity: .75; }
        /* Marker: hohl = Termin hochgerechnet, voll = genug Daten */
        .mk { position: absolute; top: -4px; width: 4px; height: 18px; margin-left: -2px; border-radius: 2px;
          background: var(--ha-card-background, var(--card-background-color, #fff)); box-shadow: inset 0 0 0 2px var(--c); }
        .mk.done { background: var(--c); }
        .ready { cursor: help; }
        .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px;
          box-shadow: inset 0 0 0 2px var(--c); }
        .dot.done { background: var(--c); }
      </style>
      <ha-card>
        ${meta}
        ${this._readiness(t)}
        ${this._priorities(t)}
        <div class="scroll"><table>
          <colgroup><col class="id"><col class="name"><col class="verdict"><col class="action"><col class="num"><col class="text"><col class="origin"></colgroup>
          <thead><tr>${t.columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
          ${body}
        </table></div>
        <div id="tip" hidden></div>
      </ha-card>`;
    this._tipPinned = null;
  }

  getCardSize() {
    return 2 + this._entities.reduce((n, e) => n + 1 + (this._hass?.states[e]?.attributes?.checks?.length ?? 6), 0);
  }

  getGridOptions() {
    return { columns: "full" };
  }

  // Ohne Konfiguration: alle zugeschalteten Audits (Liste vom Zeitstrahl-Sensor)
  get _entities() {
    return this._configured.length ? this._configured : enabledAudits(this._hass).map((x) => x.entity_id);
  }

  static getStubConfig() {
    return {};
  }
}

if (!customElements.get("air-water-heatpump-audit-card")) {
  customElements.define("air-water-heatpump-audit-card", AirWaterAuditCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "air-water-heatpump-audit-card",
    name: "Luft-Wasser-Wärmepumpen-Audit",
    description: "Ampel und Prüfungen eines Wärmepumpen-Audits",
  });
}

// ---------------------------------------------------------------------------------------------------------------
// Zeitstrahl-Karte: je Audit ein Tageswert als Linie vor den Ampel-Bändern, Ereignisse als senkrechte Linien.
// Konfiguration:  type: custom:air-water-heatpump-audit-timeline-card
//                 entity: sensor.air_water_heatpump_audit_timeline   (Vorgabe)
// Admins können Ereignisse direkt hier eintragen (Subentry-Flow der Integration, REST-API nur für Admins).

const TL_AUDITS = ["efficiency", "flow_temperature", "capacity", "data_basis"];

const TL_TEXT = {
  de: {
    title: "Zeitstrahl",
    intro: "Je Audit ein Messwert pro Tag. Die farbigen Bänder sind dieselben Grenzen wie in der Tabelle; "
      + "senkrechte Linien sind eingetragene Ereignisse.",
    audits: {
      efficiency: ["Effizienz", "Gütegrad"],
      flow_temperature: ["Vorlauf", "Pufferverlust"],
      capacity: ["Leistung", "Starts pro Tag"],
      data_basis: ["Datenbasis", "Abdeckung"],
    },
    notes: {
      efficiency: "Tageswert; das Urteil in der Tabelle gilt erst für eine Woche. Blau oben: unplausibel hoch, eher ein Messfehler.",
      capacity: "Grenze aus Prüfung C1 (2.000 Starts pro Jahr, umgerechnet auf die Heizstunden des Standorts).",
      dhw: "Aus den Warmwasserladungen des Tages; dieselbe Ampel wie beim Heizen.",
      cost: "Ohne Grundpreis. Grenze: früherer Brennstoff plus 10 % Messtoleranz (Prüfung K1).",
    },
    units: { "1/d": "/Tag" },
    verdicts: { ok: "grün", hint: "gelb", warn: "rot", info: "Info", not_assessable: "nicht bewertbar" },
    cop: "Arbeitszahl",
    cost: "Stromkosten",
    none: "Noch kein voller Tag ausgewertet. Der erste Tageswert erscheint nach Mitternacht.",
    events: "Ereignisse",
    noEvents: "Noch keine Ereignisse eingetragen.",
    beforeRange: "vor dem gezeigten Zeitraum",
    add: "Ereignis hinzufügen",
    manage: "Ereignisse ändern oder löschen →",
    time: "Zeitpunkt", kind: "Art", note: "Notiz", save: "Speichern", cancel: "Abbrechen",
    notePlaceholder: "z. B. Parallelverschiebung −1 K",
    saved: "Gespeichert. Die Audits werden neu gerechnet, das dauert einige Sekunden.",
    failed: "Speichern fehlgeschlagen",
    pick: "Auf einen Punkt tippen zeigt die Werte des Tages. Jeder Punkt steht für einen ganzen Tag (0–24 Uhr); "
      + "ein hohler Punkt heißt: An diesem Tag wurde etwas geändert, der Wert mischt beide Zustände.",
    mixed: "Tag mit Ereignis – Wert mischt die Zeit davor und danach",
    today: "heute",
    latest: "zuletzt",
    missing: "Entität nicht gefunden",
  },
  en: {
    title: "Timeline",
    intro: "One measured value per day and audit. The coloured bands use the same limits as the table; "
      + "vertical lines are recorded events.",
    audits: {
      efficiency: ["Efficiency", "Carnot efficiency"],
      flow_temperature: ["Flow temperature", "Buffer loss"],
      capacity: ["Capacity", "Starts per day"],
      data_basis: ["Data basis", "Coverage"],
    },
    notes: {
      efficiency: "Daily value; the verdict in the table needs a full week. Blue at the top: implausibly high, more likely a measurement error.",
      capacity: "Limit from check C1 (2,000 starts per year, scaled to the site's heating hours).",
      dhw: "From the day's hot water charges; same colours as for space heating.",
      cost: "Without standing charge. Limit: previous fuel plus 10 % measurement tolerance (check K1).",
    },
    units: { "1/d": "/day" },
    verdicts: { ok: "green", hint: "yellow", warn: "red", info: "info", not_assessable: "not assessable" },
    cop: "COP",
    cost: "electricity cost",
    none: "No full day evaluated yet. The first daily value appears after midnight.",
    events: "Events",
    noEvents: "No events recorded yet.",
    beforeRange: "before the period shown",
    add: "Add event",
    manage: "Edit or delete events →",
    time: "Time", kind: "Kind", note: "Note", save: "Save", cancel: "Cancel",
    notePlaceholder: "e.g. parallel shift −1 K",
    saved: "Saved. The audits are being recalculated, this takes a few seconds.",
    failed: "Saving failed",
    pick: "Tap a point to see the values of that day. Each point stands for a whole day (0–24 h); "
      + "a hollow point means something was changed that day, so the value mixes both states.",
    mixed: "Day with an event – the value mixes the time before and after",
    today: "today",
    latest: "latest",
    missing: "Entity not found",
  },
};

const pad = (n) => String(n).padStart(2, "0");

class AirWaterAuditTimelineCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.air_water_heatpump_audit_timeline", ...config };
    this._signature = null;
    this._selected = null;
    if (!this.shadowRoot) this._build();
  }

  connectedCallback() {
    if (!this._resize) {
      this._resize = new ResizeObserver(() => this._update(true));
      this._resize.observe(this);
    }
  }

  disconnectedCallback() {
    this._resize?.disconnect();
    this._resize = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._update(false);
  }

  _t() {
    return TL_TEXT[(this._hass?.language || "en").startsWith("de") ? "de" : "en"];
  }

  _locale() {
    return this._hass?.locale?.language || this._hass?.language || "en";
  }

  // Das Formular steht in einem eigenen Bereich, der beim Neuzeichnen der Diagramme erhalten bleibt.
  _build() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; user-select: text; -webkit-user-select: text; }
        h2 { margin: 0 0 4px; font-size: 1.2em; font-weight: 500; }
        .muted { color: var(--secondary-text-color); font-size: .9em; }
        .chart { margin-top: 14px; }
        .chart .label { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
        .chart .label b { font-weight: 500; }
        svg { display: block; width: 100%; overflow: visible; }
        svg text { font-size: 11px; fill: var(--secondary-text-color); }
        svg .ev text { fill: var(--primary-text-color); font-weight: 600; }
        svg circle { cursor: pointer; }
        .day { margin-top: 12px; padding: 8px 10px; border-radius: 8px; background: var(--secondary-background-color); }
        .events { margin-top: 16px; }
        .events h3 { margin: 0 0 6px; font-size: 1em; font-weight: 500; }
        .events ol { margin: 0; padding-left: 0; list-style: none; }
        .events li { margin: 3px 0; }
        .badge { display: inline-block; min-width: 18px; padding: 0 4px; margin-right: 6px; border-radius: 9px; text-align: center;
          background: var(--primary-color); color: var(--text-primary-color, #fff); font-size: .85em; }
        .admin { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
        .admin .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
        .admin form { display: none; flex-direction: column; gap: 8px; max-width: 520px; }
        .admin form.open { display: flex; }
        .admin label { display: flex; flex-direction: column; gap: 2px; font-size: .9em; color: var(--secondary-text-color); }
        .admin input, .admin select, .admin textarea { font: inherit; padding: 6px; border-radius: 6px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        button { font: inherit; padding: 6px 14px; border-radius: 6px; border: none; cursor: pointer;
          background: var(--primary-color); color: var(--text-primary-color, #fff); }
        button.secondary { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
        a { color: var(--primary-color); }
        .status { font-size: .9em; }
      </style>
      <ha-card>
        <div id="charts"></div>
        <div id="admin" class="admin" hidden></div>
      </ha-card>`;
    this._charts = this.shadowRoot.getElementById("charts");
    this._admin = this.shadowRoot.getElementById("admin");
    this._charts.addEventListener("click", (ev) => {
      const i = ev.target?.dataset?.day;
      if (i === undefined) return;
      this._selected = Number(i) === this._selected ? null : Number(i);
      this._update(true);
    });
  }

  _update(force) {
    const hass = this._hass;
    if (!hass || !this._charts) return;
    const st = hass.states[this._config.entity];
    const width = Math.round(this._charts.clientWidth || 600);
    const signature = [st?.last_updated, width, this._selected, hass.language].join("|");
    if (!force && signature === this._signature) return;
    this._signature = signature;
    this._renderCharts(st, width);
    this._renderAdmin(st);
  }

  _fmt(v, decimals) {
    return v === null || v === undefined ? "–"
      : Number(v).toLocaleString(this._locale(), { minimumFractionDigits: decimals ?? 0, maximumFractionDigits: decimals ?? 0 });
  }

  _fmtTime(iso, withTime = true) {
    return new Date(iso).toLocaleString(this._locale(), withTime
      ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "2-digit" });
  }

  _unit(u, t) {
    return t.units[u] ?? (u ? ` ${u}` : "");
  }

  _renderCharts(st, width) {
    const t = this._t();
    const title = `<h2>${esc(this._config.title || t.title)}</h2><div class="muted">${t.intro}</div>`;
    if (!st) {
      this._charts.innerHTML = `${title}<p class="muted">${t.missing}: ${esc(this._config.entity)}</p>`;
      return;
    }
    const a = st.attributes;
    const days = a.days ?? [];
    const events = (a.events ?? []).map((e, i) => ({ ...e, n: i + 1, t: Date.parse(e.time) / 1000 }));
    if (!days.length) {
      this._charts.innerHTML = title + `<p class="muted">${t.none}</p>` + this._eventList(events, null, t);
      return;
    }
    const x0 = days[0].start;
    const now = Date.now() / 1000;
    const x1 = Math.max(days[days.length - 1].end, this._nextMidnight(now));
    const geo = { width, left: 44, right: 10, x0, x1, now };
    geo.x = (s) => geo.left + (s - x0) / (x1 - x0) * (width - geo.left - geo.right);
    geo.days = this._dayGrid(x0, x1, now, geo, t);
    const visible = events.filter((e) => e.t >= x0 && e.t <= x1);
    const audits = this._tlAudits(a);
    const charts = audits.map((audit, k) => this._chart(audit, a.scales?.[audit] ?? {}, days, visible, geo, t,
      k === 0, k === audits.length - 1)).join("");
    const sel = this._selected !== null && days[this._selected] ? this._dayDetails(days[this._selected], a.scales, t, events)
      : `<div class="muted" style="margin-top:8px">${t.pick}</div>`;
    this._charts.innerHTML = title + charts + sel + this._eventList(events, x0, t);
  }

  // Zugeschaltete Audits mit Zeitstrahl: Linien zuerst, Streifen (Datenbasis) zuletzt
  _tlAudits(a) {
    const meta = a.audits ?? TL_AUDITS.map((id, order) => ({ id, order }));
    this._meta = Object.fromEntries(meta.map((x) => [x.id, x]));
    return meta.filter((x) => a.scales?.[x.id])
      .sort((x, y) => (a.scales[x.id].strip ? 1 : 0) - (a.scales[y.id].strip ? 1 : 0) || x.order - y.order)
      .map((x) => x.id);
  }

  _names(audit, t) {
    const m = this._meta?.[audit] ?? {};
    return t.audits[audit] ?? [m.name ?? audit, m.metric ?? ""];
  }

  _chart(audit, scale, days, events, geo, t, first, last) {
    const [name, metric] = this._names(audit, t);
    const strip = !!scale.strip;
    const top = first ? 14 : 4;
    const plotH = strip ? 16 : 90;
    const axisH = 16;
    const h = top + plotH + axisH;
    const values = days.map((d) => d[audit]?.value).filter((v) => v !== null && v !== undefined);
    const lo = scale.min ?? 0;
    let hi = scale.max;
    if (hi === null || hi === undefined) {
      const bandTop = Math.max(0, ...(scale.bands ?? []).map((b) => b[1] ?? 0));
      hi = Math.max(1, ...values, bandTop * 1.5) * 1.1;
    }
    const y = (v) => top + plotH - (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo) * plotH;
    const xl = geo.left, xr = geo.width - geo.right;
    let svg = "";
    if (strip) {
      // Datenbasis: nur Ampel-Streifen, ein Feld je Tag
      days.forEach((d, i) => {
        const p = d[audit] ?? {};
        svg += `<rect data-day="${i}" x="${geo.x(d.start) + 0.5}" y="${top}" width="${Math.max(1, geo.x(d.end) - geo.x(d.start) - 1)}"
          height="${plotH}" rx="2" fill="${COLORS[p.verdict] ?? COLORS.not_assessable}" style="cursor:pointer">
          <title>${esc(d.day)}: ${esc(this._fmt(p.value, 1))} %</title></rect>`;
      });
    } else {
      for (const [b0, b1, verdict] of scale.bands ?? []) {
        const yTop = y(b1 ?? hi), yBottom = y(b0);
        svg += `<rect x="${xl}" y="${yTop}" width="${xr - xl}" height="${Math.max(0, yBottom - yTop)}"
          fill="${COLORS[verdict]}" fill-opacity=".13"/>`;
      }
      // y-Achse: Grenzen der Bänder beschriften
      const ticks = [...new Set([lo, hi, ...(scale.bands ?? []).flatMap((b) => [b[0], b[1]])
        .filter((v) => v !== null && v > lo && v < hi)])];
      // Beschriftungen, die näher als 11 px aneinander lägen, weglassen. Vorrang: Grenzen des grünen Bands, dann
      // übrige Grenzen, dann Achsenenden.
      const okEdges = (scale.bands ?? []).filter((b) => b[2] === "ok").flatMap((b) => [b[0], b[1]]);
      const rank = (v) => (okEdges.includes(v) ? 0 : v === lo || v === hi ? 2 : 1);
      const drawn = [];
      for (const v of ticks.sort((p, q) => rank(p) - rank(q))) {
        if (drawn.some((d) => Math.abs(y(d) - y(v)) < 11)) continue;
        drawn.push(v);
        svg += `<text x="${xl - 4}" y="${y(v) + 4}" text-anchor="end">${esc(this._fmt(v, v === hi && scale.max == null ? 0 : scale.decimals))}</text>`;
      }
      svg += `<line x1="${xl}" x2="${xr}" y1="${top + plotH}" y2="${top + plotH}" stroke="var(--divider-color)"/>`;
      // Linie mit Lücken an Tagen ohne Wert
      let path = "", open = false;
      days.forEach((d) => {
        const v = d[audit]?.value;
        if (v === null || v === undefined) { open = false; return; }
        path += `${open ? "L" : "M"}${geo.x((d.start + d.end) / 2).toFixed(1)},${y(v).toFixed(1)}`;
        open = true;
      });
      svg += `<path d="${path}" fill="none" stroke="var(--primary-text-color)" stroke-opacity=".55" stroke-width="1.5"/>`;
      days.forEach((d, i) => {
        const p = d[audit];
        if (!p || p.value === null || p.value === undefined) return;
        const r = i === this._selected ? 6 : 4;
        const color = COLORS[p.verdict] ?? COLORS.not_assessable;
        // Tag mit Ereignis: hohler Punkt, weil der Tageswert beide Zustände mischt
        const mixed = this._mixed(d, events);
        svg += `<circle data-day="${i}" cx="${geo.x((d.start + d.end) / 2)}" cy="${y(p.value)}" r="${r}"
          fill="${mixed ? "var(--card-background-color, #fff)" : color}" stroke="${mixed ? color : "var(--card-background-color, #fff)"}"
          stroke-width="${mixed ? 2 : 1.5}" style="cursor:pointer">
          <title>${esc(d.day)}: ${esc(this._fmt(p.value, scale.decimals))}${esc(this._unit(scale.unit, t))} (${esc(t.verdicts[p.verdict] ?? p.verdict)})${mixed ? ` – ${esc(t.mixed)}` : ""}</title></circle>`;
      });
    }
    // Tagesraster: Trennlinie an jeder Mitternacht, noch nicht vergangener Teil von heute abgedunkelt
    for (const g of geo.days) {
      svg += `<line x1="${g.x0}" x2="${g.x0}" y1="${top}" y2="${top + plotH + 4}" stroke="var(--secondary-text-color)" stroke-opacity=".35"/>`;
    }
    if (geo.now < geo.x1) {
      const nx = geo.x(geo.now);
      svg += `<rect x="${nx}" y="${top}" width="${Math.max(0, xr - nx)}" height="${plotH}" fill="var(--secondary-text-color)" fill-opacity=".12"/>`;
    }
    // Ereignisse: senkrechte Linien, Nummer nur im obersten Diagramm
    for (const e of events) {
      const ex = geo.x(e.t);
      // Kurzinfo auf der ganzen Gruppe; breite unsichtbare Linie als Trefferfläche, die gestrichelte ist zu schmal
      const tip = `${e.n} · ${e.title || ""}${e.note ? ` – ${e.note}` : ""}`;
      svg += `<g class="ev"><title>${esc(tip)}</title><line x1="${ex}" x2="${ex}" y1="${first ? 12 : 0}" y2="${top + plotH}"
        stroke="var(--primary-color)" stroke-width="1.5" stroke-dasharray="4 3"/>
        <line x1="${ex}" x2="${ex}" y1="0" y2="${top + plotH}" stroke="transparent" stroke-width="12"/>`
        + (first ? `<text x="${ex}" y="9" text-anchor="middle">${e.n}</text>` : "") + `</g>`;
    }
    for (const g of geo.days) {
      if (g.label) svg += `<text x="${(g.x0 + g.x1) / 2}" y="${top + plotH + 13}" text-anchor="middle"${g.today ? ' font-weight="600"' : ""}>${esc(g.label)}</text>`;
    }
    const latest = [...days].reverse().find((d) => d[audit]?.value !== null && d[audit]?.value !== undefined);
    const now = latest ? `${this._fmt(latest[audit].value, strip ? 1 : scale.decimals)}${this._unit(scale.unit, t)} (${esc(latest.day.slice(8, 10) + "." + latest.day.slice(5, 7) + ".")})` : "–";
    const note = t.notes[audit] && (!["capacity", "cost"].includes(audit) || (scale.bands ?? []).length) ? `<div class="muted">${t.notes[audit]}</div>` : "";
    return `<div class="chart">
      <div class="label"><b>${esc(name)}</b><span class="muted">${esc(metric)} · ${t.latest} ${esc(now)}</span></div>${note}
      <svg viewBox="0 0 ${geo.width} ${h}" height="${h}" preserveAspectRatio="none">${svg}</svg></div>`;
  }

  _nextMidnight(s) {
    const d = new Date(s * 1000);
    d.setHours(24, 0, 0, 0);
    return d.getTime() / 1000;
  }

  // Ortstage zwischen x0 und x1 mit Beschriftung; bei Platzmangel nur jeder n-te Tag (heute immer)
  _dayGrid(x0, x1, now, geo, t) {
    const out = [];
    const d = new Date(x0 * 1000);
    d.setHours(0, 0, 0, 0);
    while (d.getTime() / 1000 < x1) {
      const a = d.getTime() / 1000;
      d.setDate(d.getDate() + 1);
      const b = d.getTime() / 1000;
      out.push({ s: a, e: b, x0: geo.x(Math.max(a, x0)), x1: geo.x(Math.min(b, x1)), today: a <= now && now < b });
    }
    const slot = (geo.width - geo.left - geo.right) / Math.max(1, out.length);
    const every = slot >= 34 ? 1 : Math.ceil(34 / slot);
    const loc = this._locale();
    out.forEach((g, i) => {
      if (!g.today && (out.length - 1 - i) % every) return;
      const day = new Date(g.s * 1000);
      const date = day.toLocaleDateString(loc, { day: "2-digit", month: "2-digit" });
      if (g.today && slot >= 90) g.label = `${t.today}, ${date}`;
      else if (slot >= 64) g.label = `${day.toLocaleDateString(loc, { weekday: "short" })} ${date}`;
      else g.label = date;
    });
    return out;
  }

  _mixed(d, events) {
    return events.some((e) => e.t > d.start && e.t < d.end);
  }

  _dayDetails(d, scales, t, events) {
    const parts = Object.keys(scales ?? {}).filter((audit) => d[audit]).map((audit) => {
      const p = d[audit] ?? {};
      const sc = scales?.[audit] ?? {};
      const [name, metric] = this._names(audit, t);
      let text = `${metric} ${this._fmt(p.value, sc.strip ? 1 : sc.decimals)}${p.value == null ? "" : this._unit(sc.unit, t)}`
        + ` (${t.verdicts[p.verdict] ?? p.verdict ?? "–"})`;
      if (audit === "dhw" && p.cop != null) text += `, ${t.cop} ${this._fmt(p.cop, 1)}`;
      if (audit === "cost" && p.cost_eur != null) text += `, ${t.cost} ${this._fmt(p.cost_eur, 2)} €`;
      if (audit === "efficiency" && p.cop != null) {
        text += `, ${t.cop} ${this._fmt(p.cop, 1)} = ${this._fmt(p.heat_kwh, 1)} kWh ÷ ${this._fmt(p.electricity_kwh, 0)} kWh`;
        if (p.outdoor_mean != null) text += `, ${this._fmt(p.outdoor_mean, 1)} °C`;
      }
      return `<div><b>${esc(name)}:</b> ${esc(text)}</div>`;
    }).join("");
    const mixed = this._mixed(d, events ?? []) ? `<div class="muted">${esc(t.mixed)}</div>` : "";
    return `<div class="day"><div><b>${esc(new Date(d.start * 1000).toLocaleDateString(this._locale(), { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }))}</b></div>${mixed}${parts}</div>`;
  }

  _eventList(events, x0, t) {
    const kinds = TEXT[(this._hass?.language || "en").startsWith("de") ? "de" : "en"].kinds;
    const items = events.map((e) => `<li><span class="badge">${e.n}</span>${esc(this._fmtTime(e.time))} · `
      + `${esc(kinds[e.kind] ?? e.kind)}${e.note ? ` – ${esc(e.note)}` : ""}`
      + (x0 !== null && e.t < x0 ? ` <span class="muted">(${t.beforeRange})</span>` : "") + `</li>`).join("");
    return `<div class="events"><h3>${t.events}</h3>${items ? `<ol>${items}</ol>` : `<div class="muted">${t.noEvents}</div>`}</div>`;
  }

  // Nur für Admins: Ereignis anlegen (Subentry-Flow) und Link zur Integrationsseite.
  _renderAdmin(st) {
    const isAdmin = !!this._hass?.user?.is_admin;
    const entryId = st?.attributes?.entry_id;
    this._admin.hidden = !(isAdmin && entryId);
    if (this._admin.hidden || this._admin.dataset.lang === this._hass.language) return;
    this._admin.dataset.lang = this._hass.language;
    const t = this._t();
    const kinds = TEXT[(this._hass.language || "en").startsWith("de") ? "de" : "en"].kinds;
    this._admin.innerHTML = `
      <div class="row">
        <button type="button" id="open">${t.add}</button>
        <a href="/config/integrations/integration/air_water_heatpump_audit">${t.manage}</a>
      </div>
      <form id="form">
        <label>${t.time}<input type="datetime-local" name="time" required></label>
        <label>${t.kind}<select name="kind">${Object.entries(kinds).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
        <label>${t.note}<textarea name="note" rows="2" placeholder="${esc(t.notePlaceholder)}"></textarea></label>
        <div class="row"><button type="submit">${t.save}</button><button type="button" class="secondary" id="cancel">${t.cancel}</button></div>
      </form>
      <div class="status muted" id="status"></div>`;
    const form = this._admin.querySelector("#form");
    const status = this._admin.querySelector("#status");
    this._admin.querySelector("#open").addEventListener("click", () => {
      const n = new Date();
      form.time.value = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}T${pad(n.getHours())}:${pad(n.getMinutes())}`;
      form.classList.add("open");
      status.textContent = "";
    });
    this._admin.querySelector("#cancel").addEventListener("click", () => form.classList.remove("open"));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const id = this._hass.states[this._config.entity]?.attributes?.entry_id;
      const data = { time: form.time.value.replace("T", " ") + ":00", kind: form.kind.value, note: form.note.value.trim() };
      status.textContent = "…";
      try {
        const flow = await this._hass.callApi("POST", "config/config_entries/subentries/flow", { handler: [id, "event"] });
        const res = await this._hass.callApi("POST", `config/config_entries/subentries/flow/${flow.flow_id}`, data);
        if (res.type !== "create_entry") throw new Error(JSON.stringify(res.errors ?? res.reason ?? res.type));
        form.reset();
        form.classList.remove("open");
        status.textContent = t.saved;
      } catch (err) {
        status.textContent = `${t.failed}: ${err?.body?.message ?? err?.message ?? err}`;
      }
    });
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  static getStubConfig() {
    return { entity: "sensor.air_water_heatpump_audit_timeline" };
  }
}

if (!customElements.get("air-water-heatpump-audit-timeline-card")) {
  customElements.define("air-water-heatpump-audit-timeline-card", AirWaterAuditTimelineCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "air-water-heatpump-audit-timeline-card",
    name: "Luft-Wasser-Wärmepumpen-Audit Zeitstrahl",
    description: "Tageswerte je Audit mit Ampel-Bändern und Ereignissen",
  });
}
