from web3 import Web3
from decimal import Decimal
from .config.addresses import BASE_MAINNET, ARBITRUM_MAINNET

ETH_ORACLE_PRICE_ABI_BASE = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]

ETH_ORACLE_PRICE_ABI_ARBITRUM = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]

def get_eth_price(web3: Web3) -> Decimal:
    """Get the current ETH/USD price from the oracle contract"""
    oracle_contract = web3.eth.contract(
        address=web3.to_checksum_address(ARBITRUM_MAINNET['eth_usd_oracle']),
        abi=ETH_ORACLE_PRICE_ABI_ARBITRUM
    )
    
    # Get price and decimals
    _, price, _, _, _ = oracle_contract.functions.latestRoundData().call()
    decimals = oracle_contract.functions.decimals().call()
    
    # Convert to decimal
    price_usd = Decimal(price) / Decimal(10**decimals)
    # print(f"ETH/USD Price: ${price_usd}")
    return price_usd 