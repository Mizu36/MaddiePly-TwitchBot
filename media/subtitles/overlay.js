const STATE_URL = "state.json";
const POLL_INTERVAL_MS = 120;
const SCALE_STEP = 0.92;
const MIN_SCALE = 0.1;
const DEFAULT_FONT_SIZE = 72;
const MIN_FONT_PX = 12;
const LINE_HEIGHT_RATIO = 1.18;
const TEXTBOX_SCROLL_MS = 140;
const TEXTBOX_FADE_OUT_MS = 350;
const TEXTBOX_FADE_IN_MS = 120;
const canvas = document.getElementById("subtitle-text");
const container = document.getElementById("subtitle-canvas");
const subtitleBox = document.getElementById("subtitle-box");
const body = document.body;
const STYLE_PYRAMID = "pyramid";
const STYLE_TEXTBOX = "text_box";
let latestVersion = 0;
let fetchInFlight = false;
let pendingFitFrame = null;
let currentStyle = STYLE_PYRAMID;
let textBoxLineEls = [];
let textBoxLines = ["", ""];
let textBoxLineIndex = 0;
let textBoxPendingSpace = false;
let textBoxTimeline = [];
let textBoxTimelineIndex = 0;
let textBoxStartMs = 0;
let textBoxAnimFrame = null;
let textBoxTextIndex = 0;
let textBoxSourceText = "";
let textBoxScrollInProgress = false;
let textBoxScrollBuffer = "";
let textBoxScrollPendingSpace = false;
let textBoxScrollTimeout = null;
let textBoxWordStartOffset = 0;
let measureSpan = null;
let textboxImageAvailable = false;
let textBoxVisible = false;
let textBoxFadeTimeout = null;

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
        const styleKey = normalizeStyle(data.style);
        applyStyle(styleKey);
        if (styleKey === STYLE_TEXTBOX) {
            renderTextBox(data);
        } else {
            renderLines(data.lines || []);
        }
    } catch (error) {
        console.error("Subtitle overlay fetch failed", error);
    } finally {
        fetchInFlight = false;
    }
}

function normalizeStyle(raw) {
    const val = typeof raw === "string" ? raw.trim().toLowerCase() : "";
    if (val.includes("text box")) {
        return STYLE_TEXTBOX;
    }
    return STYLE_PYRAMID;
}

