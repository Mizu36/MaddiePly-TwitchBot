const STATE_URL = "state.json";
const POLL_INTERVAL_MS = 120;
const SCALE_STEP = 0.92;
const MIN_SCALE = 0.1;
const DEFAULT_FONT_SIZE = 72;
const MIN_FONT_PX = 12;
const LINE_HEIGHT_RATIO = 1.18;
const canvas = document.getElementById("subtitle-text");
const container = document.getElementById("subtitle-canvas");
let latestVersion = 0;
let fetchInFlight = false;
let pendingFitFrame = null;

async function fetchState() {
    if (fetchInFlight) {
        return;
    }
    fetchInFlight = true;
    try {
        const response = await fetch(`${STATE_URL}?v=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        if (!data || typeof data.version === "undefined") {
            return;
        }
        if (data.version === latestVersion) {
            return;
        }
        latestVersion = data.version;
        renderLines(data.lines || []);
    } catch (error) {
        console.error("Subtitle overlay fetch failed", error);
    } finally {
        fetchInFlight = false;
    }
}

function renderLines(lines) {
    canvas.innerHTML = "";
    if (!Array.isArray(lines) || !lines.length) {
        return;
    }
    const fragment = document.createDocumentFragment();
    const heightCap = computeHeightCap(lines.length);
    const uniformBase = determineUniformBaseSize(lines, heightCap);
    for (const line of lines) {
        const div = document.createElement("div");
        div.className = "subtitle-line";
        div.dataset.baseSize = `${uniformBase}`;
        div.style.fontSize = `${uniformBase}px`;
        div.textContent = line?.text ?? "";
        fragment.appendChild(div);
    }
    canvas.appendChild(fragment);
    fitTextToCanvas();
    schedulePostLayoutFit();
}

function determineUniformBaseSize(lines, heightCap) {
    let base = DEFAULT_FONT_SIZE;
    for (const line of lines) {
        const size = typeof line?.fontSize === "number" ? line.fontSize : DEFAULT_FONT_SIZE;
        base = Math.min(base, size);
    }
    if (typeof heightCap === "number" && heightCap > 0) {
        base = Math.min(base, heightCap);
    }
    return Math.max(MIN_FONT_PX, base);
}

function applyScale(scale) {
    const nodes = canvas.querySelectorAll(".subtitle-line");
    nodes.forEach((node) => {
        const base = parseFloat(node.dataset.baseSize) || DEFAULT_FONT_SIZE;
        const size = Math.max(MIN_FONT_PX, base * scale);
        node.style.fontSize = `${size}px`;
    });
}

function computeHeightCap(lineCount) {
    if (!container || !lineCount) {
        return null;
    }
    const availableHeight = getAvailableHeight(container);
    if (availableHeight <= 0) {
        return null;
    }
    const perLine = availableHeight / (lineCount * LINE_HEIGHT_RATIO);
    if (!Number.isFinite(perLine) || perLine <= 0) {
        return null;
    }
    return Math.floor(perLine);
}

function getAvailableHeight(element) {
    const styles = window.getComputedStyle(element);
    const paddingTop = parseFloat(styles.paddingTop) || 0;
    const paddingBottom = parseFloat(styles.paddingBottom) || 0;
    return Math.max(0, element.clientHeight - paddingTop - paddingBottom);
}

function getAvailableWidth(element) {
    const styles = window.getComputedStyle(element);
    const paddingLeft = parseFloat(styles.paddingLeft) || 0;
    const paddingRight = parseFloat(styles.paddingRight) || 0;
    return Math.max(0, element.clientWidth - paddingLeft - paddingRight);
}

function fitTextToCanvas() {
    if (!canvas.firstChild || !container) {
        return;
    }
    let scale = 1;
    applyScale(scale);
    const maxHeight = getAvailableHeight(container) || container.clientHeight;
    if (maxHeight <= 0) {
        return;
    }
    for (let i = 0; i < 40; i += 1) {
        const overflowHeight = canvas.scrollHeight > maxHeight;
        if (!overflowHeight) {
            break;
        }
        const nextScale = Math.max(MIN_SCALE, scale * SCALE_STEP);
        if (nextScale === scale) {
            break;
        }
        scale = nextScale;
        applyScale(scale);
    }
    const overflowHeight = canvas.scrollHeight > maxHeight;
    if (overflowHeight) {
        const heightRatio = maxHeight / Math.max(1, canvas.scrollHeight);
        const ratio = Math.max(0.05, heightRatio);
        applyScale(scale * ratio);
    }
}

function schedulePostLayoutFit() {
    if (pendingFitFrame !== null) {
        cancelAnimationFrame(pendingFitFrame);
    }
    pendingFitFrame = requestAnimationFrame(() => {
        pendingFitFrame = null;
        fitTextToCanvas();
    });
}

setInterval(fetchState, POLL_INTERVAL_MS);
fetchState();
