from web3 import Web3

# Contract addresses for different networks
BASE_MAINNET = {
    'ui_pool_data_provider': '0x68100bD5345eA474D93577127C11F39FF8463e93',
    'pool_addresses_provider': '0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D',
    'eth_usd_oracle': '0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70',
} 

ARBITRUM_MAINNET = {
    'ui_pool_data_provider': '0x5c5228aC8BC1528482514aF3e27E692495148717',
    'pool_addresses_provider': '0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb',
    'eth_usd_oracle': '0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612'
} 

# Arbitrum Mainnet addresses
USDC_ADDRESS = Web3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")  # USDC.e on Arbitrum
HYPERLIQUID_BRIDGE = Web3.to_checksum_address("0x2df1c51e09aecf9cacb7bc98cb1742757f163df7")