"""Staged PCB trace-to-component graph hypotheses.

PRISM supplies an optional trace proposal mask. This module adds independent
line evidence, pad candidates, Zhang-Suen thinning, package-edge pin priors,
geometric matching, and uncertainty-ranked graph edges.
"""
from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from typing import Iterable

import cv2
import numpy as np


def zhang_suen(mask: np.ndarray) -> np.ndarray:
    """Thin a binary mask to one-pixel ridges with Zhang-Suen subiterations."""
    image = (mask > 0).astype(np.uint8)
    if not np.any(image):
        return image * 255
    h, w = image.shape
    padded = np.pad(image, 1)
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            p2 = padded[:-2, 1:-1]
            p3 = padded[:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, :-2]
            p8 = padded[1:-1, :-2]
            p9 = padded[:-2, :-2]
            center = padded[1:-1, 1:-1]
            neighbors = (p2, p3, p4, p5, p6, p7, p8, p9)
            total = sum(neighbors)
            transitions = sum(((neighbors[i] == 0) & (neighbors[(i + 1) % 8] == 1)).astype(np.uint8)
                              for i in range(8))
            if phase == 0:
                m1 = p2 * p4 * p6
                m2 = p4 * p6 * p8
            else:
                m1 = p2 * p4 * p8
                m2 = p2 * p6 * p8
            remove = (center == 1) & (total >= 2) & (total <= 6) & (transitions == 1) & (m1 == 0) & (m2 == 0)
            if np.any(remove):
                padded[1:-1, 1:-1][remove] = 0
                changed = True
    return (padded[1:-1, 1:-1] * 255).astype(np.uint8)


def _component_body_mask(shape: tuple[int, int], detections: list[dict]) -> np.ndarray:
    h, w = shape
    mask = np.zeros((h, w), np.uint8)
    for d in detections:
        box = d.get("bbox_xyxy")
        if not box:
            continue
        x0, y0, x1, y1 = [int(round(float(v))) for v in box]
        bw, bh = x1 - x0, y1 - y0
        inset = max(2, int(round(min(bw, bh) * 0.12)))
        if bw * bh > h * w * 0.012:
            inset = max(2, int(round(min(bw, bh) * 0.07)))
        cv2.rectangle(mask, (max(0, x0 + inset), max(0, y0 + inset)),
                      (min(w - 1, x1 - inset), min(h - 1, y1 - inset)), 255, -1)
    return mask


def detect_pad_candidates(image: np.ndarray, detections: list[dict]) -> tuple[list[dict], np.ndarray]:
    """Find reflective pad/via-like blobs with scale-aware morphology checks."""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    value, sat = hsv[:, :, 2], hsv[:, :, 1]
    bright_metal = ((value >= 155) & (sat <= 105)).astype(np.uint8) * 255
    warm_metal = ((hsv[:, :, 0] <= 30) & (sat >= 45) & (value >= 100)).astype(np.uint8) * 255
    binary = cv2.bitwise_or(bright_metal, warm_metal)
    k = max(3, int(round(min(h, w) * 0.004)))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max(5.0, h * w * 0.000008)
    max_area = max(min_area + 1, h * w * 0.003)
    pads: list[dict] = []
    pad_mask = np.zeros((h, w), np.uint8)
    boxes = [d.get("bbox_xyxy") for d in detections if d.get("bbox_xyxy")]
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not min_area <= area <= max_area:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < 2 or bh < 2:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        circularity = 4 * math.pi * area / (perimeter * perimeter + 1e-6)
        aspect = min(bw, bh) / max(bw, bh)
        if circularity < 0.12 and aspect < 0.28:
            continue
        cx, cy = x + bw / 2, y + bh / 2
        # Avoid component-body glare; edge leads are left available as anchors.
        if any(b[0] + (b[2] - b[0]) * 0.10 < cx < b[2] - (b[2] - b[0]) * 0.10 and
               b[1] + (b[3] - b[1]) * 0.10 < cy < b[3] - (b[3] - b[1]) * 0.10 for b in boxes):
            continue
        confidence = min(0.95, 0.35 + 0.35 * min(1, circularity) + 0.25 * aspect)
        index = len(pads) + 1
        pads.append({"id": index, "xy": [round(cx, 1), round(cy, 1)],
                     "bbox_xyxy": [x, y, x + bw, y + bh], "area_px": round(area, 1),
                     "circularity": round(circularity, 3), "confidence": round(confidence, 3)})
        cv2.drawContours(pad_mask, [contour], -1, 255, -1)
    pads.sort(key=lambda p: p["confidence"], reverse=True)
    for index, pad in enumerate(pads, 1):
        pad["id"] = index
    return pads, pad_mask


