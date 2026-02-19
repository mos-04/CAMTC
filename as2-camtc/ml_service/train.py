"""
AS2-CAMTC ML Service: Train PriorityNet on 10k synthetic samples (healthcare, finance, IoT).
"""
import logging
import os
import sys
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

from model import PriorityNet, DOMAIN_MAP, assign_tier

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DOMAIN_WEIGHTS = {
    "healthcare": {"urgency": 0.5, "value": 0.2, "reputation": 0.15, "latency": 0.15},
    "finance": {"urgency": 0.2, "value": 0.5, "reputation": 0.15, "latency": 0.15},
    "iot": {"urgency": 0.3, "value": 0.1, "reputation": 0.2, "latency": 0.4},
}

TX_TYPE_EMBED = {
    "healthcare": {"cardiac_alert": 0, "medication_order": 1, "vitals_log": 2, "lab_result": 3, "icu_alert": 4},
    "finance": {"market": 0, "limit": 1, "stop": 2, "hft": 3, "settlement": 4},
    "iot": {"fire": 0, "gas": 1, "temperature": 2, "traffic": 3, "motion": 4},
}


def one_hot_tx_type(domain: str, tx_type: str) -> np.ndarray:
    d = TX_TYPE_EMBED.get(domain, {})
    idx = d.get(tx_type, 0)
    arr = np.zeros(5)
    arr[min(idx, 4)] = 1.0
    return arr


def oracle_priority(domain: str, urgency: float, value: float, reputation: float, latency: float) -> float:
    w = DOMAIN_WEIGHTS[domain]
    return float(
        w["urgency"] * urgency + w["value"] * value + w["reputation"] * reputation + w["latency"] * latency
    )


def generate_samples(n_total: int = 10000):
    np.random.seed(42)
    domains_list = []
    tx_types_list = []
    urgency_list = []
    value_list = []
    reputation_list = []
    latency_list = []
    labels_list = []

    n_hc = 3500
    n_fin = 3500
    n_iot = n_total - n_hc - n_fin

    def add_domain(count: int, domain: str, tx_types: list, u_a, u_b, v_a, v_b, r_a, r_b, l_a, l_b):
        for _ in range(count):
            domains_list.append(domain)
            tx_types_list.append(np.random.choice(tx_types))
            u = np.random.beta(u_a, u_b)
            v = np.random.beta(v_a, v_b)
            r = np.random.beta(r_a, r_b)
            l = np.random.beta(l_a, l_b)
            urgency_list.append(u)
            value_list.append(v)
            reputation_list.append(r)
            latency_list.append(l)
            labels_list.append(oracle_priority(domain, u, v, r, l))

    add_domain(n_hc, "healthcare", ["cardiac_alert", "medication_order", "vitals_log", "lab_result", "icu_alert"],
               8, 2, 6, 4, 9, 2, 7, 3)
    add_domain(n_fin, "finance", ["market", "limit", "stop", "hft", "settlement"],
               6, 4, 9, 2, 8, 3, 6, 4)
    add_domain(n_iot, "iot", ["fire", "gas", "temperature", "traffic", "motion"],
               5, 3, 4, 6, 7, 3, 9, 2)

    domain_ids = np.array([DOMAIN_MAP[d] for d in domains_list], dtype=np.int64)
    urgency = np.array(urgency_list, dtype=np.float32).reshape(-1, 1)
    value = np.array(value_list, dtype=np.float32).reshape(-1, 1)
    reputation = np.array(reputation_list, dtype=np.float32).reshape(-1, 1)
    latency = np.array(latency_list, dtype=np.float32).reshape(-1, 1)

    tx_embeds = np.zeros((n_total, 5), dtype=np.float32)
    for i in range(n_total):
        tx_embeds[i] = one_hot_tx_type(domains_list[i], tx_types_list[i])

    features = np.hstack([urgency, value, reputation, latency, tx_embeds, np.zeros((n_total, 8))])
    features = features[:, :17]

    labels = np.array(labels_list, dtype=np.float32)
    return domain_ids, features, labels


def main():
    os.makedirs("models", exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("device=%s", device)

    domain_ids, features, labels = generate_samples(10000)
    d_id = torch.from_numpy(domain_ids)
    x = torch.from_numpy(features)
    y = torch.from_numpy(labels).unsqueeze(1)

    dataset = TensorDataset(d_id, x, y)
    loader = DataLoader(dataset, batch_size=32, shuffle=True, num_workers=0)

    model = PriorityNet().to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    for epoch in range(100):
        model.train()
        total_loss = 0.0
        for batch_d, batch_x, batch_y in loader:
            batch_d = batch_d.to(device)
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad()
            out = model(batch_d, batch_x)
            loss = criterion(out.unsqueeze(1), batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        avg_loss = total_loss / len(loader)
        if (epoch + 1) % 10 == 0:
            logger.info("epoch=%d loss=%.4f", epoch + 1, avg_loss)

    model.eval()
    with torch.no_grad():
        pred = model(d_id.to(device), x.to(device)).cpu().numpy()
    pred_clip = np.clip(pred, 0.0, 1.0)
    pred_tiers = np.array([assign_tier(p) for p in pred_clip])
    true_tiers = np.array([assign_tier(l) for l in labels])
    tier_acc = (pred_tiers == true_tiers).mean() * 100
    final_loss = float(np.mean((pred_clip - labels) ** 2))

    torch.save(model.state_dict(), "models/priority_model.pth")
    logger.info("Saved models/priority_model.pth")
    logger.info("Final loss=%.4f Tier accuracy=%.2f%%", final_loss, tier_acc)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.metrics import confusion_matrix
        cm = confusion_matrix(true_tiers, pred_tiers, labels=[1, 2, 3])
        plt.figure(figsize=(6, 5))
        plt.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        plt.title("Tier confusion matrix")
        plt.colorbar()
        tick_marks = np.arange(3)
        plt.xticks(tick_marks, ["T1", "T2", "T3"])
        plt.yticks(tick_marks, ["T1", "T2", "T3"])
        thresh = cm.max() / 2.0
        for i in range(3):
            for j in range(3):
                plt.text(j, i, str(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > thresh else "black")
        plt.ylabel("True tier")
        plt.xlabel("Predicted tier")
        plt.tight_layout()
        plt.savefig("models/confusion_matrix.png", dpi=100)
        plt.close()
        logger.info("Saved models/confusion_matrix.png")
    except Exception as e:
        logger.warning("Could not save confusion matrix: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
