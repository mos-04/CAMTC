"""
AS2-CAMTC Scripts: Train PriorityNet on 10k synthetic samples (standalone).
"""
import logging
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml_service"))
from model import PriorityNet, DOMAIN_MAP, assign_tier

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DOMAIN_WEIGHTS = {
    "healthcare": {"urgency": 0.5, "value": 0.2, "reputation": 0.15, "latency": 0.15},
    "finance": {"urgency": 0.2, "value": 0.5, "reputation": 0.15, "latency": 0.15},
    "iot": {"urgency": 0.3, "value": 0.1, "reputation": 0.2, "latency": 0.4},
}


def one_hot(domain: str, tx_type: str) -> np.ndarray:
    types = {
        "healthcare": ["cardiac_alert", "medication_order", "vitals_log", "lab_result", "icu_alert"],
        "finance": ["market", "limit", "stop", "hft", "settlement"],
        "iot": ["fire", "gas", "temperature", "traffic", "motion"],
    }
    arr = np.zeros(5)
    lst = types.get(domain, types["healthcare"])
    try:
        idx = lst.index(tx_type) if tx_type in lst else 0
    except ValueError:
        idx = 0
    arr[min(idx, 4)] = 1.0
    return arr


def oracle_priority(domain: str, u: float, v: float, r: float, l: float) -> float:
    w = DOMAIN_WEIGHTS[domain]
    return w["urgency"] * u + w["value"] * v + w["reputation"] * r + w["latency"] * l


def generate_10k():
    np.random.seed(42)
    n = 10000
    domain_ids = []
    features_list = []
    labels_list = []
    for _ in range(3500):
        d = "healthcare"
        domain_ids.append(DOMAIN_MAP[d])
        u, v, r, lat = np.random.beta(8, 2), np.random.beta(6, 4), np.random.beta(9, 2), np.random.beta(7, 3)
        tx = np.random.choice(["cardiac_alert", "medication_order", "vitals_log", "lab_result", "icu_alert"])
        domain_ids[-1] = DOMAIN_MAP[d]
        features_list.append([u, v, r, lat] + list(one_hot(d, tx)) + [0.0] * 8)
        features_list[-1] = (features_list[-1] + [0.0] * 17)[:17]
        labels_list.append(oracle_priority(d, u, v, r, lat))
    for _ in range(3500):
        d = "finance"
        domain_ids.append(DOMAIN_MAP[d])
        u, v, r, lat = np.random.beta(6, 4), np.random.beta(9, 2), np.random.beta(8, 3), np.random.beta(6, 4)
        tx = np.random.choice(["market", "limit", "stop", "hft", "settlement"])
        features_list.append([u, v, r, lat] + list(one_hot(d, tx)) + [0.0] * 8)
        features_list[-1] = (features_list[-1] + [0.0] * 17)[:17]
        labels_list.append(oracle_priority(d, u, v, r, lat))
    for _ in range(3000):
        d = "iot"
        domain_ids.append(DOMAIN_MAP[d])
        u, v, r, lat = np.random.beta(5, 3), np.random.beta(4, 6), np.random.beta(7, 3), np.random.beta(9, 2)
        tx = np.random.choice(["fire", "gas", "temperature", "traffic", "motion"])
        features_list.append([u, v, r, lat] + list(one_hot(d, tx)) + [0.0] * 8)
        features_list[-1] = (features_list[-1] + [0.0] * 17)[:17]
        labels_list.append(oracle_priority(d, u, v, r, lat))
    D = np.array(domain_ids, dtype=np.int64)
    X = np.array(features_list, dtype=np.float32)
    Y = np.array(labels_list, dtype=np.float32)
    return D, X, Y


def main():
    model_dir = ROOT / "ml_service" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    D, X, Y = generate_10k()
    n = len(Y)
    idx = np.random.permutation(n)
    split = int(0.8 * n)
    train_idx, val_idx = idx[:split], idx[split:]
    D_t, X_t, Y_t = D[train_idx], X[train_idx], Y[train_idx]
    D_v, X_v, Y_v = D[val_idx], X[val_idx], Y[val_idx]
    loader = DataLoader(
        TensorDataset(torch.from_numpy(D_t), torch.from_numpy(X_t), torch.from_numpy(Y_t).unsqueeze(1)),
        batch_size=32,
        shuffle=True,
    )
    model = PriorityNet().to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    for epoch in range(100):
        model.train()
        total = 0.0
        for batch_d, batch_x, batch_y in loader:
            batch_d, batch_x, batch_y = batch_d.to(device), batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            out = model(batch_d, batch_x)
            loss = criterion(out.unsqueeze(1), batch_y)
            loss.backward()
            optimizer.step()
            total += loss.item()
        if (epoch + 1) % 10 == 0:
            logger.info("epoch=%d loss=%.4f", epoch + 1, total / len(loader))
    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(D_v).to(device), torch.from_numpy(X_v).to(device)).cpu().numpy()
    pred = np.clip(pred, 0.0, 1.0)
    pred_tiers = np.array([assign_tier(p) for p in pred])
    true_tiers = np.array([assign_tier(y) for y in Y_v])
    tier_acc = (pred_tiers == true_tiers).mean() * 100
    loss_val = float(np.mean((pred - Y_v) ** 2))
    torch.save(model.state_dict(), model_dir / "priority_model.pth")
    logger.info("Saved %s", model_dir / "priority_model.pth")
    logger.info("Loss=%.4f Tier Accuracy=%.2f%%", loss_val, tier_acc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