def _pin_priors(detections: list[dict]) -> list[dict]:
    """Create low-confidence package-edge terminal priors, not asserted pins."""
    priors = []
    for comp_i, d in enumerate(detections):
        box = d.get("bbox_xyxy")
        if not box:
            continue
        x0, y0, x1, y1 = [float(v) for v in box]
        bw, bh = x1 - x0, y1 - y0
        if bw < 5 or bh < 5:
            continue
        label = str(d.get("class_name", "component")).lower()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        pts = []
        if label in {"ic", "connector", "display"}:
            for side, length in (("top", bw), ("bottom", bw), ("left", bh), ("right", bh)):
                n = max(3, min(32, int(round(length / max(5.0, min(bw, bh) * 0.13)))) )
                for j in range(n):
                    t = (j + 0.5) / n
                    if side == "top": p, direction = [x0 + t * bw, y0], [0, -1]
                    elif side == "bottom": p, direction = [x0 + t * bw, y1], [0, 1]
                    elif side == "left": p, direction = [x0, y0 + t * bh], [-1, 0]
                    else: p, direction = [x1, y0 + t * bh], [1, 0]
                    pts.append((p, direction, side))
        else:
            # Two-terminal package prior at opposite ends of the long axis.
            if bw >= bh:
                pts = [([x0, cy], [-1, 0], "left"), ([x1, cy], [1, 0], "right")]
            else:
                pts = [([cx, y0], [0, -1], "top"), ([cx, y1], [0, 1], "bottom")]
        for point, direction, side in pts:
            priors.append({"id": len(priors) + 1, "component_index": comp_i,
                           "component": label, "xy": [round(point[0], 1), round(point[1], 1)],
                           "direction_xy": direction, "side": side,
                           "confidence": 0.25 if label in {"ic", "connector", "display"} else 0.18,
                           "prior_type": "package_edge_estimate"})
    return priors


