const NS = "http://www.w3.org/2000/svg";
const instances = new WeakMap();

function make(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

export default function(component) {
  const { parentElement, data, setStateValue } = component;
  const root = parentElement.querySelector("[data-schematic-viewer]");
  const viewport = root.querySelector("[data-viewport]");
  const page = root.querySelector("[data-page]");
  const camera = root.querySelector("[data-camera]");
  const image = root.querySelector("[data-schematic-image]");
  const hitLayer = root.querySelector("[data-hit-regions]");
  const selectionLayer = root.querySelector("[data-selection-overlay]");
  const zoomLabel = root.querySelector("[data-zoom-label]");
  const geometryLabel = root.querySelector("[data-geometry-label]");
  const empty = root.querySelector("[data-empty]");
  let state = instances.get(root);
  if (!state) {
    state = { scale: 1, x: 0, y: 0, pageKey: "", assetKey: "", objectUrl: "", selected: null, navigationId: null, drag: null, pointer: null, listeners: [], observer: null, eventCounter: 0 };
    instances.set(root, state);
  }
  state.eventCounter = Math.max(state.eventCounter, Number(data.event_sequence_seed) || 0);
  state.sendSelection = (region) => {
    state.eventCounter += 1;
    setStateValue("selection", {
      component_ref: region.component_ref,
      symbol_uuid: region.symbol_uuid,
      sheet_path: region.sheet_path,
      unit: region.unit,
      context_key: data.context_key,
      asset_key: data.asset_key,
      event_seq: state.eventCounter,
      event_id: `${Date.now()}-${state.eventCounter}`,
    });
  };
  state.data = data;
  const listen = (target, event, handler, options) => {
    target.addEventListener(event, handler, options);
    state.listeners.push(() => target.removeEventListener(event, handler, options));
  };
  const svgPoint = (clientX, clientY) => {
    const p = page.createSVGPoint(); p.x = clientX; p.y = clientY;
    return p.matrixTransform(page.getScreenCTM().inverse());
  };
  const renderCamera = () => {
    camera.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`);
    zoomLabel.textContent = `${Math.round(state.scale * 100)}%`;
  };
  const fit = () => { state.scale = 1; state.x = 0; state.y = 0; renderCamera(); };
  const zoomAt = (factor, point) => {
    const scale = Math.min(8, Math.max(0.25, state.scale * factor));
    const ratio = scale / state.scale;
    state.x = point.x - (point.x - state.x) * ratio;
    state.y = point.y - (point.y - state.y) * ratio;
    state.scale = scale; renderCamera();
  };
  const centerOn = (ref) => {
    const region = (data.regions || []).find((r) => r.component_ref === ref);
    if (!region) return;
    const points = region.polygon;
    const cx = points.reduce((sum, p) => sum + p[0], 0) / points.length;
    const cy = points.reduce((sum, p) => sum + p[1], 0) / points.length;
    const vb = data.view_box;
    state.x = vb[0] + vb[2] / 2 - cx * state.scale;
    state.y = vb[1] + vb[3] / 2 - cy * state.scale;
    renderCamera();
  };
  const buildRegions = () => {
    hitLayer.replaceChildren(); selectionLayer.replaceChildren();
    for (const [index, region] of (data.regions || []).entries()) {
      const shape = make("polygon", { points: region.polygon.map((p) => p.join(",")).join(" "),
        class: "cc-hit-region", "data-region-index": index, tabindex: "0", role: "button", "aria-label": `부품 ${region.component_ref} 선택` });
      hitLayer.appendChild(shape);
    }
    const selected = (data.regions || []).filter((r) => r.component_ref === data.selected_ref);
    for (const region of selected) {
      selectionLayer.appendChild(make("polygon", { points: region.polygon.map((p) => p.join(",")).join(" "), class: "cc-highlight" }));
    }
  };
  const setAsset = () => {
    const vb = data.view_box;
    if (!vb || !data.svg) {
      empty.hidden = false; page.hidden = true; return;
    }
    empty.hidden = true; page.hidden = false;
    page.setAttribute("viewBox", `${vb[0]} ${vb[1]} ${vb[2]} ${vb[3]}`);
    image.setAttribute("x", vb[0]); image.setAttribute("y", vb[1]);
    image.setAttribute("width", vb[2]); image.setAttribute("height", vb[3]);
    if (state.assetKey !== data.asset_key || !state.objectUrl) {
      if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
      state.objectUrl = URL.createObjectURL(new Blob([data.svg], { type: "image/svg+xml" }));
      image.setAttribute("href", state.objectUrl);
      const newPage = state.assetKey !== data.asset_key;
      state.assetKey = data.asset_key;
      state.pageKey = data.asset_key;
      if (newPage) fit();
    }
    if (state.navigationId !== data.navigation_id) {
      state.navigationId = data.navigation_id;
      if (data.navigation_ref) centerOn(data.navigation_ref);
    }
  };
  const onWheel = (event) => {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, svgPoint(event.clientX, event.clientY));
  };
  const onPointerDown = (event) => {
    if (event.button !== 0 || event.target.closest(".cc-hit-region")) return;
    const point = svgPoint(event.clientX, event.clientY);
    state.drag = { pointerId: event.pointerId, x: point.x, y: point.y, tx: state.x, ty: state.y };
    viewport.setPointerCapture(event.pointerId); viewport.dataset.dragging = "true";
  };
  const onPointerMove = (event) => {
    if (!state.drag || state.drag.pointerId !== event.pointerId) return;
    const point = svgPoint(event.clientX, event.clientY);
    state.x = state.drag.tx + point.x - state.drag.x;
    state.y = state.drag.ty + point.y - state.drag.y;
    renderCamera();
  };
  const endDrag = (event) => {
    if (event?.pointerId !== undefined && state.drag && state.drag.pointerId !== event.pointerId) return;
    state.drag = null; viewport.dataset.dragging = "false";
  };
  if (state.listeners.length === 0) {
    listen(viewport, "wheel", onWheel, { passive: false });
    listen(viewport, "pointerdown", onPointerDown);
    listen(viewport, "pointermove", onPointerMove);
    listen(viewport, "pointerup", endDrag);
    listen(viewport, "pointercancel", endDrag);
    listen(viewport, "lostpointercapture", endDrag);
    listen(window, "blur", endDrag);
    listen(window, "pagehide", endDrag);
    listen(hitLayer, "click", (event) => {
      const shape = event.target.closest("[data-region-index]");
      if (!shape) return;
      event.stopPropagation();
      const region = state.data.regions?.[Number(shape.dataset.regionIndex)];
      if (region) state.sendSelection(region);
    });
    listen(hitLayer, "keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const shape = event.target.closest("[data-region-index]");
      if (!shape) return;
      event.preventDefault();
      const region = state.data.regions?.[Number(shape.dataset.regionIndex)];
      if (region) state.sendSelection(region);
    });
    for (const button of root.querySelectorAll("[data-action]")) listen(button, "click", () => {
      const action = button.dataset.action;
      if (action === "fit" || action === "reset") fit();
      else if (action === "zoom-in" || action === "zoom-out") {
        const rect = page.getBoundingClientRect();
        zoomAt(action === "zoom-in" ? 1.25 : 0.8, svgPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
      }
    });
    state.observer = new ResizeObserver(() => { if (state.scale === 1 && state.x === 0 && state.y === 0) fit(); });
    state.observer.observe(viewport);
  }
  if (state.pageKey !== data.asset_key) setAsset(); else setAsset();
  geometryLabel.textContent = data.geometry_status === "VERIFIED_GEOMETRY" ? "심벌 선택 · 검증됨" : `심벌 선택 · ${data.geometry_status}`;
  if (state.selected !== data.selected_ref || state.assetKey !== data.asset_key) {
    state.selected = data.selected_ref;
    buildRegions();
  } else {
    // Rebuilding keeps the Python → canvas highlight synchronized after a rerun.
    buildRegions();
  }
  renderCamera();
  return () => {
    for (const remove of state.listeners.splice(0)) remove();
    state.observer?.disconnect();
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = "";
  };
}
