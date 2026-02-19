"""
AS2-CAMTC Scripts: Compile and deploy Solidity contracts to Ganache.
"""
import json
import logging
import os
import sys
from pathlib import Path

from web3 import Web3
from web3.providers import HTTPProvider

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("DEPLOY")

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "contracts"
DEPLOYED_DIR = CONTRACTS_DIR / "deployed"


def install_solc(version: str = "0.8.20"):
    try:
        import solcx
        solcx.install_solc(version)
        return solcx.get_solc_version()
    except Exception as e:
        logger.warning("solcx install_solc: %s", e)
        try:
            import solcx
            solcx.set_solc_version(version)
            return version
        except Exception:
            pass
    return None


def compile_and_deploy(contract_name: str, ganache_url: str, account: str):
    import solcx
    sol_path = CONTRACTS_DIR / f"{contract_name}.sol"
    if not sol_path.exists():
        logger.error("Contract not found: %s", sol_path)
        return None
    source = sol_path.read_text()
    try:
        compiled = solcx.compile_standard(
            {
                "language": "Solidity",
                "sources": {f"{contract_name}.sol": {"content": source}},
                "settings": {
                    "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
                    "optimizer": {"enabled": True, "runs": 200},
                },
            },
            allow_paths=[str(CONTRACTS_DIR)],
        )
    except Exception as e:
        logger.exception("Compile failed: %s", e)
        return None
    sol_key = f"{contract_name}.sol"
    if sol_key not in compiled["contracts"]:
        logger.error("Compiled key not found: %s", sol_key)
        return None
    contract_meta = compiled["contracts"][sol_key][contract_name]
    abi = contract_meta["abi"]
    bytecode = contract_meta["evm"]["bytecode"]["object"]
    w3 = Web3(HTTPProvider(ganache_url))
    if not w3.is_connected():
        logger.error("Ganache not connected")
        return None
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    try:
        tx_hash = Contract.constructor().transact({"from": account})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        address = receipt["contractAddress"]
        gas_used = receipt.get("gasUsed", 0)
    except Exception as e:
        logger.exception("Deploy failed: %s", e)
        return None
    DEPLOYED_DIR.mkdir(parents=True, exist_ok=True)
    (DEPLOYED_DIR / f"{contract_name}.abi.json").write_text(json.dumps(abi, indent=2))
    (DEPLOYED_DIR / f"{contract_name}.address.txt").write_text(address)
    logger.info("✅ %s at %s (gas: %s)", contract_name, address, gas_used)
    return address


def main():
    ganache_url = os.environ.get("GANACHE_URL", "http://localhost:8545")
    install_solc("0.8.20")
    w3 = Web3(HTTPProvider(ganache_url))
    if not w3.eth.accounts:
        logger.error("No accounts in Ganache")
        return 1
    account = w3.eth.accounts[0]
    for name in ["HealthcareContract", "FinanceContract", "IoTContract"]:
        compile_and_deploy(name, ganache_url, account)
    return 0


if __name__ == "__main__":
    sys.exit(main())
