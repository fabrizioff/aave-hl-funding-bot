from hyperliquid.utils import constants

class Config:
    # Network settings
    RPC_URL = ""
    PRIVATE_KEY = ""
    
    # Protocol settings
    AAVE_POOL = ""
    HYPERLIQUID_API = ""
    
    # Strategy parameters
    TARGET_LTV = 0.7
    MIN_PROFIT_THRESHOLD = 0.02
    REBALANCE_THRESHOLD = 0.05
    MAX_SLIPPAGE = 0.001
    
    # Assets
    COLLATERAL_TOKEN = "USDC"
    BORROW_TOKEN = "ETH" 
    
    # Hyperliquid settings
    HYPERLIQUID_MAINNET_API = constants.MAINNET_API_URL
    HYPERLIQUID_DEFAULT_TOKEN = "ETH"
    HYPERLIQUID_DEFAULT_SIZE = 0.02
    HYPERLIQUID_DEFAULT_LEVERAGE = 1