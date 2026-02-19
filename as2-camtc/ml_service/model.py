"""
AS2-CAMTC ML Service: PriorityNet model for multi-tier priority scoring.
"""
import logging
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

DOMAIN_MAP = {"healthcare": 0, "finance": 1, "iot": 2}
DOMAIN_NAMES = ["healthcare", "finance", "iot"]


def assign_tier(priority: float) -> int:
    """Map priority score to tier: >0.85→1, >0.60→2, else→3."""
    if priority > 0.85:
        return 1
    if priority > 0.60:
        return 2
    return 3


class PriorityNet(nn.Module):
    """Neural network for transaction priority scoring. 3 domains → 16-dim embedding + 17 features → 1 priority."""

    def __init__(self, num_domains: int = 3, embed_dim: int = 16, feature_dim: int = 17):
        super().__init__()
        self.domain_embed = nn.Embedding(num_domains, embed_dim)
        input_dim = embed_dim + feature_dim
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.BatchNorm1d(32),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, domain_id: torch.Tensor, features: torch.Tensor) -> torch.Tensor:
        """
        domain_id: (batch,) or scalar, long tensor 0/1/2
        features: (batch, 17) - urgency, value, reputation, latency_sensitivity, tx_type_one_hot(3), etc.
        """
        if domain_id.dim() == 0:
            domain_id = domain_id.unsqueeze(0)
        if features.dim() == 1:
            features = features.unsqueeze(0)
        emb = self.domain_embed(domain_id)
        x = torch.cat([emb, features], dim=-1)
        return self.net(x).squeeze(-1)
