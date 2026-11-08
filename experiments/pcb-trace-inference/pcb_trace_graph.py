"""Staged PCB trace-to-component graph hypotheses.

PRISM supplies an optional trace proposal mask. This module adds independent
line evidence, pad candidates, Zhang-Suen thinning, package-edge pin priors,
geometric matching, and uncertainty-ranked graph edges.
"""
from __future__ import annotations

import csv
import io
import math
import re
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
    """Create package-count-constrained priors; never invent IC pins from class alone."""
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
        footprint = str(d.get("footprint") or d.get("package") or "").lower()
        package_layout = str(d.get("package_layout") or "").lower()
        raw_pin_count = d.get("pin_count")
        pin_count = int(raw_pin_count) if isinstance(raw_pin_count, (int, float)) and raw_pin_count > 0 else None
        if label == "ic":
            if not pin_count:
                match = re.search(r"(?:soic|tssop|ssop|dip|qfp|lqfp|qfn)[-_ ]?(\d{1,3})", footprint)
                pin_count = int(match.group(1)) if match else None
            if pin_count and pin_count <= 128:
                if any(token in footprint for token in ("qfp", "lqfp", "qfn")):
                    sides = ("top", "bottom", "left", "right")
                    side_counts = [pin_count // 4] * 4
                    for side_index in range(pin_count % 4):
                        side_counts[side_index] += 1
                elif any(token in footprint for token in ("soic", "tssop", "ssop", "dip")):
                    sides = ("left", "right") if bw >= bh else ("top", "bottom")
                    side_counts = [pin_count // 2] * 2
                    for side_index in range(pin_count % 2):
                        side_counts[side_index] += 1
                else:
                    side_counts, sides = [], ()
                if sides and sum(side_counts) == pin_count and all(side_counts):
                    for side, per_side in zip(sides, side_counts):
                        length = bw if side in {"top", "bottom"} else bh
                        for j in range(per_side):
                            t = (j + 0.5) / per_side
                            if side == "top": p, direction = [x0 + t * bw, y0], [0, -1]
                            elif side == "bottom": p, direction = [x0 + t * bw, y1], [0, 1]
                            elif side == "left": p, direction = [x0, y0 + t * bh], [-1, 0]
                            else: p, direction = [x1, y0 + t * bh], [1, 0]
                            pts.append((p, direction, side))
        elif label == "connector":
            if not pin_count:
                match = re.search(r"(?:1x|2x|pinheader[-_ ]?)(\d{1,3})", footprint)
                pin_count = int(match.group(1)) if match else None
            if pin_count and pin_count <= 128 and package_layout in {"single_row", "dual_row"}:
                # Emit exactly the declared count on a single inferred exit face.
                side = str(d.get("pin_side") or ("bottom" if bw >= bh else "right")).lower()
                if side not in {"top", "bottom", "left", "right"}:
                    side = "bottom" if bw >= bh else "right"
                direction = {"top": [0, -1], "bottom": [0, 1],
                             "left": [-1, 0], "right": [1, 0]}[side]
                horizontal = side in {"top", "bottom"}
                rows = 1 if package_layout == "single_row" else 2
                counts = [pin_count // rows] * rows
                for row in range(pin_count % rows):
                    counts[row] += 1
                for row_index, row_count in enumerate(counts):
                    offset = 0.0 if rows == 1 else ((row_index + 0.5) / rows - 0.5) * (bh if horizontal else bw) * 0.35
                    for j in range(row_count):
                        t = (j + 0.5) / row_count
                        if side == "top": p = [x0 + t * bw, y0 + abs(offset)]
                        elif side == "bottom": p = [x0 + t * bw, y1 - abs(offset)]
                        elif side == "left": p = [x0 + abs(offset), y0 + t * bh]
                        else: p = [x1 - abs(offset), y0 + t * bh]
                        pts.append((p, direction, f"{side}_row_{row_index+1}"))
        elif label in {"resistor", "capacitor", "inductor", "diode", "led", "fuse",
                       "ferrite_bead", "emi_filter", "mov", "thermistor", "potentiometer"}:
            # Two-terminal package prior at opposite ends of the long axis.
            if bw >= bh:
                pts = [([x0, cy], [-1, 0], "left"), ([x1, cy], [1, 0], "right")]
            else:
                pts = [([cx, y0], [0, -1], "top"), ([cx, y1], [0, 1], "bottom")]
        else:
            # No pin count/footprint template is available for this class.
            # Emit no fictitious individual pins.
            continue
        for point, direction, side in pts:
            priors.append({"id": len(priors) + 1, "component_index": comp_i,
                           "component": label, "xy": [round(point[0], 1), round(point[1], 1)],
                           "direction_xy": direction, "side": side,
                           "confidence": 0.25 if label in {"ic", "connector", "display"} else 0.18,
                           "pin_count_template": pin_count,
                           "prior_type": "package_template_estimate"})
    return priors


def _hungarian_assignment(cost: np.ndarray) -> list[tuple[int, int]]:
    """Minimum-cost rectangular assignment (Kuhn-Munkres potentials form)."""
    matrix = np.asarray(cost, dtype=np.float64)
    if matrix.ndim != 2 or matrix.size == 0:
        return []
    if matrix.shape[0] > matrix.shape[1]:
        pairs = _hungarian_assignment(matrix.T)
        return [(column, row) for row, column in pairs]
    rows, cols = matrix.shape
    u = np.zeros(rows + 1)
    v = np.zeros(cols + 1)
    p = np.zeros(cols + 1, dtype=np.int32)
    way = np.zeros(cols + 1, dtype=np.int32)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv = np.full(cols + 1, np.inf)
        used = np.zeros(cols + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = np.inf, 0
            for j in range(1, cols + 1):
                if used[j]:
                    continue
                cur = matrix[i0 - 1, j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return [(int(p[j] - 1), j - 1) for j in range(1, cols + 1) if p[j] != 0]


def _thin_endpoints(skeleton: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    neighbors = cv2.filter2D((skeleton > 0).astype(np.uint8), -1,
                             np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT)
    degree = neighbors - (skeleton > 0).astype(np.uint8)
    ys, xs = np.where((skeleton > 0) & (degree == 1))
    endpoints = list(zip(xs.tolist(), ys.tolist()))
    ys, xs = np.where((skeleton > 0) & (degree >= 3))
    junctions = list(zip(xs.tolist(), ys.tolist()))
    return endpoints, junctions


def _ordered_skeleton_chains(component_mask: np.ndarray) -> list[list[list[int]]]:
    """Walk 8-neighbor centerline adjacency into ordered, non-zigzag polylines."""
    ys, xs = np.where(component_mask > 0)
    pixels = {(int(x), int(y)) for x, y in zip(xs, ys)}
    if not pixels:
        return []
    adjacency: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in pixels:
        neighbors = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                point = (x + dx, y + dy)
                if point not in pixels:
                    continue
                # Avoid diagonal shortcuts when an orthogonal pixel already
                # represents the same local route connection.
                if dx and dy and ((x + dx, y) in pixels or (x, y + dy) in pixels):
                    continue
                neighbors.append(point)
        adjacency[(x, y)] = neighbors

    def edge(a: tuple[int, int], b: tuple[int, int]):
        return (a, b) if a < b else (b, a)

    remaining = {edge(point, neighbor) for point, neighbors in adjacency.items() for neighbor in neighbors}
    chains: list[list[list[int]]] = []
    starts = sorted(point for point in pixels if len(adjacency[point]) != 2)
    for start in starts:
        if not adjacency[start]:
            chains.append([[start[0], start[1]]])
        for neighbor in adjacency[start]:
            if edge(start, neighbor) not in remaining:
                continue
            chain = [start, neighbor]
            remaining.remove(edge(start, neighbor))
            previous, current = start, neighbor
            while len(adjacency[current]) == 2:
                following = next((point for point in adjacency[current] if point != previous), None)
                if following is None or edge(current, following) not in remaining:
                    break
                remaining.remove(edge(current, following))
                chain.append(following)
                previous, current = current, following
            chains.append([[x, y] for x, y in chain])
    while remaining:
        start, neighbor = min(remaining)
        chain = [start, neighbor]
        remaining.remove(edge(start, neighbor))
        previous, current = start, neighbor
        while True:
            following = next((point for point in adjacency[current]
                              if point != previous and edge(current, point) in remaining), None)
            if following is None:
                break
            remaining.remove(edge(current, following))
            chain.append(following)
            previous, current = current, following
        chains.append([[x, y] for x, y in chain])
    return chains


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
    voting_score = (0.45 * (prism_vote > 0).astype(np.float32) +
                    0.40 * (line_vote > 0).astype(np.float32) +
                    0.15 * (conductive_color > 0).astype(np.float32))
    # A single filter can no longer pass by itself: any two independent votes
    # exceed 0.50; color evidence is a weak corroborating vote.
    trace_mask = (voting_score >= 0.50).astype(np.uint8) * 255

    pads, pad_mask = detect_pad_candidates(image, detections)
    # Record which pre-suppression trace regions touch each pad. Pad interiors
    # are removed before thinning, but this contact ledger preserves endpoints.
    _, original_labels, _, _ = cv2.connectedComponentsWithStats(trace_mask, 8)
    pad_contact_labels: dict[int, set[int]] = {}
    for pad in pads:
        px, py = [int(round(value)) for value in pad["xy"]]
        radius = max(3, int(round(max(pad["bbox_xyxy"][2] - pad["bbox_xyxy"][0],
                                      pad["bbox_xyxy"][3] - pad["bbox_xyxy"][1]) / 2)) + 4)
        x0, x1 = max(0, px-radius), min(w, px+radius+1)
        y0, y1 = max(0, py-radius), min(h, py+radius+1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (xx-px) ** 2 + (yy-py) ** 2 <= radius ** 2
        touched = set(int(value) for value in np.unique(original_labels[y0:y1, x0:x1][disk]) if value > 0)
        pad_contact_labels[pad["id"]] = touched
        pad["pre_suppression_trace_regions"] = sorted(touched)
    # Pads remain graph anchors and are suppressed only from the centerline mask.
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

    # Global one-to-one assignment prevents iteration order from consuming the
    # best pad for an earlier, weaker pin prior.
    matches = []
    match_scores: dict[tuple[int, int], tuple[float, float]] = {}
    if priors and pads:
        unmatched_cost = 0.52
        invalid_cost = 10.0
        cost = np.full((len(priors), len(pads) + len(priors)), unmatched_cost, dtype=np.float64)
        cost[:, :len(pads)] = invalid_cost
        tolerance = max(8.0, min(h, w) * 0.025)
        for prior_i, prior in enumerate(priors):
            px, py = prior["xy"]
            for pad_i, pad in enumerate(pads):
                qx, qy = pad["xy"]
                distance = math.hypot(px - qx, py - qy)
                if distance > tolerance:
                    continue
                dx, dy = qx - px, qy - py
                norm = max(1e-6, math.hypot(dx, dy))
                direction = prior["direction_xy"]
                direction_score = max(0.0, min(1.0, (dx * direction[0] + dy * direction[1]) / norm))
                score = (0.50 * math.exp(-distance / max(1.0, tolerance * 0.55)) +
                         0.30 * direction_score + 0.20 * pad["confidence"])
                if direction_score < 0.15:
                    continue
                cost[prior_i, pad_i] = 1.0 - score
                match_scores[(prior_i, pad_i)] = (score, distance)
        for prior_i, pad_i in _hungarian_assignment(cost):
            if pad_i >= len(pads) or (prior_i, pad_i) not in match_scores:
                continue
            score, distance = match_scores[(prior_i, pad_i)]
            if score < 1.0 - unmatched_cost:
                continue
            prior, pad = priors[prior_i], pads[pad_i]
            matches.append({"prior_id": prior["id"], "pad_id": pad["id"],
                            "component_index": prior["component_index"],
                            "distance_px": round(distance, 1), "match_score": round(score, 3),
                            "assignment": "HUNGARIAN_GLOBAL"})

    # Each connected centerline component becomes its own graph node. Every
    # pad touching that component gets an edge, preserving branches and parallel
    # trace segments without collapsing a multi-pad net to one extreme pair.
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
        local_component = (skel_labels == label_id).astype(np.uint8)
        polylines = _ordered_skeleton_chains(local_component)
        original_regions = set(int(v) for v in np.unique(original_labels[ys, xs]) if v > 0)
        attached_pads = []
        for pad in pads:
            x, y = pad["xy"]
            d2 = (xs - x) ** 2 + (ys - y) ** 2
            closest_index = int(np.argmin(d2))
            contact_preserved = bool(pad_contact_labels.get(pad["id"], set()) & original_regions)
            if contact_preserved or float(d2[closest_index]) <= max_pad_gap ** 2:
                attached_pads.append((pad, closest_index, math.sqrt(float(d2[closest_index]))))
        density = float(np.mean(voting_score[ys, xs]))
        trace_node_id = f"trace_component_{label_id}"
        graph_nodes.append({"id": trace_node_id, "kind": "centerline_component",
                            "centerline_pixels": int(skel_stats[label_id, cv2.CC_STAT_AREA]),
                            "polylines": polylines, "evidence": round(density, 3),
                            "attached_pad_ids": [p[0]["id"] for p in attached_pads],
                            "contact_preserved_from_pre_suppression_mask": bool(attached_pads)})
        for pad, closest_index, gap in attached_pads:
            nearest_point = [int(xs[closest_index]), int(ys[closest_index])]
            points = [[int(round(pad["xy"][0])), int(round(pad["xy"][1]))], nearest_point]
            rank = max(0.0, min(100.0, 100 * (
                0.55 * density + 0.25 * pad["confidence"] +
                0.20 * math.exp(-gap / max(1.0, max_pad_gap)))))
            graph_edges.append({"id": len(graph_edges)+1, "from": f"pad_{pad['id']}",
                                "to": trace_node_id, "points": points,
                                "rank_score": round(rank, 1), "evidence": round(density, 3),
                                "uncertainty": round(1.0 - rank / 100.0, 3),
                                "centerline_pixels": len(points), "method": "pad_centerline_contact"})

    graph_backend = "adjacency-list"
    try:
        import networkx as nx
        graph = nx.MultiGraph()
        for node in graph_nodes:
            graph.add_node(node["id"], **node)
        for edge in graph_edges:
            graph.add_edge(edge["from"], edge["to"], **edge)
        graph_backend = "NetworkX MultiGraph"
        graph_nodes = [{"id": node, **attrs} for node, attrs in graph.nodes(data=True)]
        graph_edges = [{k: v for k, v in attrs.items() if k not in {"from", "to"}} |
                       {"from": a, "to": b} for a, b, attrs in graph.edges(data=True)]
    except ImportError:
        pass

    prior_component_indexes = {p["component_index"] for p in priors}
    prior_unavailable = [{"component_index": i,
                          "class": str(d.get("class_name", "component")),
                          "reason": "NO_SUPPORTED_PACKAGE_PIN_TEMPLATE"}
                         for i, d in enumerate(detections)
                         if str(d.get("class_name", "component")).lower() in {"ic", "connector"}
                         and i not in prior_component_indexes]
    diagnostics = {"stages": ["PRISM/line/color multi-filter voting", "morphological pad candidates",
                              "pad exclusion", "Zhang-Suen centerline", "package-edge pin priors",
                              "distance/geometric pad matching", "uncertainty-ranked graph"],
                   "mask_pixels": int(cv2.countNonZero(clean)), "centerline_pixels": int(cv2.countNonZero(skeleton)),
                   "pad_candidates": len(pads), "pin_priors": len(priors), "pin_pad_matches": len(matches),
                   "pin_prior_unavailable_components": prior_unavailable,
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
    for node in graph_nodes:
        if node.get("kind") != "centerline_component":
            continue
        for chain in node.get("polylines", []):
            if len(chain) > 1:
                cv2.polylines(graph_overlay, [np.asarray(chain, np.int32).reshape((-1, 1, 2))],
                              False, (255, 40, 220), 2, cv2.LINE_AA)

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
