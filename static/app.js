const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const dropTitle = document.querySelector("#drop-title");
const dropHint = document.querySelector("#drop-hint");
const scanButton = document.querySelector("#scan-button");
const scanResult = document.querySelector("#scan-result");

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function renderPorts(ports) {
  const list = document.querySelector("#ports-list");
  if (!ports.length) {
    list.innerHTML = '<tr><td colspan="3" class="empty-row">No listening ports detected</td></tr>';
    return;
  }
  list.innerHTML = ports.map((port) => `
    <tr>
      <td><span class="port-number">:${port.port}</span><span class="port-address">${escapeHtml(port.address)}</span></td>
      <td class="process-name">${escapeHtml(port.process)}</td>
      <td><span class="status-pill ${port.authorized ? "status-ok" : "status-review"}"><i></i>${port.authorized ? "Allowed" : "Review"}</span></td>
    </tr>`).join("");
}

function renderHistory(scans) {
  const history = document.querySelector("#scan-history");
  if (!scans.length) {
    history.innerHTML = '<tr><td colspan="5" class="empty-row">No files scanned yet</td></tr>';
    return;
  }
  history.innerHTML = scans.map((scan) => `
    <tr>
      <td class="file-name">${escapeHtml(scan.filename)}</td>
      <td><span class="status-pill ${scan.status === "clear" ? "status-ok" : "status-review"}"><i></i>${scan.status === "clear" ? "Clear" : "Review"}</span></td>
      <td class="findings-cell">${scan.findings.length ? escapeHtml(scan.findings.join(" · ")) : "—"}</td>
      <td><code class="hash-value" title="${escapeHtml(scan.sha256)}">${escapeHtml(scan.sha256.slice(0, 12))}…</code></td>
      <td class="time-cell">${new Date(scan.scanned_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
    </tr>`).join("");
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("Status unavailable");
    const status = await response.json();
    document.querySelector("#files-count").textContent = status.scan_count;
    document.querySelector("#flagged-count").textContent = status.flagged_count;
    document.querySelector("#ports-count").textContent = status.ports.length;
    document.querySelector("#unauthorized-count").textContent = status.unauthorized_ports;
    document.querySelector("#ports-foot").textContent = `${status.ports.length} listening on this device`;
    document.querySelector("#allowlist-values").textContent = status.allowed_ports.map((port) => `:${port}`).join("   ") || "None configured";
    document.querySelector("#checked-at").textContent = `Last checked ${new Date(status.checked_at).toLocaleTimeString()}`;
    renderPorts(status.ports);
    renderHistory(status.scans);
  } catch (_error) {
    document.querySelector("#checked-at").textContent = "Could not reach local monitor";
  }
}

function setSelectedFile(file) {
  if (!file) return;
  dropTitle.textContent = file.name;
  dropHint.textContent = `${(file.size / 1024).toFixed(1)} KiB · ready to inspect`;
  dropZone.classList.add("has-file");
}

fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0]));
for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
}
dropZone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  setSelectedFile(file);
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileInput.files[0]) return;
  scanButton.disabled = true;
  scanButton.querySelector("span:first-child").textContent = "Scanning…";
  scanResult.hidden = true;
  const body = new FormData(uploadForm);
  try {
    const response = await fetch("/api/scan", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Scan failed");
    const clear = result.status === "clear";
    scanResult.className = `scan-result ${clear ? "result-clear" : "result-review"}`;
    scanResult.innerHTML = `<div class="result-title"><span>${clear ? "✓" : "!"}</span><strong>${clear ? "No known indicators found" : "File needs review"}</strong></div><p>${clear ? "No matching patterns were detected by the local rules." : result.findings.map(escapeHtml).join(" · ")}</p><code>SHA-256&nbsp; ${escapeHtml(result.sha256)}</code>`;
    scanResult.hidden = false;
    refreshStatus();
  } catch (error) {
    scanResult.className = "scan-result result-review";
    scanResult.textContent = error.message;
    scanResult.hidden = false;
  } finally {
    scanButton.disabled = false;
    scanButton.querySelector("span:first-child").textContent = "Scan file";
  }
});

function updateClock() {
  document.querySelector("#local-clock").textContent = new Date().toLocaleTimeString();
}

updateClock();
refreshStatus();
setInterval(updateClock, 1000);
setInterval(refreshStatus, 5000);