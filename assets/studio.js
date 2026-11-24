/* Packet Tracer export workflow and topology metadata. */
(() => {
  "use strict";

  const SUPPORTED_TYPES = new Set(["pc", "laptop", "router", "switch"]);
  const ROUTER_MODELS = ["2911", "2811"];
  const PORTS = {
    router: {
      "2911": ["g0/0", "g0/1", "g0/2"],
      "2811": ["fa0/0", "fa0/1"]
    },
    switch: Array.from({length: 24}, (_, i) => `fa0/${i + 1}`),
    host: ["fa0"]
  };

  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  let toastTimer;

  function notify(message, kind = "info") {
    const toast = byId("studio-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.className = `studio-toast visible ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 3200);
  }

  function defaultModel(device) {
    if (device.type === "router") return "2911";
    if (device.type === "switch") return "2960-24TT";
    return "PC-PT";
  }

  function getRouterPortName(device, index) {
    const options = PORTS.router[device?.model] || PORTS.router["2911"];
    return options[index] || "";
  }
  window.getRouterPortName = getRouterPortName;

  function portChoices(device) {
    if (!device) return [];
    if (device.type === "router") return PORTS.router[device.model] || PORTS.router["2911"];
    if (device.type === "switch") return PORTS.switch;
    if (["pc", "laptop"].includes(device.type)) return PORTS.host;
    return [];
  }

  function getPortForDevice(deviceId, connection) {
    if (!connection) return "";
    if (connection.from === deviceId) return connection.fromPort || "";
    if (connection.to === deviceId) return connection.toPort || "";
    return "";
  }
  window.getPortForDevice = getPortForDevice;

  function portUsed(deviceId, port, ignoreConnectionId) {
    return networkState.connections.some((connection) =>
      connection.id !== ignoreConnectionId &&
      ((connection.from === deviceId && connection.fromPort === port) ||
       (connection.to === deviceId && connection.toPort === port))
    );
  }

  function firstFreePort(device, connectionId) {
    const choices = portChoices(device);
    return choices.find((port) => !portUsed(device.id, port, connectionId)) || "";
  }

  function ensureRouterInterface(device, port) {
    if (!device || device.type !== "router" || !port) return;
    device.interfaces = Array.isArray(device.interfaces) ? device.interfaces : [];
    const basePort = port.toLowerCase();
    const existing = device.interfaces.some((iface) => {
      const name = String(iface.name || "").toLowerCase().split(".")[0];
      return name === basePort;
    });
    if (!existing) {
      const index = device.interfaces.length;
      device.interfaces.push({
        id: `${device.id}_int${index}`, ip: "", cidr: 24, name: basePort, vlan: null
      });
    }
  }

  function assignConnectionPorts(connection) {
    const from = networkState.devices.find((device) => device.id === connection.from);
    const to = networkState.devices.find((device) => device.id === connection.to);
    if (!from || !to) return false;
    from.model ||= defaultModel(from);
    to.model ||= defaultModel(to);

    connection.fromPort ||= firstFreePort(from, connection.id);
    connection.toPort ||= firstFreePort(to, connection.id);
    if (from.type === "router") ensureRouterInterface(from, connection.fromPort);
    if (to.type === "router") ensureRouterInterface(to, connection.toPort);
    return Boolean(connection.fromPort && connection.toPort);
  }
  window.assignConnectionPorts = assignConnectionPorts;

  function hydrateConnectionPorts() {
    if (!Array.isArray(networkState.devices) || !Array.isArray(networkState.connections)) return;
    networkState.devices.forEach((device) => {
      device.model ||= defaultModel(device);
      if (device.type === "router") {
        device.interfaces = Array.isArray(device.interfaces) ? device.interfaces : [];
        device.interfaces.forEach((iface) => {
          iface.name = String(iface.name || "g0/0").toLowerCase();
          const legacyPort = iface.name.match(/^eth(\d+)$/);
          if (legacyPort) {
            iface.name = getRouterPortName(device, Number(legacyPort[1])) || iface.name;
          }
        });
        if (!device.interfaces.length) {
          device.interfaces.push({
            id: `${device.id}_int0`, ip: "", cidr: 24,
            name: getRouterPortName(device, 0), vlan: null
          });
        }
      }
    });
    networkState.connections.forEach((connection, index) => {
      connection.id ||= `conn_imported_${index + 1}`;
      if (connection.fromPort) connection.fromPort = String(connection.fromPort).toLowerCase();
      if (connection.toPort) connection.toPort = String(connection.toPort).toLowerCase();
      assignConnectionPorts(connection);
    });
    networkState.devices
      .filter((device) => device.type === "router")
      .forEach((device) => device.interfaces.forEach((iface) => {
        const base = String(iface.name || "").toLowerCase().split(".")[0];
        iface.name = base + (iface.vlan ? `.${iface.vlan}` : "");
      }));
  }
  window.hydrateConnectionPorts = hydrateConnectionPorts;

  function getAvailablePortOptions(device, connection) {
    if (!device) return [];
    const current = getPortForDevice(device.id, connection);
    const options = portChoices(device).filter((port) =>
      port === current || !portUsed(device.id, port, connection.id)
    );
    if (current && !options.includes(current)) options.unshift(current);
    return options.length ? options : (current ? [current] : []);
  }
  window.getAvailablePortOptions = getAvailablePortOptions;

  function updateConnectionPort(deviceId, connectionId, nextPort) {
    const connection = networkState.connections.find((item) => item.id === connectionId);
    const device = networkState.devices.find((item) => item.id === deviceId);
    if (!connection || !device || !portChoices(device).includes(nextPort)) return;

    if (portUsed(deviceId, nextPort, connectionId)) {
      notify(`${nextPort} đã được sử dụng trên ${device.name}.`, "error");
      if (typeof updateConfigPanel === "function") updateConfigPanel();
      return;
    }
    if (connection.from === deviceId) connection.fromPort = nextPort;
    else if (connection.to === deviceId) connection.toPort = nextPort;
    if (device.type === "router") ensureRouterInterface(device, nextPort);

    renderConnections();
    if (typeof updateConfigPanel === "function") updateConfigPanel();
    notify(`Đã gán ${nextPort} cho kết nối.`, "success");
  }
  window.updateConnectionPort = updateConnectionPort;

  function switchModelLabel(device) {
    if (device.type === "router") return `Cisco ${device.model || "2911"}`;
    if (device.type === "switch") return "Switch mặc định · pktlib";
    if (["pc", "laptop"].includes(device.type)) return "PC-PT";
    return "Chưa hỗ trợ xuất .pkt";
  }

  function updateModelCard() {
    const card = byId("pkt-model-card");
    const select = byId("router-model");
    const field = byId("router-model-field");
    const description = byId("pkt-model-description");
    if (!card || !networkState) return;

    const device = networkState.devices.find((item) => item.id === networkState.selectedDevice);
    if (!device) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    if (device.type === "router") {
      field.classList.remove("hidden");
      select.value = device.model || "2911";
      description.textContent = "Cổng router được chọn tự động theo model. Muốn đổi cổng switch, mở cấu hình VLAN của switch.";
    } else {
      field.classList.add("hidden");
      description.textContent = `Model xuất: ${switchModelLabel(device)}. ${SUPPORTED_TYPES.has(device.type) ? "Có thể đưa vào file Packet Tracer." : "Hãy thay bằng PC, Router hoặc Switch để xuất."}`;
    }
  }

  function remapRouterPorts(device, model) {
    device.model = model;
    const connections = networkState.connections.filter((connection) =>
      connection.from === device.id || connection.to === device.id
    );
    const choices = portChoices(device);
    const oldInterfaces = Array.isArray(device.interfaces) ? device.interfaces : [];
    const savedByIndex = oldInterfaces.filter((iface) =>
      iface.vlan || String(iface.name || "").includes(".")
    );
    const physicalInterfaces = oldInterfaces.filter((iface) =>
      !iface.vlan && !String(iface.name || "").includes(".")
    );
    connections.forEach((connection, index) => {
      const port = choices[index];
      if (!port) return;
      if (connection.from === device.id) connection.fromPort = port;
      if (connection.to === device.id) connection.toPort = port;
    });
    device.interfaces = choices.map((port, index) => {
      const prior = physicalInterfaces[index] || {};
      return {
        id: prior.id || `${device.id}_int${index}`,
        ip: prior.ip || "",
        cidr: prior.cidr || 24,
        name: port,
        vlan: prior.vlan || null
      };
    });
    device.interfaces.push(...savedByIndex);
    hydrateConnectionPorts();
    renderConnections();
    renderRouterInterfaces(device);
    updateModelCard();
  }

  function modelDisplay(type, model) {
    if (type === "router") return `Cisco ${model || "2911"}`;
    if (type === "switch") return "Switch";
    if (type === "pc" || type === "laptop") return "PC-PT";
    return "Không hỗ trợ";
  }

  function preflight() {
    hydrateConnectionPorts();
    const devices = networkState.devices || [];
    const connections = networkState.connections || [];
    const deviceById = new Map(devices.map((device) => [device.id, device]));
    const errors = [];
    const warnings = [];
    const rows = [];

    byId("export-device-count").textContent = String(devices.length);
    byId("export-link-count").textContent = String(connections.length);

    if (!devices.length) errors.push("Sơ đồ chưa có thiết bị.");
    const names = new Set();
    for (const device of devices) {
      const name = String(device.name || "").trim();
      if (!SUPPORTED_TYPES.has(device.type)) {
        errors.push(`${name || device.type}: loại thiết bị này chưa được hỗ trợ khi xuất.`);
      }
      if (!/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(name)) {
        errors.push(`Tên “${name || "chưa đặt"}” cần bắt đầu bằng chữ và chỉ dùng chữ, số, gạch ngang hoặc gạch dưới.`);
      }
      const normalizedName = name.toLowerCase();
      if (names.has(normalizedName)) errors.push(`Tên thiết bị “${name}” bị trùng.`);
      names.add(normalizedName);

      const exportedModel = modelDisplay(device.type, device.model);
      const ip = device.config?.ip || "";
      if (["pc", "laptop"].includes(device.type) && !ip) warnings.push(`${name}: chưa đặt IP.`);
      rows.push({
        name,
        mapping: exportedModel,
        status: SUPPORTED_TYPES.has(device.type) ? "Sẵn sàng" : "Không hỗ trợ",
        ok: SUPPORTED_TYPES.has(device.type)
      });
    }

    const portUse = new Set();
    for (const connection of connections) {
      const from = deviceById.get(connection.from);
      const to = deviceById.get(connection.to);
      if (!from || !to) {
        errors.push("Có kết nối trỏ tới thiết bị không còn tồn tại.");
        continue;
      }
      if (!connection.fromPort || !connection.toPort) {
        errors.push(`Không tìm được cổng cho kết nối ${from.name} ↔ ${to.name}.`);
      }
      for (const [device, port] of [[from, connection.fromPort], [to, connection.toPort]]) {
        if (port && !portChoices(device).includes(String(port).toLowerCase())) {
          errors.push(`${device.name}: cổng ${port} không phù hợp với model hiện tại.`);
        }
        const key = `${device.id}:${port}`;
        if (port && portUse.has(key)) errors.push(`${device.name} dùng trùng cổng ${port}.`);
        if (port) portUse.add(key);
      }
      rows.push({
        name: `${from.name} (${connection.fromPort || "?"}) ↔ ${to.name} (${connection.toPort || "?"})`,
        mapping: "Cáp tự chọn",
        status: "Sẵn sàng",
        ok: Boolean(connection.fromPort && connection.toPort)
      });
    }

    byId("export-ready-count").textContent = String(devices.filter((device) => SUPPORTED_TYPES.has(device.type)).length);
    byId("export-preview-rows").innerHTML = rows.map((row) => `
      <tr>
       <td>${escapeHtml(row.name)}</td>
       <td>${escapeHtml(row.mapping)}</td>
       <td><span class="inline-flex rounded-full px-2 py-1 ${row.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}">${escapeHtml(row.status)}</span></td>
      </tr>`).join("");

    const alert = byId("export-alert");
    if (errors.length) {
      alert.className = "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800";
      alert.innerHTML = `<strong>Cần chỉnh ${errors.length} mục</strong><ul class="mt-2 list-disc space-y-1 pl-5">${errors.map(escapeHtml).map((item) => `<li>${item}</li>`).join("")}</ul>`;
    } else if (warnings.length) {
      alert.className = "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900";
      alert.innerHTML = `<strong>Sơ đồ có thể xuất.</strong><div class="mt-1">${warnings.map(escapeHtml).join(" · ")}</div>`;
    } else {
      alert.className = "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800";
      alert.textContent = "Sơ đồ đã sẵn sàng. Cổng vật lý được gán tự động và cáp sẽ do pktlib chọn.";
    }
    byId("export-confirm").disabled = errors.length > 0;
    return { ok: errors.length === 0, errors, warnings };
  }

  function openExportDialog() {
    const modal = byId("export-modal");
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    preflight();
    setTimeout(() => byId("export-close")?.focus(), 0);
  }

  function closeExportDialog() {
    if (byId("export-confirm").dataset.busy === "true") return;
    const modal = byId("export-modal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    byId("btn-export-pkt")?.focus();
  }

  function setExportBusy(busy) {
    const button = byId("export-confirm");
    button.dataset.busy = busy ? "true" : "false";
    button.disabled = busy;
    byId("export-spinner").classList.toggle("hidden", !busy);
    byId("export-button-label").textContent = busy ? "Đang tạo file…" : "Tạo file .pkt";
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function exportPkt() {
    const check = preflight();
    if (!check.ok) return;
    const baseName = (byId("export-filename").value || "topology")
      .trim().replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48) || "topology";
    const payload = {
      name: baseName,
      devices: networkState.devices,
      connections: networkState.connections,
      firewallRules: networkState.firewallRules || []
    };
    setExportBusy(true);
    try {
      const response = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        let message = "Không tạo được file .pkt.";
        try {
          const data = await response.json();
          message = data.error || message;
        } catch (_) { /* response may not be JSON */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      if (!blob.size) throw new Error("Máy chủ trả về file rỗng.");
      downloadBlob(blob, `${baseName}.pkt`);
      byId("export-alert").className = "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800";
      byId("export-alert").textContent = `Đã tạo ${baseName}.pkt. Mở tệp bằng Cisco Packet Tracer để tiếp tục.`;
      notify(`Đã tải ${baseName}.pkt`, "success");
    } catch (error) {
      byId("export-alert").className = "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800";
      byId("export-alert").textContent = error.message;
      notify(error.message, "error");
    } finally {
      setExportBusy(false);
    }
  }

  function localizePrimaryControls() {
    const replacements = [
      ["#device-palette + p", "Kéo thiết bị vào sơ đồ"],
      ["#app > .flex-1.flex.overflow-hidden > aside:first-child h2", "Thiết bị"],
      ['[data-tab="device"]', "Thiết bị"],
      ['[data-tab="firewall"]', "ACL"],
      ['[data-tab="info"]', "Thông tin"],
      ["#btn-connect", "Nối thiết bị"],
      ["#btn-delete", "Xóa"],
      ["#btn-trace", "Mô phỏng"],
      ["#status-text", "Sẵn sàng"]
    ];
    for (const [selector, value] of replacements) {
      const element = document.querySelector(selector);
      if (element) {
        if (selector.startsWith("#") && element.tagName === "BUTTON") {
          const svg = element.querySelector("svg");
          element.textContent = "";
          if (svg) element.appendChild(svg);
          element.append(document.createTextNode(` ${value} `));
        } else {
          element.textContent = value;
        }
      }
    }
    const paletteHeading = byId("device-palette")?.parentElement?.previousElementSibling;
    if (paletteHeading) {
      const description = paletteHeading.querySelector("p");
      if (description) description.textContent = "Kéo thiết bị vào sơ đồ";
    }
    const help = document.querySelector("#no-selection p");
    if (help) help.textContent = "Chọn thiết bị trên sơ đồ để xem cấu hình.";
  }

  function installModelPanel() {
    const prior = window.updateConfigPanel;
    if (typeof prior === "function" && !prior.__studioWrapped) {
      const wrapped = function(...args) {
        const result = prior.apply(this, args);
        updateModelCard();
        return result;
      };
      wrapped.__studioWrapped = true;
      window.updateConfigPanel = wrapped;
    }
    const selector = byId("router-model");
    selector?.addEventListener("change", () => {
      const device = networkState.devices.find((item) => item.id === networkState.selectedDevice);
      if (device?.type === "router" && ROUTER_MODELS.includes(selector.value)) {
        remapRouterPorts(device, selector.value);
        notify(`${device.name} đang dùng Cisco ${selector.value}.`, "success");
      }
    });

    // Apply network fields as soon as a user finishes editing them.
    ["device-name", "ip-address", "subnet-mask", "default-gateway", "dns-server"].forEach((id) => {
      byId(id)?.addEventListener("change", () => {
        if (networkState.selectedDevice && typeof applyConfiguration === "function") applyConfiguration();
      });
    });
    updateModelCard();
  }

  function initStudio() {
    hydrateConnectionPorts();
    localizePrimaryControls();
    installModelPanel();

    byId("btn-export-pkt")?.addEventListener("click", openExportDialog);
    byId("export-close")?.addEventListener("click", closeExportDialog);
    byId("export-cancel")?.addEventListener("click", closeExportDialog);
    byId("export-confirm")?.addEventListener("click", exportPkt);
    document.querySelectorAll("[data-export-close]").forEach((element) =>
      element.addEventListener("click", closeExportDialog)
    );
    byId("export-modal")?.addEventListener("click", (event) => {
      if (event.target === byId("export-modal")) closeExportDialog();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !byId("export-modal").classList.contains("hidden")) closeExportDialog();
    });
  }

  document.addEventListener("DOMContentLoaded", initStudio);
})();

