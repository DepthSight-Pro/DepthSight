# api/nft_verifier.py
"""
DepthSight Genesis NFT Pass on-chain verifier on Arbitrum One (Chain 42161).
Inspects ERC-1155 contract 0x29ce393672507c185a5E9Bc2e721E8009e3520C8 for:
- Token #1: DepthSight Core Syndicate Pass (+0.5x additive mining bonus)
- Token #2: DepthSight Apex Syndicate Pass (+1.0x additive mining bonus)
- Token #0 is untouched / reserved.
"""

import logging
import re
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("depthsight.nft_verifier")

NFT_CONTRACT_ADDRESS = "0x29ce393672507c185a5E9Bc2e721E8009e3520C8"
ARBITRUM_CHAIN_ID = 42161

ARBITRUM_RPCS = [
    "https://arb1.arbitrum.io/rpc",
    "https://arbitrum.llamarpc.com",
    "https://1rpc.io/arb",
    "https://rpc.ankr.com/arbitrum",
]

# Standard ERC-1155 balanceOf(address,uint256) function selector: 0x00fdd58e
BALANCE_OF_SELECTOR = "0x00fdd58e"

TOKEN_CONFIGS = {
    2: {
        "pass_type": "apex",
        "name": "DepthSight Apex Syndicate Pass",
        "bonus_multiplier": 1.0,  # Additive +1.0x (1.0 + 1.0 = 2.0x)
        "nominal": 50000.0,
        "multiplier_label": "2.0x",
    },
    1: {
        "pass_type": "core",
        "name": "DepthSight Core Syndicate Pass",
        "bonus_multiplier": 0.5,  # Additive +0.5x (1.0 + 0.5 = 1.5x)
        "nominal": 25000.0,
        "multiplier_label": "1.5x",
    },
}

_MEMORY_CACHE: Dict[str, Dict[str, Any]] = {}


def is_valid_evm_address(address: Optional[str]) -> bool:
    if not address or not isinstance(address, str):
        return False
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address.strip()))


def encode_balance_of_call(wallet: str, token_id: int) -> str:
    clean_wallet = wallet.strip().lower().replace("0x", "").zfill(64)
    token_hex = hex(token_id).replace("0x", "").zfill(64)
    return BALANCE_OF_SELECTOR + clean_wallet + token_hex


async def query_erc1155_balance(
    wallet: str,
    token_id: int,
    contract_address: str = NFT_CONTRACT_ADDRESS,
    timeout: float = 6.0,
) -> int:
    """
    Queries balanceOf(wallet, token_id) directly via Arbitrum One JSON-RPC.
    Tries public RPC endpoints with failover.
    """
    if not is_valid_evm_address(wallet):
        return 0

    calldata = encode_balance_of_call(wallet, token_id)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": contract_address,
                "data": calldata,
            },
            "latest",
        ],
    }

    for rpc_url in ARBITRUM_RPCS:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(rpc_url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    raw_hex = data.get("result")
                    if raw_hex and raw_hex.startswith("0x") and len(raw_hex) > 2:
                        return int(raw_hex, 16)
        except Exception as exc:
            logger.debug(f"[NFT Verifier] RPC failover {rpc_url}: {exc}")
            continue

    logger.warning(
        f"[NFT Verifier] All Arbitrum RPCs failed for wallet {wallet} token {token_id}"
    )
    return 0


async def verify_wallet_nft(
    wallet_address: Optional[str],
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Verifies if a wallet holds a DepthSight Genesis Pass (Token #1 or #2).
    Token #2 takes priority if both are held.
    Returns:
        {
            "has_nft": bool,
            "token_id": Optional[int],
            "pass_type": Optional[str],
            "name": Optional[str],
            "bonus_multiplier": float,  # e.g. 0.5 or 1.0 (additive!)
            "balance": int,
            "contract": str,
            "chain_id": int,
        }
    """
    default_res: Dict[str, Any] = {
        "has_nft": False,
        "token_id": None,
        "pass_type": None,
        "name": None,
        "bonus_multiplier": 0.0,
        "balance": 0,
        "contract": NFT_CONTRACT_ADDRESS,
        "chain_id": ARBITRUM_CHAIN_ID,
    }

    if not is_valid_evm_address(wallet_address):
        return default_res

    clean_wallet = wallet_address.strip().lower()

    if not force_refresh and clean_wallet in _MEMORY_CACHE:
        return _MEMORY_CACHE[clean_wallet]

    # 1. Check Token #2 (Apex Syndicate Pass, +1.0x bonus) first
    bal_apex = await query_erc1155_balance(clean_wallet, 2)
    if bal_apex > 0:
        cfg = TOKEN_CONFIGS[2]
        res = {
            "has_nft": True,
            "token_id": 2,
            "pass_type": cfg["pass_type"],
            "name": cfg["name"],
            "bonus_multiplier": cfg["bonus_multiplier"],
            "balance": bal_apex,
            "contract": NFT_CONTRACT_ADDRESS,
            "chain_id": ARBITRUM_CHAIN_ID,
        }
        _MEMORY_CACHE[clean_wallet] = res
        return res

    # 2. Check Token #1 (Core Syndicate Pass, +0.5x bonus)
    bal_core = await query_erc1155_balance(clean_wallet, 1)
    if bal_core > 0:
        cfg = TOKEN_CONFIGS[1]
        res = {
            "has_nft": True,
            "token_id": 1,
            "pass_type": cfg["pass_type"],
            "name": cfg["name"],
            "bonus_multiplier": cfg["bonus_multiplier"],
            "balance": bal_core,
            "contract": NFT_CONTRACT_ADDRESS,
            "chain_id": ARBITRUM_CHAIN_ID,
        }
        _MEMORY_CACHE[clean_wallet] = res
        return res

    _MEMORY_CACHE[clean_wallet] = default_res
    return default_res


async def batch_verify_wallet_nfts(
    wallets: List[str],
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Verifies multiple wallets in parallel.
    Returns mapping clean_wallet -> verification_result.
    """
    import asyncio

    unique_wallets = list(
        {w.strip().lower() for w in wallets if is_valid_evm_address(w)}
    )
    if not unique_wallets:
        return {}

    tasks = [verify_wallet_nft(w, force_refresh=force_refresh) for w in unique_wallets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    mapping = {}
    for w, r in zip(unique_wallets, results):
        if isinstance(r, dict):
            mapping[w] = r
        else:
            mapping[w] = {
                "has_nft": False,
                "token_id": None,
                "pass_type": None,
                "name": None,
                "bonus_multiplier": 0.0,
                "balance": 0,
                "contract": NFT_CONTRACT_ADDRESS,
                "chain_id": ARBITRUM_CHAIN_ID,
            }

    return mapping