def _thin_endpoints(skeleton: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    neighbors = cv2.filter2D((skeleton > 0).astype(np.uint8), -1,
                             np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT)
    degree = neighbors - (skeleton > 0).astype(np.uint8)
    ys, xs = np.where((skeleton > 0) & (degree == 1))
    endpoints = list(zip(xs.tolist(), ys.tolist()))
    ys, xs = np.where((skeleton > 0) & (degree >= 3))
    junctions = list(zip(xs.tolist(), ys.tolist()))
    return endpoints, junctions


def run_trace_graph_pipeline(image: np.ndarray, detections: list[dict], prism_mask: np.ndarray | None = None):
    """Run staged trace/pad detection and emit an uncertainty-aware component graph."""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # PRISM multi-filter output is one vote. Local multi-angle black-hat and
    # color/contrast evidence provide independent supporting votes.
    if prism_mask is None or prism_mask.size == 0:
        prism_vote = np.zeros((h, w), np.uint8)
    else:
        prism_vote = cv2.resize(prism_mask, (w, h), interpolation=cv2.INTER_NEAREST)
        prism_vote = (prism_vote > 0).astype(np.uint8) * 255
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    line_response = np.zeros((h, w), np.uint8)
    for length in (7, 11, 15, 21):
        for angle in (0, 30, 60, 90, 120, 150):
            size = length if length % 2 else length + 1
            kernel = np.zeros((size, size), np.uint8)
            c, r = size // 2, size // 2 - 1
            a = math.radians(angle)
            cv2.line(kernel, (c - round(r * math.cos(a)), c - round(r * math.sin(a))),
                     (c + round(r * math.cos(a)), c + round(r * math.sin(a))), 1, 1)
            line_response = cv2.max(line_response,
                cv2.morphologyEx(enhanced, cv2.MORPH_BLACKHAT, kernel))
    threshold, _ = cv2.threshold(line_response, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    line_vote = (line_response >= max(7, threshold)).astype(np.uint8) * 255
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    conductive_color = (((hue <= 30) & (sat >= 35) & (val >= 65)) |
                        ((sat <= 75) & (val >= 145))).astype(np.uint8) * 255
    voting_score = (0.50 * (prism_vote > 0).astype(np.float32) +
                    0.40 * (line_vote > 0).astype(np.float32) +
                    0.10 * (conductive_color > 0).astype(np.float32))
    trace_mask = (voting_score >= 0.40).astype(np.uint8) * 255

    pads, pad_mask = detect_pad_candidates(image, detections)
    # Pads stay as graph anchors and are removed from the trace body before thinning.
    pad_exclusion = cv2.dilate(pad_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), 1)
    body_mask = _component_body_mask((h, w), detections)
    trace_mask[pad_exclusion > 0] = 0
    trace_mask[body_mask > 0] = 0
    trace_mask = cv2.morphologyEx(trace_mask, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), 1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(trace_mask, 8)
    min_area = max(6, int(round(min(h, w) * 0.012)))
    clean = np.zeros_like(trace_mask)
    for label_id in range(1, n):
        if stats[label_id, cv2.CC_STAT_AREA] >= min_area:
            clean[labels == label_id] = 255
    skeleton = zhang_suen(clean)
    endpoints, junctions = _thin_endpoints(skeleton)
    priors = _pin_priors(detections)

    # Assign each low-confidence package prior to at most one nearby pad.
    matches = []
    used_pads: set[int] = set()
    for prior in priors:
        px, py = prior["xy"]
        choices = []
        for pad in pads:
            if pad["id"] in used_pads:
                continue
            qx, qy = pad["xy"]
            distance = math.hypot(px - qx, py - qy)
            tolerance = max(8.0, min(h, w) * 0.025)
            if distance <= tolerance:
                # Combine proximity, the expected lead direction, and pad morphology.
                dx, dy = qx - px, qy - py
                norm = max(1e-6, math.hypot(dx, dy))
                direction = prior["direction_xy"]
                direction_score = max(0.0, min(1.0, (dx * direction[0] + dy * direction[1]) / norm))
                score = (0.50 * math.exp(-distance / max(1.0, tolerance * 0.55)) +
                         0.30 * direction_score + 0.20 * pad["confidence"])
                choices.append((score, pad, distance))
        if choices:
            score, pad, distance = max(choices, key=lambda item: item[0])
            used_pads.add(pad["id"])
            matches.append({"prior_id": prior["id"], "pad_id": pad["id"],
                            "component_index": prior["component_index"],
                            "distance_px": round(distance, 1), "match_score": round(score, 3)})

    # Treat each retained centerline component as a possible path edge between pads.
    n_skel, skel_labels, skel_stats, _ = cv2.connectedComponentsWithStats(skeleton, 8)
    max_pad_gap = max(5.0, min(h, w) * 0.012)
    graph_nodes = [{"id": f"pad_{p['id']}", "kind": "pad", "xy": p["xy"],
                    "confidence": p["confidence"]} for p in pads]
    graph_nodes += [{"id": f"pinprior_{p['id']}", "kind": "pin_prior",
                    "component_index": p["component_index"], "component": p["component"],
                    "xy": p["xy"], "confidence": p["confidence"]} for p in priors]
    graph_nodes += [{"id": f"component_{i+1}", "kind": "component",
                     "label": str(d.get("class_name", "component")),
                     "bbox_xyxy": d.get("bbox_xyxy"), "confidence": d.get("confidence", 0.0)}
                    for i, d in enumerate(detections)]
    graph_edges = []
    for match in matches:
        graph_edges.append({"id": len(graph_edges)+1, "from": f"pinprior_{match['prior_id']}",
                            "to": f"pad_{match['pad_id']}", "rank_score": round(match["match_score"] * 100, 1),
                            "uncertainty": round(1.0 - match["match_score"], 3),
                            "evidence": match["match_score"], "centerline_pixels": 0,
                            "points": [], "method": "geometric_pin_pad_match"})
    for label_id in range(1, n_skel):
        if skel_stats[label_id, cv2.CC_STAT_AREA] < 5:
            continue
        ys, xs = np.where(skel_labels == label_id)
        if not len(xs):
            continue
        indices = []
        for pad in pads:
            x, y = pad["xy"]
            d2 = (xs - x) ** 2 + (ys - y) ** 2
            if float(np.min(d2)) <= max_pad_gap ** 2:
                indices.append((pad["id"], int(np.argmin(d2))))
        if len(indices) < 2:
            continue
        # Keep only the two most separated pad anchors on a given trace fragment.
        pairs = []
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                pa, pb = pads[indices[a][0]-1], pads[indices[b][0]-1]
                pairs.append((math.hypot(pa["xy"][0]-pb["xy"][0], pa["xy"][1]-pb["xy"][1]), indices[a], indices[b]))
        _, left, right = max(pairs, key=lambda p: p[0])
        pad_a, pad_b = pads[left[0]-1], pads[right[0]-1]
        points = [[int(x), int(y)] for x, y in zip(xs.tolist(), ys.tolist())]
        density = float(np.mean(voting_score[ys, xs]))
        size_penalty = 0.12 if len(indices) > 4 else 0.0
        rank = max(0.0, min(100.0, 100 * (0.55 * density + 0.25 * (pad_a["confidence"] + pad_b["confidence"]) / 2 + 0.20) - size_penalty * 100))
        graph_edges.append({"id": len(graph_edges)+1, "from": f"pad_{pad_a['id']}",
                            "to": f"pad_{pad_b['id']}", "points": points,
                            "rank_score": round(rank, 1), "evidence": round(density, 3),
                            "uncertainty": round(1.0 - rank / 100.0, 3),
                            "centerline_pixels": len(points), "method": "pad_centerline_match"})

    graph_backend = "adjacency-list"
    try:
        import networkx as nx
        graph = nx.Graph()
        for node in graph_nodes:
            graph.add_node(node["id"], **node)
        for edge in graph_edges:
            graph.add_edge(edge["from"], edge["to"], **edge)
        graph_backend = "NetworkX"
        graph_nodes = [{"id": node, **attrs} for node, attrs in graph.nodes(data=True)]
        graph_edges = [{k: v for k, v in attrs.items() if k not in {"from", "to"}} |
                       {"from": a, "to": b} for a, b, attrs in graph.edges(data=True)]
    except ImportError:
        pass

    diagnostics = {"stages": ["PRISM/line/color multi-filter voting", "morphological pad candidates",
                              "pad exclusion", "Zhang-Suen centerline", "package-edge pin priors",
                              "distance/geometric pad matching", "uncertainty-ranked graph"],
                   "mask_pixels": int(cv2.countNonZero(clean)), "centerline_pixels": int(cv2.countNonZero(skeleton)),
                   "pad_candidates": len(pads), "pin_priors": len(priors), "pin_pad_matches": len(matches),
                   "endpoints": len(endpoints), "junctions": len(junctions),
                   "graph_nodes": len(graph_nodes), "graph_edges": len(graph_edges),
                   "graph_backend": graph_backend,
                   "note": "박스 기반 예상 핀은 낮은 신뢰도의 단서입니다. rank_score는 보정된 연결 확률이 아닙니다."}

    mask_overlay = image.copy()
    mask_overlay[clean > 0] = (0.55 * mask_overlay[clean > 0] + 0.45 * np.array([30, 220, 255])).astype(np.uint8)
    center_overlay = image.copy()
    center_overlay[cv2.dilate(skeleton, np.ones((3, 3), np.uint8)) > 0] = (20, 40, 255)
    pad_overlay = image.copy()
    for pad in pads:
        x, y = map(lambda v: int(round(v)), pad["xy"])
        cv2.circle(pad_overlay, (x, y), 4, (30, 235, 90), 1, cv2.LINE_AA)
    for prior in priors:
        x, y = map(lambda v: int(round(v)), prior["xy"])
        cv2.circle(pad_overlay, (x, y), 2, (255, 190, 20), -1, cv2.LINE_AA)
    graph_overlay = image.copy()
    for edge in graph_edges:
        pts = edge.get("points", [])
        if len(pts) > 1:
            cv2.polylines(graph_overlay, [np.asarray(pts, np.int32).reshape((-1, 1, 2))], False,
                          (255, 40, 220), 2, cv2.LINE_AA)
            x, y = pts[len(pts)//2]
            cv2.putText(graph_overlay, f"{edge['id']}:{edge.get('rank_score', 0)}", (x+2, y-2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 40, 220), 1, cv2.LINE_AA)
    for pad in pads:
        x, y = map(lambda v: int(round(v)), pad["xy"])
        cv2.circle(graph_overlay, (x, y), 3, (30, 235, 90), -1, cv2.LINE_AA)

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["edge_id", "from_node", "to_node", "rank_score", "uncertainty", "evidence", "centerline_pixels", "points_xy_json"])
    import json
    for edge in graph_edges:
        writer.writerow([edge.get("id"), edge.get("from"), edge.get("to"), edge.get("rank_score"),
                         edge.get("uncertainty"), edge.get("evidence"), edge.get("centerline_pixels"),
                         json.dumps(edge.get("points", []), separators=(",", ":"))])
    return {"mask": clean, "skeleton": skeleton, "pads": pads, "pin_priors": priors,
            "matches": matches, "nodes": graph_nodes, "edges": graph_edges,
            "diagnostics": diagnostics, "mask_overlay": mask_overlay,
            "pad_overlay": pad_overlay, "centerline_overlay": center_overlay, "graph_overlay": graph_overlay,
            "csv": csv_buffer.getvalue()}
