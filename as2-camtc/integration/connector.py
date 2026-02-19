"""
AS2-CAMTC Integration: Submit finalized block transactions to Ethereum contracts.
"""
import json
import logging
import os
from pathlib import Path

from web3 import Web3
from web3.providers import HTTPProvider

from blockchain.block import Block, Transaction

logger = logging.getLogger(__name__)

DEPLOYED_DIR = Path(__file__).resolve().parent.parent / "contracts" / "deployed"

DOMAIN_RECORD_TYPES = {
    "healthcare": {
        "cardiac_alert": 0,
        "medication_order": 1,
        "vitals_log": 2,
        "lab_result": 3,
        "icu_alert": 4,
    },
    "finance": {"market": 0, "limit": 1, "stop": 2, "hft": 3, "settlement": 4},
    "iot": {"fire": 0, "gas": 1, "temperature": 2, "traffic": 3, "motion": 4},
}


class BlockchainConnector:
    def __init__(self, ganache_url: str = "http://ganache:8545"):
        self.ganache_url = ganache_url
        self.w3 = Web3(HTTPProvider(ganache_url))
        self.account = self.w3.eth.accounts[0] if self.w3.eth.accounts else None
        self._contracts = {}
        self._load_contracts()

    def _load_contracts(self) -> None:
        if not self.w3.is_connected():
            logger.warning("[CONNECTOR] Ganache not connected at %s", self.ganache_url)
            return
        names = ["HealthcareContract", "FinanceContract", "IoTContract"]
        for name in names:
            abi_path = DEPLOYED_DIR / f"{name}.abi.json"
            addr_path = DEPLOYED_DIR / f"{name}.address.txt"
            if abi_path.exists() and addr_path.exists():
                try:
                    with open(abi_path) as f:
                        abi = json.load(f)
                    with open(addr_path) as f:
                        addr = f.read().strip()
                    self._contracts[name] = self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
                    logger.info("[CONNECTOR] loaded %s at %s", name, addr)
                except Exception as e:
                    logger.warning("[CONNECTOR] failed to load %s: %s", name, e)
            else:
                logger.debug("[CONNECTOR] no deployment for %s (missing %s or %s)", name, abi_path, addr_path)

    def _bytes32(self, s: str) -> bytes:
        if len(s) > 32:
            return self.w3.keccak(text=s)[:32]
        return s.encode().ljust(32, b"\0")[:32]

    def process_finalized_block(self, block: Block, cr=None) -> None:
        if not self._contracts:
            return
        h = block.hash.replace("0x", "")
        block_hash_bytes = bytes.fromhex(h[:64]) if len(h) >= 64 else bytes.fromhex(h.zfill(64))
        if len(block_hash_bytes) < 32:
            block_hash_bytes = (block_hash_bytes + b"\0" * 32)[:32]
        block_hash_b32 = "0x" + block_hash_bytes.hex()
        for tx in block.transactions:
            self._submit_to_contract(tx, block_hash_b32)

    def _submit_to_contract(self, tx: Transaction, block_hash: str) -> None:
        domain = (tx.domain or "").lower()
        data = tx.data or {}
        try:
            if domain == "healthcare" and "HealthcareContract" in self._contracts:
                c = self._contracts["HealthcareContract"]
                patient_id = self._bytes32(data.get("patient_id", tx.tx_id))
                record_type = DOMAIN_RECORD_TYPES.get("healthcare", {}).get(tx.tx_type.lower().replace("-", "_"), 0)
                data_hash = self.w3.keccak(text=tx.tx_id)
                is_emergency = tx.tier == 1 or data.get("is_emergency", False)
                tx_hash = c.functions.submitRecord(
                    patient_id,
                    record_type,
                    data_hash,
                    tx.tier,
                    is_emergency,
                    block_hash,
                ).transact({"from": self.account})
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                logger.info("[CONTRACT] HealthcareContract.submitRecord() | tx=%s | status=%s", tx_hash.hex(), "✅" if receipt.get("status") == 1 else "❌")
                if is_emergency:
                    logger.info("[CONTRACT] EmergencyAlert emitted | patient=%s | tier=%d", data.get("patient_id", tx.tx_id), tx.tier)
            elif domain == "finance" and "FinanceContract" in self._contracts:
                c = self._contracts["FinanceContract"]
                order_id = self._bytes32(data.get("order_id", tx.tx_id))
                order_type = DOMAIN_RECORD_TYPES.get("finance", {}).get(tx.tx_type.lower(), 0)
                amount = int(data.get("amount", 100))
                price = int(data.get("price", 100))
                tx_hash = c.functions.placeOrder(order_id, order_type, amount, price, tx.tier, block_hash).transact({"from": self.account})
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                logger.info("[CONTRACT] FinanceContract.placeOrder() | tx=%s | status=%s", tx_hash.hex(), "✅" if receipt.get("status") == 1 else "❌")
            elif domain == "iot" and "IoTContract" in self._contracts:
                c = self._contracts["IoTContract"]
                sensor_id = self._bytes32(data.get("sensor_id", tx.tx_id))
                sensor_type = DOMAIN_RECORD_TYPES.get("iot", {}).get(tx.tx_type.lower(), 0)
                data_hash = self.w3.keccak(text=tx.tx_id)
                is_alert = tx.tier == 1 or data.get("is_alert", False)
                location = str(data.get("location", "unknown"))[:64]
                tx_hash = c.functions.recordSensorData(
                    sensor_id, sensor_type, data_hash, tx.tier, is_alert, location, block_hash
                ).transact({"from": self.account})
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                logger.info("[CONTRACT] IoTContract.recordSensorData() | tx=%s | status=%s", tx_hash.hex(), "✅" if receipt.get("status") == 1 else "❌")
        except Exception as e:
            logger.exception("[CONTRACT] _submit_to_contract failed | domain=%s | error=%s", domain, e)
