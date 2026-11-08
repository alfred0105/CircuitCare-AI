"""Soft clDice loss for binary PCB trace segmentation experiments.

This is a small PyTorch implementation based on the published soft-skeleton
formulation. It expects dense pixel masks and is not used by the current
YOLO object-detection checkpoints.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


def _soft_erode(image: torch.Tensor) -> torch.Tensor:
    vertical = -F.max_pool2d(-image, kernel_size=(3, 1), stride=1, padding=(1, 0))
    horizontal = -F.max_pool2d(-image, kernel_size=(1, 3), stride=1, padding=(0, 1))
    return torch.minimum(vertical, horizontal)


def _soft_dilate(image: torch.Tensor) -> torch.Tensor:
    return F.max_pool2d(image, kernel_size=3, stride=1, padding=1)


def soft_skeletonize(image: torch.Tensor, iterations: int = 10) -> torch.Tensor:
    image = image.clamp(0, 1)
    opened = _soft_dilate(_soft_erode(image))
    skeleton = F.relu(image - opened)
    current = image
    for _ in range(max(0, iterations)):
        current = _soft_erode(current)
        delta = F.relu(current - _soft_dilate(_soft_erode(current)))
        skeleton = skeleton + F.relu(delta - skeleton * delta)
    return skeleton.clamp(0, 1)


def soft_cldice_loss(probabilities: torch.Tensor, target: torch.Tensor,
                     iterations: int = 10, smooth: float = 1.0) -> torch.Tensor:
    """Topology-aware loss for probabilities and binary masks, both Bx1xHxW."""
    if probabilities.ndim != 4 or target.ndim != 4:
        raise ValueError("soft_cldice_loss expects BxCxHxW tensors")
    if probabilities.shape != target.shape:
        raise ValueError("prediction and target shapes must match")
    pred = probabilities.clamp(0, 1)
    truth = target.to(dtype=pred.dtype).clamp(0, 1)
    pred_skeleton = soft_skeletonize(pred, iterations)
    truth_skeleton = soft_skeletonize(truth, iterations)
    topology_precision = ((pred_skeleton * truth).sum() + smooth) / (pred_skeleton.sum() + smooth)
    topology_sensitivity = ((truth_skeleton * pred).sum() + smooth) / (truth_skeleton.sum() + smooth)
    cldice = (2 * topology_precision * topology_sensitivity /
              (topology_precision + topology_sensitivity).clamp_min(1e-7))
    return 1 - cldice


def combined_trace_loss(logits: torch.Tensor, target: torch.Tensor,
                        cldice_weight: float = 0.5, skeleton_iterations: int = 10) -> torch.Tensor:
    """BCE + soft Dice + weighted soft clDice for a binary segmentation head."""
    target = target.to(dtype=logits.dtype)
    probabilities = torch.sigmoid(logits)
    bce = F.binary_cross_entropy_with_logits(logits, target)
    smooth = 1.0
    dice = 1 - ((2 * (probabilities * target).sum() + smooth) /
                (probabilities.sum() + target.sum() + smooth))
    topology = soft_cldice_loss(probabilities, target, iterations=skeleton_iterations)
    return bce + dice + float(cldice_weight) * topology