function applyStyle(styleKey) {
    if (styleKey === currentStyle) {
        return;
    }
    currentStyle = styleKey;
    body.classList.toggle("text-box-mode", styleKey === STYLE_TEXTBOX);
    canvas.innerHTML = "";
    pendingFitFrame = null;
    if (styleKey === STYLE_TEXTBOX) {
        initTextBoxLines();
        resetTextBoxState();
        updateTextboxImageClass();
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

function initTextBoxLines() {
    if (!canvas) {
        return;
    }
    canvas.innerHTML = "";
    textBoxLineEls = [];
    for (let i = 0; i < 2; i += 1) {
        const line = document.createElement("div");
        line.className = "text-box-line";
        canvas.appendChild(line);
        textBoxLineEls.push(line);
    }
}

function resetTextBoxState() {
    cancelTextBoxAnimation();
    textBoxLines = ["", ""];
    textBoxLineIndex = 0;
    textBoxPendingSpace = false;
    textBoxWordStartOffset = 0;
    textBoxScrollInProgress = false;
    textBoxScrollBuffer = "";
    textBoxScrollPendingSpace = false;
    if (textBoxScrollTimeout !== null) {
        clearTimeout(textBoxScrollTimeout);
        textBoxScrollTimeout = null;
    }
    if (textBoxFadeTimeout !== null) {
        clearTimeout(textBoxFadeTimeout);
        textBoxFadeTimeout = null;
    }
    textBoxTimeline = [];
    textBoxTimelineIndex = 0;
    textBoxStartMs = 0;
    textBoxTextIndex = 0;
    textBoxSourceText = "";
    updateTextBoxLines();
}

function renderTextBox(data) {
    if (!data) {
        resetTextBoxState();
        return;
    }
    const shouldReset = Boolean(data.reset);
    const incomingText = typeof data.text === "string" ? data.text : "";
    if (shouldReset || incomingText !== textBoxSourceText) {
        resetTextBoxState();
    }
    if (data.visible === false) {
        setTextBoxVisibility(false, Boolean(data.clear));
        return;
    }
    setTextBoxVisibility(true, false);
    if (!incomingText) {
        return;
    }
    textBoxSourceText = incomingText;
    textBoxTimeline = buildTextBoxTimeline(data);
    textBoxTimelineIndex = 0;
    textBoxStartMs = performance.now();
    textBoxTextIndex = 0;
    textBoxPendingSpace = false;
    textBoxLineIndex = 0;
    textBoxLines = ["", ""];
    textBoxWordStartOffset = 0;
    updateTextBoxLines();
    scheduleTextBoxFrame();
}

function setTextBoxVisibility(visible, clearAfterFade) {
    if (!body) {
        return;
    }
    textBoxVisible = Boolean(visible);
    body.classList.toggle("textbox-visible", textBoxVisible);
    body.classList.toggle("textbox-hiding", !textBoxVisible);

    if (textBoxFadeTimeout !== null) {
        clearTimeout(textBoxFadeTimeout);
        textBoxFadeTimeout = null;
    }
    if (!textBoxVisible && clearAfterFade) {
        textBoxFadeTimeout = setTimeout(() => {
            if (!textBoxVisible) {
                resetTextBoxState();
                updateTextBoxLines();
            }
            textBoxFadeTimeout = null;
        }, TEXTBOX_FADE_OUT_MS);
    }
}

function buildTextBoxTimeline(data) {
    const timings = Array.isArray(data.character_timings) ? data.character_timings : [];
    const timeline = [];
    for (const item of timings) {
        const char = item?.char;
        if (char === undefined || char === null) {
            continue;
        }
        const start = Number(item.start || 0);
        timeline.push({ char: String(char), start: Math.max(0, start) });
    }
    timeline.sort((a, b) => a.start - b.start);

    if (timeline.length) {
        return timeline;
    }
    const text = typeof data.text === "string" ? data.text : "";
    if (!text) {
        return [];
    }
    const duration = Number(data.duration_seconds || 0);
    const totalMs = duration > 0 ? duration * 1000 : Math.max(800, text.length * 40);
    const stepMs = text.length ? totalMs / text.length : 40;
    let current = 0;
    for (const ch of text) {
        timeline.push({ char: ch, start: current / 1000 });
        current += stepMs;
    }
    return timeline;
}

function scheduleTextBoxFrame() {
    if (textBoxAnimFrame !== null) {
        cancelAnimationFrame(textBoxAnimFrame);
    }
    textBoxAnimFrame = requestAnimationFrame(runTextBoxFrame);
}

function runTextBoxFrame() {
    textBoxAnimFrame = null;
    if (!textBoxTimeline.length) {
        return;
    }
    const elapsed = (performance.now() - textBoxStartMs) / 1000;
    while (textBoxTimelineIndex < textBoxTimeline.length) {
        const entry = textBoxTimeline[textBoxTimelineIndex];
        if (entry.start > elapsed) {
            break;
        }
        appendTextBoxChar(entry.char);
        textBoxTimelineIndex += 1;
    }
    if (textBoxTimelineIndex < textBoxTimeline.length) {
        scheduleTextBoxFrame();
    }
}

function cancelTextBoxAnimation() {
    if (textBoxAnimFrame !== null) {
        cancelAnimationFrame(textBoxAnimFrame);
        textBoxAnimFrame = null;
    }
}

function appendTextBoxChar(char) {
    if (textBoxScrollInProgress) {
        appendTextBoxScrollChar(char);
        return;
    }

    if (char === "\n") {
        advanceTextBoxLine();
        textBoxPendingSpace = false;
        textBoxTextIndex += 1;
        return;
    }

    if (isWhitespace(char)) {
        textBoxPendingSpace = true;
        textBoxTextIndex += 1;
        return;
    }

    const wordStart = isWordStart();
    if (wordStart) {
        const nextWord = peekUpcomingWord();
        if (nextWord) {
            ensureWordFits(nextWord);
        }
    }

    if (textBoxScrollInProgress) {
        appendTextBoxScrollChar(char);
        return;
    }

    let lineText = textBoxLines[textBoxLineIndex] || "";
    if (textBoxPendingSpace) {
        if (lineText) {
            lineText += " ";
        }
        textBoxPendingSpace = false;
    }

    if (wordStart) {
        textBoxWordStartOffset = lineText.length;
    }

    lineText += char;
    textBoxLines[textBoxLineIndex] = lineText;
    updateTextBoxLines();
    reflowTextBoxOverflow();
    textBoxTextIndex += 1;
}

function appendTextBoxScrollChar(char) {
    if (char === "\n") {
        textBoxScrollBuffer = "";
        textBoxScrollPendingSpace = false;
        textBoxTextIndex += 1;
        return;
    }

    if (isWhitespace(char)) {
        textBoxScrollPendingSpace = true;
        textBoxTextIndex += 1;
        return;
    }

    let bufferText = textBoxScrollBuffer;
    if (textBoxScrollPendingSpace) {
        if (bufferText) {
            bufferText += " ";
        }
        textBoxScrollPendingSpace = false;
    }
    bufferText += char;
    textBoxScrollBuffer = bufferText;
    textBoxTextIndex += 1;
}

function isWhitespace(char) {
    return typeof char === "string" && char.trim() === "";
}

function isWordStart() {
    if (!textBoxSourceText) {
        return true;
    }
    if (textBoxTextIndex <= 0) {
        return true;
    }
    const prev = textBoxSourceText[textBoxTextIndex - 1];
    return prev === undefined || prev.trim() === "";
}

function peekUpcomingWord() {
    const text = textBoxSourceText || "";
    if (!text) {
        return "";
    }
    let idx = textBoxTextIndex;
    while (idx < text.length && text[idx].trim() === "") {
        idx += 1;
    }
    let word = "";
    while (idx < text.length && text[idx].trim() !== "") {
        word += text[idx];
        idx += 1;
    }
    return word;
}

function ensureWordFits(word) {
    if (!word) {
        return;
    }
    const maxWidth = getTextBoxWidth();
    if (!maxWidth) {
        return;
    }
    const current = textBoxLines[textBoxLineIndex] || "";
    const prefix = textBoxPendingSpace && current ? " " : "";
    const candidate = `${current}${prefix}${word}`;
    if (current && measureTextWidth(candidate) > maxWidth) {
        advanceTextBoxLine();
    }
}

function reflowTextBoxOverflow() {
    const maxWidth = getTextBoxWidth();
    if (!maxWidth) {
        return;
    }
    let lineText = textBoxLines[textBoxLineIndex] || "";
    if (!lineText) {
        return;
    }
    if (measureTextWidth(lineText) <= maxWidth) {
        return;
    }
    if (textBoxWordStartOffset <= 0 || textBoxWordStartOffset >= lineText.length) {
        return;
    }

    const word = lineText.slice(textBoxWordStartOffset);
    const prefix = lineText.slice(0, textBoxWordStartOffset).trimEnd();

    if (textBoxLineIndex === 0) {
        textBoxLines[0] = prefix;
        textBoxLines[1] = word;
        textBoxLineIndex = 1;
        textBoxWordStartOffset = 0;
        updateTextBoxLines();
        return;
    }

    if (textBoxScrollInProgress) {
        return;
    }

    textBoxLines[1] = prefix;
    textBoxLineIndex = 1;
    textBoxWordStartOffset = 0;
    startTextBoxScroll(word);
    updateTextBoxLines();
}

function advanceTextBoxLine() {
    if (textBoxLineIndex === 0) {
        textBoxLineIndex = 1;
        textBoxWordStartOffset = 0;
        updateTextBoxLines();
        return;
    }
    if (textBoxScrollInProgress) {
        return;
    }
    textBoxLineIndex = 1;
    textBoxWordStartOffset = 0;
    startTextBoxScroll("");
}

function startTextBoxScroll(bufferSeed) {
    if (textBoxScrollInProgress) {
        return;
    }
    textBoxScrollInProgress = true;
    textBoxScrollBuffer = bufferSeed || "";
    textBoxScrollPendingSpace = false;
    triggerTextBoxScroll(() => {
        textBoxLines[0] = textBoxLines[1];
        textBoxLines[1] = textBoxScrollBuffer;
        textBoxPendingSpace = textBoxScrollPendingSpace;
        textBoxScrollBuffer = "";
        textBoxScrollPendingSpace = false;
        textBoxScrollInProgress = false;
        updateTextBoxLines();
    });
}

function triggerTextBoxScroll(onDone) {
    if (!canvas || !textBoxLineEls.length) {
        if (typeof onDone === "function") {
            onDone();
        }
        return;
    }
    const lineHeight = textBoxLineEls[0].getBoundingClientRect().height || 0;
    if (!lineHeight) {
        if (typeof onDone === "function") {
            onDone();
        }
        return;
    }
    if (textBoxScrollTimeout !== null) {
        clearTimeout(textBoxScrollTimeout);
        textBoxScrollTimeout = null;
    }
    canvas.classList.add("textbox-scroll");
    canvas.style.transform = "translateY(0)";
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            canvas.style.transform = `translateY(-${lineHeight}px)`;
            textBoxScrollTimeout = setTimeout(() => {
                canvas.classList.remove("textbox-scroll");
                canvas.style.transform = "";
                textBoxScrollTimeout = null;
                if (typeof onDone === "function") {
                    onDone();
                }
            }, TEXTBOX_SCROLL_MS);
        });
    });
}

