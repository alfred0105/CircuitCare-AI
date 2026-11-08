"""Experimental component-location-guided PCB connection hypotheses.

This is an independent OpenCV implementation of two ideas used by PCB
reverse-engineering tools: conductivity likelihood + A* path ranking, and
connected-region propagation from terminal-like anchors. It does not import
or copy implementation code from the referenced repositories.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from typing import Iterable

import cv2
import numpy as np


def _line_kernel(length: int, angle: float) -> np.ndarray:
    size = length | 1
    kernel = np.zeros((size, size), np.uint8)
    c = size // 2
    r = c - 1
    a = math.radians(angle)
    cv2.line(kernel, (c - round(r * math.cos(a)), c - round(r * math.sin(a))),
             (c + round(r * math.cos(a)), c + round(r * math.sin(a))), 1, 1)
    return kernel


def _conductivity_map(image: np.ndarray, grid_max: int = 240) -> tuple[np.ndarray, int, dict]:
    h, w = image.shape[:2]
    step = max(2, int(math.ceil(max(h, w) / grid_max)))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # PCB Mapper's general principle: score likely exposed conductors, then
    # combine it with local narrow-line evidence for soldermask-covered tracks.
    hue, sat, val = [hsv[:, :, i].astype(np.float32) for i in range(3)]
    color = np.full((h, w), 0.08, np.float32)
    warm = ((hue >= 3) & (hue <= 30) & (sat >= 35) & (val >= 45))
    color[warm] = np.minimum(0.9, 0.4 + sat[warm] / 255 * 0.35 + val[warm] / 255 * 0.2)
    metal = (sat <= 75) & (val >= 150)
    color[metal] = np.maximum(color[metal], 0.48 + val[metal] / 255 * 0.30)
    dark = (val < 100) & (sat < 100)
    color[dark] = np.maximum(color[dark], 0.16)

    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    response = np.zeros_like(enhanced)
    for length in (7, 11, 15):
        for angle in (0, 45, 90, 135):
            response = cv2.max(response, cv2.morphologyEx(
                enhanced, cv2.MORPH_BLACKHAT, _line_kernel(length, angle)))
    # Robust scaling limits isolated glare/lettering from dominating the map.
    scale = max(12.0, float(np.percentile(response, 99.4)))
    linear = np.clip(response.astype(np.float32) / scale, 0, 1)
    linear = np.power(linear, 1.25) * 0.82
    likelihood = np.maximum(color, linear)
    # Favor PCB interiors while allowing warm copper and metallic terminals.
    board_hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hvals = board_hsv[:, :, 0]
    svals = board_hsv[:, :, 1]
    eligible = (svals > 35) & (board_hsv[:, :, 2] > 25)
    if np.count_nonzero(eligible) > image.size // 80:
        hist = np.bincount(hvals[eligible], weights=svals[eligible], minlength=180)
        hue_center = int(np.argmax(cv2.GaussianBlur(hist.astype(np.float32)[None, :], (9, 1), 0)[0]))
        dist = np.abs(hvals.astype(np.int16) - hue_center)
        dist = np.minimum(dist, 180 - dist)
        soldermask = (dist <= 24) & (svals >= 25)
        likelihood[soldermask] = np.maximum(likelihood[soldermask], linear[soldermask])
        # Keep conductor-colored pixels even when their hue differs from mask.
        likelihood[(warm | metal)] = np.maximum(likelihood[(warm | metal)], color[(warm | metal)])
    small_w, small_h = max(1, int(math.ceil(w / step))), max(1, int(math.ceil(h / step)))
    small = cv2.resize(likelihood, (small_w, small_h), interpolation=cv2.INTER_AREA)
    return small.astype(np.float32), step, {"grid_width": small_w, "grid_height": small_h,
                                             "grid_step_px": step}


def _nearest_pairs(components: list[dict], max_pairs: int = 12) -> list[tuple[int, int, float]]:
    centers = []
    for item in components:
        x0, y0, x1, y1 = [float(v) for v in item["bbox_xyxy"]]
        centers.append(((x0 + x1) / 2, (y0 + y1) / 2))
    unique: dict[tuple[int, int], float] = {}
    for i, (x, y) in enumerate(centers):
        distances = sorted((math.hypot(x - xx, y - yy), j)
                           for j, (xx, yy) in enumerate(centers) if j != i)
        for distance, j in distances[:2]:
            a, b = sorted((i, j))
            unique[(a, b)] = distance
    return [(a, b, d) for (a, b), d in sorted(unique.items(), key=lambda v: v[1])[:max_pairs]]


def _facing_anchor(box: Iterable[float], other: Iterable[float], shape: tuple[int, int], step: int) -> tuple[int, int]:
    h, w = shape
    x0, y0, x1, y1 = [float(v) for v in box]
    ox0, oy0, ox1, oy1 = [float(v) for v in other]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tx, ty = (ox0 + ox1) / 2, (oy0 + oy1) / 2
    dx, dy = tx - cx, ty - cy
    if abs(dx) * max(1, y1 - y0) > abs(dy) * max(1, x1 - x0):
        x = x1 if dx >= 0 else x0
        y = min(y1, max(y0, cy + (x - cx) * dy / (dx if abs(dx) > 1e-6 else 1)))
    else:
        y = y1 if dy >= 0 else y0
        x = min(x1, max(x0, cx + (y - cy) * dx / (dy if abs(dy) > 1e-6 else 1)))
    x += (step * 1.5) * (1 if dx >= 0 else -1) if abs(dx) >= abs(dy) else 0
    y += (step * 1.5) * (1 if dy >= 0 else -1) if abs(dy) > abs(dx) else 0
    return (min(max(int(round(x / step)), 0), max(0, math.ceil(w / step) - 1)),
            min(max(int(round(y / step)), 0), max(0, math.ceil(h / step) - 1)))


def _astar(score: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
           blocked: np.ndarray) -> list[tuple[int, int]] | None:
    height, width = score.shape
    sx, sy = start
    gx, gy = goal
    if (sx, sy) == (gx, gy):
        return [start]
    queue = [(0.0, 0.0, sx, sy)]
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    best = {(sx, sy): 0.0}
    visited = 0
    while queue and visited < 45000:
        _, cost, x, y = heapq.heappop(queue)
        visited += 1
        if (x, y) == (gx, gy):
            path = [(x, y)]
            while path[-1] != (sx, sy):
                path.append(previous[path[-1]])
            return path[::-1]
        if cost > best.get((x, y), float("inf")):
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            base = 1.414 if dx and dy else 1.0
            cell = float(score[ny, nx])
            step_cost = base * (1.0 + 4.5 * (1.0 - cell) + (14.0 if blocked[ny, nx] else 0.0))
            new_cost = cost + step_cost
            if new_cost >= best.get((nx, ny), float("inf")):
                continue
            best[(nx, ny)] = new_cost
            previous[(nx, ny)] = (x, y)
            heuristic = math.hypot(gx - nx, gy - ny)
            heapq.heappush(queue, (new_cost + heuristic, new_cost, nx, ny))
    return None


def infer_mapper_connections(image: np.ndarray, detections: list[dict], max_pairs: int = 12):
    """Rank plausible paths between nearby detected component boxes."""
    score, step, diagnostics = _conductivity_map(image)
    h, w = image.shape[:2]
    comps = [d for d in detections if d.get("bbox_xyxy")]
    blocked_full = np.zeros((h, w), np.uint8)
    for d in comps:
        x0, y0, x1, y1 = [int(round(float(v))) for v in d["bbox_xyxy"]]
        cv2.rectangle(blocked_full, (max(0, x0 + 2), max(0, y0 + 2)),
                      (min(w - 1, x1 - 2), min(h - 1, y1 - 2)), 255, -1)
    blocked = cv2.resize(blocked_full, (score.shape[1], score.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    paths = []
    for i, j, center_distance in _nearest_pairs(comps, max_pairs=max_pairs):
        start = _facing_anchor(comps[i]["bbox_xyxy"], comps[j]["bbox_xyxy"], (h, w), step)
        goal = _facing_anchor(comps[j]["bbox_xyxy"], comps[i]["bbox_xyxy"], (h, w), step)
        route = _astar(score, start, goal, blocked)
        if not route or len(route) < 2:
            continue
        avg = float(np.mean([score[y, x] for x, y in route]))
        route_length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:])) * step
        straight = max(1.0, center_distance - (float(comps[i]["bbox_xyxy"][2])-float(comps[i]["bbox_xyxy"][0]))/2
                       - (float(comps[j]["bbox_xyxy"][2])-float(comps[j]["bbox_xyxy"][0]))/2)
        detour = min(1.0, straight / max(straight, route_length))
        rank = 100 * (0.72 * avg + 0.28 * detour)
        points = [[int(x * step + step / 2), int(y * step + step / 2)] for x, y in route]
        def label(d, index):
            return str(d.get("class_name", d.get("label", "component"))) + f" #{index + 1}"
        paths.append({"id": len(paths) + 1, "from": label(comps[i], i), "to": label(comps[j], j),
                      "points": points, "rank_score": round(rank, 1),
                      "path_length_px": round(route_length, 1), "mean_conductivity": round(avg, 3),
                      "center_distance_px": round(center_distance, 1), "method": "mapper_astar"})
    paths.sort(key=lambda p: p["rank_score"], reverse=True)
    for idx, p in enumerate(paths, 1):
        p["id"] = idx
    diagnostics.update({"method": "HSV conductivity likelihood + local line response + component-box anchors + A*",
                        "pair_count": len(paths), "warning": "순위 점수는 확률 보정값이 아닌 상대 비교용입니다."})
    return paths, diagnostics


def infer_connected_regions(image: np.ndarray, detections: list[dict], threshold: float = 0.46):
    """Flood-fill likely conductive regions and report which component edges touch them."""
    score, step, diagnostics = _conductivity_map(image)
    mask = (score >= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    h, w = image.shape[:2]
    region_links: dict[int, set[int]] = defaultdict(set)
    anchors: dict[int, list[tuple[int, int]]] = defaultdict(list)
    comps = [d for d in detections if d.get("bbox_xyxy")]
    for i, d in enumerate(comps):
        x0, y0, x1, y1 = [float(v) for v in d["bbox_xyxy"]]
        # Sample a ring just outside the component body to approximate pads/leads.
        pad = max(2, step * 2)
        ix0, iy0 = max(0, int((x0 - pad) / step)), max(0, int((y0 - pad) / step))
        ix1, iy1 = min(mask.shape[1]-1, int((x1 + pad) / step)), min(mask.shape[0]-1, int((y1 + pad) / step))
        for x, y in ((ix0, int((iy0+iy1)/2)), (ix1, int((iy0+iy1)/2)),
                     (int((ix0+ix1)/2), iy0), (int((ix0+ix1)/2), iy1)):
            if 0 <= x < labels.shape[1] and 0 <= y < labels.shape[0]:
                region_id = int(labels[y, x])
                if region_id > 0:
                    region_links[region_id].add(i)
                    anchors[region_id].append((x, y))
    groups = []
    for region_id, members in region_links.items():
        if len(members) < 2:
            continue
        xs, ys = np.where(labels == region_id)
        if len(xs) < 4:
            continue
        ids = sorted(members)
        for a, b in zip(ids, ids[1:]):
            c1, c2 = comps[a], comps[b]
            name_a = str(c1.get("class_name", c1.get("label", "component"))) + f" #{a+1}"
            name_b = str(c2.get("class_name", c2.get("label", "component"))) + f" #{b+1}"
            px = [[int(x * step + step / 2), int(y * step + step / 2)] for x, y in zip(xs[::max(1, len(xs)//150)], ys[::max(1, len(ys)//150)])]
            groups.append({"id": len(groups)+1, "region_id": region_id, "from": name_a, "to": name_b, "points": px,
                           "region_pixels": int(stats[region_id, cv2.CC_STAT_AREA]),
                           "method": "connected_region_floodfill"})
    diagnostics.update({"method": "conductivity threshold + connected-region flood fill + component-edge association",
                        "threshold": threshold, "connected_groups": len(groups),
                        "note": "이 방식은 고립 패드가 합쳐지기 쉬워 연결 증거가 강한 영역만 후보로 표시합니다."})
    return groups, labels, diagnostics, step


def draw_connection_overlay(image: np.ndarray, candidates: list[dict], color=(255, 70, 220)) -> np.ndarray:
    overlay = image.copy()
    for item in candidates:
        pts = item.get("points") or []
        if len(pts) < 2:
            continue
        arr = np.asarray(pts, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(overlay, [arr], False, color, 2, cv2.LINE_AA)
        x, y = pts[len(pts)//2]
        cv2.putText(overlay, f"{item['id']}:{item.get('rank_score', item.get('region_pixels', 0))}",
                    (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    return overlay


def draw_region_overlay(image: np.ndarray, candidates: list[dict], labels: np.ndarray, step: int) -> np.ndarray:
    small = np.zeros((*labels.shape, 3), np.uint8)
    for item in candidates:
        region_id = int(item["region_id"])
        # Stable but visibly distinct color per connected region.
        color = ((53 * region_id + 60) % 190 + 40,
                 (97 * region_id + 80) % 170 + 60,
                 (137 * region_id + 30) % 180 + 50)
        small[labels == region_id] = color
    full = cv2.resize(small, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
    out = image.copy()
    mask = np.any(full > 0, axis=2)
    out[mask] = cv2.addWeighted(image, 0.48, full, 0.52, 0)[mask]
    return out
