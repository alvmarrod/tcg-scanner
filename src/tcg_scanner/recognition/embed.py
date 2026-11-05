from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

MODEL_NAME = "vit_small_patch14_dinov2.lvd142m"


class Embedder:
    """DINOv2 image embedder.

    torch/timm imports stay local so commands that never embed images (db, catalog)
    do not pay for them.
    """

    def __init__(self, model_name: str = MODEL_NAME, device: str | None = None) -> None:
        import timm
        import torch

        self._torch = torch
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = timm.create_model(model_name, pretrained=True, num_classes=0)
        self.model.to(self.device).eval()
        self.dim = self.model.num_features
        config = timm.data.resolve_data_config(self.model.pretrained_cfg)
        self.transform = timm.data.create_transform(**config, is_training=False)

    def __call__(self, paths: list[Path]) -> np.ndarray:
        import numpy as np
        from PIL import Image

        images = [self.transform(Image.open(path).convert("RGB")) for path in paths]
        batch = self._torch.stack(images).to(self.device)
        with self._torch.no_grad():
            features = self.model.forward_features(batch)[:, 0]
        vectors = self._torch.nn.functional.normalize(features, dim=1)
        return vectors.cpu().numpy().astype(np.float32)
