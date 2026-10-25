from __future__ import annotations

import logging

import torch

LOGGER = logging.getLogger(__name__)


def select_inference_device(preferred_device: str) -> str:
    if preferred_device != "cuda":
        LOGGER.info("Inference device selected: %s", preferred_device)
        return preferred_device

    if not torch.cuda.is_available():
        LOGGER.warning("CUDA is unavailable; inference will use CPU")
        return "cpu"

    device_name = torch.cuda.get_device_name(0)
    LOGGER.info("Inference device selected: cuda (%s)", device_name)
    return "cuda"


def get_cuda_status() -> tuple[bool, str]:
    is_available = torch.cuda.is_available()
    if not is_available:
        return False, ""
    return True, torch.cuda.get_device_name(0)