function updateTextBoxLines() {
    if (!textBoxLineEls.length) {
        return;
    }
    textBoxLineEls[0].textContent = textBoxLines[0] || "";
    textBoxLineEls[1].textContent = textBoxLines[1] || "";
}

function getTextBoxWidth() {
    if (!subtitleBox) {
        return 0;
    }
    const styles = window.getComputedStyle(subtitleBox);
    const paddingLeft = parseFloat(styles.paddingLeft) || 0;
    const paddingRight = parseFloat(styles.paddingRight) || 0;
    return Math.max(0, subtitleBox.clientWidth - paddingLeft - paddingRight);
}

function measureTextWidth(text) {
    if (!measureSpan) {
        measureSpan = document.createElement("span");
        measureSpan.style.position = "absolute";
        measureSpan.style.visibility = "hidden";
        measureSpan.style.whiteSpace = "pre";
        document.body.appendChild(measureSpan);
    }
    const reference = textBoxLineEls[0] || canvas;
    if (reference) {
        const styles = window.getComputedStyle(reference);
        measureSpan.style.fontFamily = styles.fontFamily;
        measureSpan.style.fontSize = styles.fontSize;
        measureSpan.style.fontWeight = styles.fontWeight;
        measureSpan.style.letterSpacing = styles.letterSpacing;
    }
    measureSpan.textContent = text;
    return measureSpan.getBoundingClientRect().width;
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

function detectTextboxImage() {
    if (!subtitleBox) {
        return;
    }
    const img = new Image();
    img.onload = () => {
        textboxImageAvailable = true;
        updateTextboxImageClass();
    };
    img.onerror = () => {
        textboxImageAvailable = false;
        updateTextboxImageClass();
    };
    img.src = `textbox.png?v=${Date.now()}`;
}

function updateTextboxImageClass() {
    if (!subtitleBox) {
        return;
    }
    subtitleBox.classList.toggle("textbox-image", textboxImageAvailable);
}

setInterval(fetchState, POLL_INTERVAL_MS);
detectTextboxImage();
fetchState();
