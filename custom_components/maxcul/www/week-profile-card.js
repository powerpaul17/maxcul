const DAYS = [
  ["Mon", "Montag"],
  ["Tue", "Dienstag"],
  ["Wed", "Mittwoch"],
  ["Thu", "Donnerstag"],
  ["Fri", "Freitag"],
  ["Sat", "Samstag"],
  ["Sun", "Sonntag"],
];

const MIN_TEMP = 4.5;
const MAX_TEMP = 30.5;
const DAY_MINUTES = 24 * 60;
const STEP_MINUTES = 5;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatTime(minutes) {
  if (minutes >= DAY_MINUTES) return "24:00";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function makeDefaultSchedule() {
  return DAYS.map(() => [{ end: DAY_MINUTES, temperature: 20 }]);
}

function parseProfile(profile) {
  const schedule = Array(DAYS.length);
  for (const line of profile.split(/\r?\n/)) {
    const match = line.trim().match(/^(\w+)\s+(.+)$/);
    if (!match) continue;
    const dayName = match[1].slice(0, 3).toLowerCase();
    const dayIndex = DAYS.findIndex(
      ([shortName]) => shortName.toLowerCase() === dayName,
    );
    if (dayIndex < 0) continue;

    const values = match[2].split(",").map((value) => value.trim());
    const segments = [];
    let temperature = Number(values[0]);
    if (!Number.isFinite(temperature)) continue;
    for (let index = 1; index < values.length; index += 2) {
      const [hours, minutes] = values[index].split(":").map(Number);
      const end = hours * 60 + minutes;
      if (!Number.isFinite(end) || !Number.isFinite(Number(values[index + 1]))) {
        break;
      }
      segments.push({ end, temperature });
      temperature = Number(values[index + 1]);
    }
    segments.push({ end: DAY_MINUTES, temperature });
    schedule[dayIndex] = segments;
  }
  return schedule.every(Boolean) ? schedule : null;
}

class MaxculWeekProfileCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._schedule = makeDefaultSchedule();
    this._status = "";
    this._statusError = false;
    this._statusIcon = "";
    this._loadedProfileRequestId = null;
  }

  static getConfigElement() {
    return document.createElement("maxcul-week-profile-editor");
  }

  static getStubConfig() {
    return { type: "custom:maxcul-week-profile", device_id: "" };
  }

  setConfig(config) {
    const deviceId = String(config?.device_id || "").trim();
    if (this._config && this._config.device_id !== deviceId) {
      this._schedule = makeDefaultSchedule();
      this._loadedProfileRequestId = null;
      this._status = "";
      this._statusError = false;
    }
    this._config = {
      ...config,
      device_id: deviceId,
    };
    this._render();
    this._syncProfileFromEntity();
  }

  set hass(hass) {
    this._hass = hass;
    this._syncProfileFromEntity();
  }

  getCardSize() {
    return 8;
  }

  _isThermostatSelected() {
    return Boolean(this._config.device_id);
  }

  _selectedThermostatState() {
    if (!this._hass || !this._config.device_id) return null;
    const direct = this._hass.states[this._config.device_id];
    if (direct) return direct;

    const requestedIds = new Set([this._config.device_id.toLowerCase()]);
    if (/[a-f]/i.test(this._config.device_id)) {
      const parsedHexId = parseInt(this._config.device_id, 16);
      if (Number.isFinite(parsedHexId)) {
        requestedIds.add(String(parsedHexId));
      }
    }
    return Object.values(this._hass.states).find((state) => {
      const attributes = state.attributes || {};
      const deviceId = attributes.maxcul_device_id;
      const deviceName = attributes.maxcul_device_name;
      return (
        (deviceId !== undefined &&
          requestedIds.has(String(deviceId).toLowerCase())) ||
        (typeof deviceName === "string" &&
          deviceName.toLowerCase() === this._config.device_id.toLowerCase())
      );
    }) || null;
  }

  _syncProfileFromEntity() {
    if (!this._hass || !this._config?.device_id) return;
    const state = this._selectedThermostatState();
    if (!state) {
      this._setStatus(
        `Thermostat „${this._config.device_id}“ nicht gefunden. Bitte eine gültige MaxCUL-Thermostat-Entität auswählen.`,
        true,
        "mdi:alert-circle",
      );
      return;
    }
    const attributes = state.attributes || {};
    const profile = attributes.maxcul_week_profile;
    const requestId = attributes.maxcul_week_profile_request_id;
    if (typeof profile === "string" && profile) {
      const loadedSchedule = parseProfile(profile);
      if (!loadedSchedule) {
        this._setStatus(
          "Das gespeicherte Wochenprofil konnte nicht gelesen werden. Stelle erst deinen gewünschten Wochenplan wieder her, bevor du ihn sendest.",
          true,
          "mdi:alert-circle",
        );
        return;
      }
      const profileKey = requestId || profile;
      if (profileKey !== this._loadedProfileRequestId) {
        this._schedule = loadedSchedule;
        this._loadedProfileRequestId = profileKey;
        this._render();
      }
    } else {
      this._setStatus(
        "Kein gespeichertes Wochenprofil gefunden. Die angezeigten 20 °C sind nur Voreinstellungen. Stelle erst deinen gewünschten Wochenplan wieder her, bevor du ihn sendest.",
        false,
        "mdi:information-outline",
      );
      return;
    }

    const status = attributes.maxcul_week_profile_status;
    if (status === "acknowledged") {
      this._setStatus(
        "Plan ist beim Thermostat angekommen.",
        false,
        "mdi:check-circle",
      );
    } else if (status === "pending") {
      this._setStatus(
        "Warte auf Antwort vom Thermostat …",
        false,
        "mdi:progress-clock",
      );
    } else if (status === "failed") {
      this._setStatus(
        "Keine Antwort vom Thermostat. Prüfe, ob es eingeschaltet und in Funkreichweite ist.",
        true,
        "mdi:alert-circle",
      );
    } else {
      this._setStatus(
        "Zuletzt gesendeter Plan geladen.",
        false,
        "mdi:information-outline",
      );
    }
  }

  _render() {
    if (!this._config) return;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; font-family: var(--primary-font-family, Roboto, Arial, sans-serif); }
        ha-card { display: block; padding: 16px; color: var(--primary-text-color); }
        h2 { margin: 0 0 4px; font-size: 1.25rem; }
        .subtitle, .notice, .hint { color: var(--secondary-text-color); font-size: .9rem; }
        .notice { margin: 12px 0; padding: 10px; border-left: 3px solid var(--warning-color, #db9c20); background: var(--secondary-background-color); }
        .days { display: grid; gap: 12px; }
        .day { padding: 12px; border: 1px solid var(--divider-color); border-radius: 8px; }
        .day-header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 8px; }
        .day-header strong { font-size: 1rem; }
        .timeline-wrap { position: relative; padding-bottom: 20px; }
        .timeline { position: relative; height: 34px; display: flex; overflow: hidden; border-radius: 5px; cursor: crosshair; touch-action: manipulation; background: var(--disabled-color, #ddd); }
        .segment { display: flex; align-items: center; justify-content: center; min-width: 0; overflow: hidden; border-right: 1px solid var(--card-background-color, #fff); color: #17212b; font-size: .8rem; font-weight: 600; white-space: nowrap; }
        .hours { display: flex; justify-content: space-between; position: absolute; top: 38px; left: 0; right: 0; color: var(--secondary-text-color); font-size: .7rem; }
        .switches { display: grid; gap: 6px; margin-top: 12px; }
        .switch { display: grid; grid-template-columns: minmax(115px, 1fr) minmax(130px, 1fr) auto; align-items: center; gap: 8px; }
        label { display: flex; align-items: center; gap: 6px; color: var(--secondary-text-color); font-size: .85rem; }
        input { box-sizing: border-box; width: 100%; min-height: 38px; padding: 6px 8px; border: 1px solid var(--input-idle-line-color, var(--divider-color)); border-radius: 4px; color: var(--primary-text-color); background: var(--card-background-color); font: inherit; }
        input:focus { outline: 2px solid var(--primary-color); outline-offset: 1px; }
        button { min-height: 38px; padding: 6px 12px; border: 0; border-radius: 4px; color: var(--text-primary-color, #fff); background: var(--primary-color); font: inherit; cursor: pointer; }
        button.secondary { color: var(--primary-text-color); background: var(--secondary-background-color); }
        button.delete { width: 38px; padding: 0; color: var(--error-color, #b3261e); background: transparent; font-size: 1.2rem; }
        button:disabled { cursor: not-allowed; opacity: .55; }
        .hint { margin: 8px 0 0; }
        .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 16px; }
        .status { display: flex; flex: 1 1 100%; align-items: center; gap: 8px; min-height: 1.5em; font-size: .9rem; }
        .status ha-icon { flex: 0 0 auto; --mdc-icon-size: 22px; color: var(--primary-color); }
        .status ha-icon[hidden] { display: none; }
        .status.error ha-icon { color: var(--error-color, #b3261e); }
        .status.error { color: var(--error-color, #b3261e); }
        @media (max-width: 520px) {
          ha-card { padding: 12px; }
          .switch { grid-template-columns: 1fr 1fr 38px; gap: 5px; }
          .day { padding: 9px; }
        }
      </style>
      <ha-card>
        <h2>MAX! Wochenprofil</h2>
        <div class="subtitle">${this._config.device_id ? `Thermostat ${this._escapeText(this._config.device_id)}` : "Thermostat in den Karteneinstellungen auswählen"}</div>
        <div class="notice">Das Profil wird lokal in Home Assistant gespeichert. Das tatsächlich im Thermostat gespeicherte Profil kann nicht ausgelesen werden; angezeigt wird das zuletzt gesendete Profil. Wenn noch keines gesendet wurde, startet der Editor mit 20 °C für alle Tage.</div>
        <p class="hint">Klicke in die Zeitleiste, um einen Schaltpunkt hinzuzufügen. Zeiten lassen sich in 5-Minuten-Schritten einstellen.</p>
        <div class="days"></div>
        <div class="actions">
          <button class="save" ${this._isThermostatSelected() ? "" : "disabled"}>Wochenprofil ans Thermostat senden</button>
          <button class="secondary reset">Alle Tage auf 20 °C zurücksetzen</button>
          <div class="status" role="status" aria-live="polite">
            <ha-icon aria-hidden="true"></ha-icon>
            <span class="status-message"></span>
          </div>
        </div>
      </ha-card>
    `;

    const days = this.shadowRoot.querySelector(".days");
    this._schedule.forEach((segments, dayIndex) => {
      days.append(this._renderDay(segments, dayIndex));
    });

    this.shadowRoot.querySelector(".save").addEventListener("click", () => {
      this._sendProfile();
    });
    this.shadowRoot.querySelector(".reset").addEventListener("click", () => {
      this._schedule = makeDefaultSchedule();
      this._setStatus("");
      this._render();
    });
    this._updateStatusDisplay();
  }

  _escapeText(value) {
    const span = document.createElement("span");
    span.textContent = value;
    return span.innerHTML;
  }

  _renderDay(segments, dayIndex) {
    const section = element("section", "day");
    const header = element("div", "day-header");
    header.append(
      element("strong", "", DAYS[dayIndex][1]),
      element("span", "hint", `${segments.length} Temperaturabschnitte`),
    );

    const timelineWrap = element("div", "timeline-wrap");
    const timeline = element("div", "timeline");
    timeline.setAttribute("role", "img");
    timeline.setAttribute(
      "aria-label",
      `${DAYS[dayIndex][1]}: Zeitleiste anklicken, um einen Schaltpunkt hinzuzufügen`,
    );
    let start = 0;
    segments.forEach((segment) => {
      const bar = element("div", "segment", `${segment.temperature} °C`);
      bar.style.width = `${((segment.end - start) / DAY_MINUTES) * 100}%`;
      bar.style.backgroundColor = this._temperatureColor(segment.temperature);
      bar.title = `${formatTime(start)}–${formatTime(segment.end)}: ${segment.temperature} °C`;
      timeline.append(bar);
      start = segment.end;
    });
    timeline.addEventListener("click", (event) => {
      const rect = timeline.getBoundingClientRect();
      const rawTime = ((event.clientX - rect.left) / rect.width) * DAY_MINUTES;
      const time = Math.max(
        STEP_MINUTES,
        Math.min(
          DAY_MINUTES - STEP_MINUTES,
          Math.round(rawTime / STEP_MINUTES) * STEP_MINUTES,
        ),
      );
      this._addSwitch(dayIndex, time);
    });
    timelineWrap.append(timeline);

    const hours = element("div", "hours");
    ["00", "06", "12", "18", "24"].forEach((hour) =>
      hours.append(element("span", "", hour)),
    );
    timelineWrap.append(hours);

    const switches = element("div", "switches");
    let previousEnd = 0;
    segments.forEach((segment, segmentIndex) => {
      const row = element("div", "switch");
      const timeLabel = element("label");
      const timeText = element(
        "span",
        "",
        segmentIndex === segments.length - 1 ? "Bis" : "Ende",
      );
      const timeInput = element("input");
      const minEnd = previousEnd + STEP_MINUTES;
      const maxEnd =
        segmentIndex === segments.length - 1
          ? DAY_MINUTES - STEP_MINUTES
          : segments[segmentIndex + 1].end - STEP_MINUTES;
      timeInput.type = "time";
      timeInput.min = formatTime(minEnd);
      timeInput.max = formatTime(maxEnd);
      timeInput.step = String(STEP_MINUTES * 60);
      timeInput.value = formatTime(segment.end);
      timeInput.disabled = segmentIndex === segments.length - 1;
      timeInput.setAttribute(
        "aria-label",
        `${DAYS[dayIndex][1]}: ${timeText.textContent} ${formatTime(segment.end)}`,
      );
      timeLabel.append(timeText, timeInput);

      const temperatureLabel = element("label");
      temperatureLabel.append(element("span", "", "Temperatur"));
      const temperatureInput = element("input");
      temperatureInput.type = "number";
      temperatureInput.min = String(MIN_TEMP);
      temperatureInput.max = String(MAX_TEMP);
      temperatureInput.step = "0.5";
      temperatureInput.value = String(segment.temperature);
      temperatureInput.setAttribute(
        "aria-label",
        `${DAYS[dayIndex][1]}: Temperatur ab ${formatTime(previousEnd)}`,
      );
      temperatureLabel.append(temperatureInput);
      row.append(timeLabel, temperatureLabel);

      const deleteButton = element(
        "button",
        "delete",
        segmentIndex === 0 ? "" : "×",
      );
      deleteButton.type = "button";
      deleteButton.title = "Schaltpunkt entfernen";
      deleteButton.setAttribute("aria-label", "Schaltpunkt entfernen");
      deleteButton.disabled = segmentIndex === 0;
      deleteButton.addEventListener("click", () => {
        segments[segmentIndex - 1].end = segment.end;
        segments.splice(segmentIndex, 1);
        this._render();
      });
      row.append(deleteButton);

      timeInput.addEventListener("change", () => {
        const [hour, minute] = timeInput.value.split(":").map(Number);
        const newEnd = hour * 60 + minute;
        if (
          timeInput.value &&
          newEnd >= minEnd &&
          newEnd <= maxEnd &&
          newEnd % STEP_MINUTES === 0
        ) {
          segment.end = newEnd;
          this._render();
        }
      });
      temperatureInput.addEventListener("change", () => {
        const temperature = Number(temperatureInput.value);
        if (
          Number.isFinite(temperature) &&
          temperature >= MIN_TEMP &&
          temperature <= MAX_TEMP &&
          temperature * 2 === Math.round(temperature * 2)
        ) {
          segment.temperature = temperature;
          this._render();
        }
      });
      switches.append(row);
      previousEnd = segment.end;
    });

    section.append(header, timelineWrap, switches);
    return section;
  }

  _temperatureColor(temperature) {
    const fraction = (temperature - MIN_TEMP) / (MAX_TEMP - MIN_TEMP);
    const hue = 215 - fraction * 195;
    return `hsl(${hue}, 76%, 72%)`;
  }

  _addSwitch(dayIndex, time) {
    const segments = this._schedule[dayIndex];
    if (segments.some((segment) => segment.end === time)) return;
    if (segments.length >= 13) {
      this._setStatus("Pro Tag sind höchstens 13 Temperaturabschnitte erlaubt.", true);
      return;
    }
    const index = segments.findIndex((segment) => time < segment.end);
    if (index < 0 || time <= (index === 0 ? 0 : segments[index - 1].end)) return;
    const current = segments[index];
    const oldEnd = segments[index].end;
    current.end = time;
    segments.splice(index + 1, 0, {
      end: oldEnd,
      temperature: current.temperature,
    });
    this._setStatus("");
    this._render();
  }

  _serializeProfile() {
    return this._schedule
      .map((segments, dayIndex) => {
        const values = [];
        segments.forEach((segment, index) => {
          values.push(String(segment.temperature));
          if (index < segments.length - 1) {
            values.push(formatTime(segment.end));
          }
        });
        return `${DAYS[dayIndex][0]} ${values.join(",")}`;
      })
      .join("\n");
  }

  async _sendProfile() {
    if (!this._hass) {
      this._setStatus(
        "Home Assistant ist noch nicht verbunden.",
        true,
        "mdi:alert-circle",
      );
      return;
    }
    if (!this._config.device_id) {
      this._setStatus(
        "Bitte ein Thermostat auswählen.",
        true,
        "mdi:alert-circle",
      );
      return;
    }
    const button = this.shadowRoot.querySelector(".save");
    button.disabled = true;
    this._setStatus(
      "Plan wird gesendet …",
      false,
      "mdi:send",
    );

    const serviceData = {
      device_id: this._config.device_id,
      week_profile: this._serializeProfile(),
    };
    if (this._config.device_path) {
      serviceData.device_path = this._config.device_path;
    }

    try {
      await this._hass.callService("maxcul", "set_week_profile", serviceData);
      this._setStatus(
        "Plan abgeschickt. Warte auf Bestätigung …",
        false,
        "mdi:progress-clock",
      );
    } catch (error) {
      this._setStatus(
        `Senden fehlgeschlagen: ${error?.message || "Home-Assistant-Fehler"}`,
        true,
        "mdi:alert-circle",
      );
    } finally {
      button.disabled = false;
    }
  }

  _setStatus(message, isError = false, icon = "") {
    this._status = message;
    this._statusError = isError;
    this._statusIcon = icon || (isError ? "mdi:alert-circle" : "");
    this._updateStatusDisplay();
  }

  _updateStatusDisplay() {
    const status = this.shadowRoot.querySelector(".status");
    if (status) {
      const icon = status.querySelector("ha-icon");
      icon.setAttribute("icon", this._statusIcon);
      icon.hidden = !this._statusIcon;
      status.querySelector(".status-message").textContent = this._status;
      status.classList.toggle("error", this._statusError);
    }
  }
}

class MaxculWeekProfileCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const entityPicker = this.shadowRoot.querySelector("ha-entity-picker");
    if (entityPicker) {
      this._configureEntityPicker(entityPicker);
    }
  }

  _configureEntityPicker(entityPicker) {
    entityPicker.hass = this._hass;
    entityPicker.includeDomains = ["climate"];
    const maxculEntities = Object.entries(this._hass?.entities || {})
      .filter(
        ([entityId, entity]) =>
          entity.platform === "maxcul" && entityId.startsWith("climate."),
      )
      .map(([entityId]) => entityId);
    entityPicker.includeEntities = maxculEntities.length
      ? maxculEntities
      : undefined;
    entityPicker.value = this._config.device_id || "";
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        label { display: block; margin: 12px 0; color: var(--primary-text-color); }
        input, ha-entity-picker { box-sizing: border-box; display: block; width: 100%; min-height: 40px; margin-top: 5px; }
        p { color: var(--secondary-text-color); }
      </style>
      <p>Wähle das MaxCUL-Thermostat aus der Liste aus. Alternativ kann in YAML eine Hex-Adresse oder der Friendly Name angegeben werden.</p>
      <label>Thermostat<ha-entity-picker class="device-id"></ha-entity-picker></label>
      <label>CUL-Verbindung (optional)<input class="device-path" placeholder="/dev/ttyUSB0"></label>
    `;
    const deviceId = this.shadowRoot.querySelector(".device-id");
    const devicePath = this.shadowRoot.querySelector(".device-path");
    this._configureEntityPicker(deviceId);
    devicePath.value = this._config.device_path || "";
    deviceId.addEventListener("value-changed", (event) => {
      this._config = { ...this._config, device_id: event.detail.value || "" };
      this._dispatchConfigChanged();
    });
    devicePath.addEventListener("input", () => {
      this._config = { ...this._config, device_path: devicePath.value.trim() };
      this._dispatchConfigChanged();
    });
  }

  _dispatchConfigChanged() {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

if (!customElements.get("maxcul-week-profile")) {
  customElements.define("maxcul-week-profile", MaxculWeekProfileCard);
}
if (!customElements.get("maxcul-week-profile-editor")) {
  customElements.define(
    "maxcul-week-profile-editor",
    MaxculWeekProfileCardEditor,
  );
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "maxcul-week-profile",
  name: "MAX! Wochenprofil",
  description: "Grafischer Editor für das Wochenprofil eines MAX!-Thermostats.",
});
