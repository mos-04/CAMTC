"""
AS2-CAMTC Blockchain: Transaction and Block dataclasses with hashing.
"""
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Transaction:
    tx_id: str
    domain: str
    tx_type: str
    urgency: float
    value: float
    sender_reputation: float
    latency_sensitivity: float
    priority_score: float
    tier: int
    timestamp: float
    data: Dict[str, Any]
    sender_id: str

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "domain": self.domain,
            "tx_type": self.tx_type,
            "urgency": self.urgency,
            "value": self.value,
            "sender_reputation": self.sender_reputation,
            "latency_sensitivity": self.latency_sensitivity,
            "priority_score": self.priority_score,
            "tier": self.tier,
            "timestamp": self.timestamp,
            "data": self.data,
            "sender_id": self.sender_id,
        }

    def hash(self) -> str:
        content = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class Block:
    index: int
    tier: int
    transactions: List[Transaction]
    previous_hash: str
    validator_id: str
    committee: List[str]
    signatures: Dict[str, str]
    timestamp: float
    nonce: int
    hash: str = ""

    def __post_init__(self):
        if not self.hash:
            self.hash = self.calculate_hash()

    def calculate_hash(self) -> str:
        block_data = {
            "index": self.index,
            "tier": self.tier,
            "tx_hashes": [tx.hash() for tx in self.transactions],
            "previous_hash": self.previous_hash,
            "validator_id": self.validator_id,
            "committee": sorted(self.committee),
            "timestamp": self.timestamp,
            "nonce": self.nonce,
        }
        content = json.dumps(block_data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "tier": self.tier,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "previous_hash": self.previous_hash,
            "validator_id": self.validator_id,
            "committee": self.committee,
            "signatures": self.signatures,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "hash": self.hash,
        }


def genesis_block() -> Block:
    return Block(
        index=0,
        tier=1,
        transactions=[],
        previous_hash="0" * 64,
        validator_id="genesis",
        committee=[],
        signatures={},
        timestamp=0.0,
        nonce=0,
        hash="0" * 64,
    )
