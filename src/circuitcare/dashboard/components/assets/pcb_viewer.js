const SVG_NS = "http://www.w3.org/2000/svg";
const MIN_SCALE = 1 / 1.2;
const MAX_SCALE = 4;
const instances = new WeakMap();

function svgElement(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

export default function(component) {
  const { parentElement, data, setStateValue } = component;
  const root = parentElement.querySelector("[data-pcb-viewer]");
  const viewport = root.querySelector("[data-viewport]");
  const canvas = root.querySelector("[data-canvas]");
  const camera = root.querySelector("[data-camera]");
  const image = root.querySelector("[data-board-image]");
  const layer = root.querySelector("[data-component-layer]");
  const tooltip = root.querySelector("[data-tooltip]");
  const empty = root.querySelector("[data-empty]");
  const zoomLabel = root.querySelector("[data-zoom-label]");
  let state = instances.get(root);
  if (!state) {
    state = { scale:1, x:0, y:0, assetKey:"", hover:null,
      listeners:[], observer:null, sequence:0, mountedAssetKey:"" };
    instances.set(root, state);
  }
  state.data = data;
  state.setStateValue = setStateValue;
  state.sequence = Math.max(state.sequence, Number(data.event_sequence_seed) || 0);
  const listen = (target, event, callback, options) => {
    target.addEventListener(event, callback, options);
    state.listeners.push(() => target.removeEventListener(event, callback, options));
  };
  const point = (clientX, clientY) => {
    const p = canvas.createSVGPoint(); p.x = clientX; p.y = clientY;
    return p.matrixTransform(canvas.getScreenCTM().inverse());
  };
  const hitComponent = (event) => {
    const p = point(event.clientX, event.clientY);
    const x = (p.x - state.x) / state.scale;
    const y = (p.y - state.y) / state.scale;
    return (state.data.components || []).filter((item) => {
      const [x1, y1, x2, y2] = item.bbox_xyxy;
      return x >= x1 && x <= x2 && y >= y1 && y <= y2;
    }).sort((a, b) => {
      const aSelected = a.component_id === state.data.selected_component_id;
      const bSelected = b.component_id === state.data.selected_component_id;
      if (aSelected !== bSelected) return aSelected ? -1 : 1;
      const aArea = (a.bbox_xyxy[2] - a.bbox_xyxy[0]) * (a.bbox_xyxy[3] - a.bbox_xyxy[1]);
      const bArea = (b.bbox_xyxy[2] - b.bbox_xyxy[0]) * (b.bbox_xyxy[3] - b.bbox_xyxy[1]);
      return aArea - bArea || a.component_id.localeCompare(b.component_id);
    })[0] || null;
  };
  const drawCamera = () => {
    camera.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`);
    zoomLabel.textContent = `${Math.round(state.scale * 100)}%`;
  };
  const fit = () => {
    const [width, height] = data.image_size_px;
    if (!width || !height || !viewport.clientWidth || !viewport.clientHeight) return;
    // SVG preserveAspectRatio performs centered fitting once for both image and vector layer.
    state.scale = 1; state.x = 0; state.y = 0; drawCamera();
  };
  const zoomAt = (factor) => {
    const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, state.scale * factor));
    const [width, height] = state.data.image_size_px;
    state.x = width * (1 - scale) / 2;
    state.y = height * (1 - scale) / 2;
    state.scale = scale; drawCamera();
  };
  const sendSelection = (componentId) => {
    // The visible box ID is the source of truth for inspector selection.
    state.setStateValue("selection", componentId || "__clear__");
  };
  const renderRegions = () => {
    layer.replaceChildren();
    const fragment = document.createDocumentFragment();
    for (const item of data.components || []) {
      const [x1,y1,x2,y2] = item.bbox_xyxy;
      const statusClasses = {
        SUSPECTED: "cc-fault-suspected", TEST_ABNORMAL: "cc-fault-abnormal",
        TEST_NORMAL: "cc-fault-normal", INCONCLUSIVE: "cc-fault-undetermined",
        CONFLICTED: "cc-fault-undetermined",
      };
      const legacyClasses = {
        SUSPECTED_FAULT: "cc-fault-suspected", CONFIRMED_FAULT: "cc-fault-abnormal",
        RELATED_COMPONENT: "cc-fault-related",
      };
      const diagnosisClass = statusClasses[item.fault_candidate_status]
        || legacyClasses[item.fault_candidate_status] || "";
      const shape = svgElement("rect", { x:x1, y:y1, width:x2-x1, height:y2-y1,
        class:`cc-pcb-component ${diagnosisClass}${item.component_id === data.selected_component_id ? " cc-selected" : ""}`,
        "data-component-id":item.component_id, tabindex:"0", role:"button",
        "aria-label":`${item.display_label || item.component_type} 부품 선택${item.diagnosis_display_status ? `, ${item.diagnosis_display_status}` : ""}` });
      fragment.appendChild(shape);
      if (item.display_label) {
        const label = svgElement("text", { x:(x1+x2)/2, y:Math.max(12,y1-4), class:"cc-pcb-label" });
        label.textContent = item.display_label; fragment.appendChild(label);
      }
    }
    layer.appendChild(fragment);
  };
  const setImage = () => {
    const [width,height] = data.image_size_px || [];
    if (!data.image_png_base64 || !width || !height) { empty.hidden=false; return; }
    empty.hidden=true;
    canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
    image.setAttribute("x","0"); image.setAttribute("y","0");
    image.setAttribute("width",String(width)); image.setAttribute("height",String(height));
    const key = `${data.asset_key}|${data.project_id}|${data.board_id}|${data.board_side}|${data.frame_id}`;
    const reportReady = () => {
      if (state.assetKey !== key || state.mountedAssetKey === key) return;
      const [expectedWidth, expectedHeight] = data.image_size_px;
      if (!image.isConnected || image.width.baseVal.value !== expectedWidth
          || image.height.baseVal.value !== expectedHeight) return;
      state.mountedAssetKey=key;
      setStateValue("viewer_status", { asset_key:key, status:"READY",
        image_size_px:[expectedWidth,expectedHeight], event_id:`ready-${Date.now()}` });
    };
    if (state.assetKey !== key) {
      state.assetKey=key;
      state.hover=null; tooltip.hidden=true;
      state.mountedAssetKey="";
      image.addEventListener("load", reportReady, { once:true });
      image.setAttribute("href", `data:image/png;base64,${data.image_png_base64}`);
      fit();
    }
    if (state.mountedAssetKey !== key) {
      if (typeof image.decode === "function") image.decode().then(reportReady).catch(() => {});
      if (image.complete) reportReady();
    }
  };
  if (state.listeners.length === 0) {
    listen(viewport,"wheel",(event)=>{ event.preventDefault(); zoomAt(event.deltaY<0?1.12:1/1.12); },{passive:false});
    listen(viewport,"pointermove",(event)=>{
      const hit=hitComponent(event);
      const id=hit?.component_id || null;
      if (id!==state.hover) {
        state.hover=id;
        for (const shape of layer.querySelectorAll("[data-component-id]")) shape.classList.toggle("cc-hover",shape.dataset.componentId===id);
      }
      tooltip.hidden=true;
    });
    listen(viewport,"pointerleave",()=>{ tooltip.hidden=true; state.hover=null; });
    // Select from the actual SVG box target. This avoids a second hit-test whose
    // coordinate math can drift when the responsive SVG letterboxes the image.
    listen(layer,"click",(event)=>{
      const shape=event.target.closest("[data-component-id]");
      if (!shape || !layer.contains(shape)) return;
      event.preventDefault();
      event.stopPropagation();
      sendSelection(shape.dataset.componentId);
    });
    listen(viewport,"click",(event)=>{
      if (event.target.closest("[data-component-id]")) return;
      sendSelection(null);
    });
    listen(layer,"keydown",(event)=>{ if(event.key!=="Enter"&&event.key!==" ")return; const shape=event.target.closest("[data-component-id]"); if(!shape)return; event.preventDefault(); sendSelection(shape.dataset.componentId); });
    for(const button of root.querySelectorAll("[data-action]")) listen(button,"click",()=>{
      const action=button.dataset.action; if(action==="clear-selection")sendSelection(null);
      else if(action==="fit"||action==="reset")fit();
      else zoomAt(action==="zoom-in"?1.25:1/1.25);
    });
    state.observer=new ResizeObserver(()=>{
      tooltip.hidden=true; state.hover=null;
      fit();
    }); state.observer.observe(viewport);
  }
  setImage(); renderRegions(); drawCamera();
  return ()=>{ for(const remove of state.listeners.splice(0))remove(); state.observer?.disconnect(); };
}
