from asyncio.log import logger
import os
from eth_account.signers.local import LocalAccount
import eth_account
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange
import json
from .base import ExchangeInterface
from utils.websocket_handler import WebSocketHandler
from typing import Callable
from web3 import Web3
from decimal import Decimal
from .config.addresses import USDC_ADDRESS, HYPERLIQUID_BRIDGE

class HyperliquidExchange(ExchangeInterface):
    def __init__(self):
        self.base_url = constants.MAINNET_API_URL
        self.ws_handler = None
        self._init_connection()
        
    def _init_connection(self):
        try:
            private_key = os.getenv("API_WALLET_PVT_KEY")
            self.wallet_address = os.getenv("WALLET_ADDRESS")
            
            if not private_key or not self.wallet_address:
                raise ValueError("Missing WALLET_PVT_KEY or WALLET_ADDRESS in env")
            
            # Remove the 0x prefix if present in the private key
            private_key = private_key.replace('0x', '')
            
            self.account: LocalAccount = eth_account.Account.from_key(private_key)
            self.info = Info(self.base_url, skip_ws=True)
            self.exchange = Exchange(
                self.account, 
                self.base_url, 
                account_address=self.wallet_address
            )
            
            # Initialize WebSocket handler
            self.ws_handler = WebSocketHandler(self.wallet_address, self.base_url)
            
            print("Hyperliquid connection initialized with WebSocket")
        except Exception as e:
            raise Exception(f"Failed to initialize Hyperliquid connection: {str(e)}")

    async def get_position(self):
        pass
    
    async def get_open_positions(self):
        try:
            # Get the user state and print out position information
            user_state = self.info.user_state(self.wallet_address)
            positions = []
            for position in user_state["assetPositions"]:
                positions.append(position["position"])
            return positions
        except Exception as e:
            raise Exception(f"Failed to get positions: {str(e)}")

    async def open_limit_order(self, size: float, side: str, token: str = "ETH", price: float = 1100):
        try:
            # Place an order that should rest by setting the price
            is_buy = side.lower() == "long"
            return self.exchange.order(
                token, 
                is_buy, 
                size, 
                price,
                {"limit": {"tif": "Gtc"}}
            )
        except Exception as e:
            raise Exception(f"Failed to open position: {str(e)}")

    async def cancel_order(self, token: str, oid: str):
        try:
            # Cancel the order
            return self.exchange.cancel(token, oid)
        except Exception as e:
            raise Exception(f"Failed to cancel order: {str(e)}")

    async def query_order(self, oid: str):
        try:
            # Query the order status by oid
            return self.info.query_order_by_oid(self.wallet_address, oid)
        except Exception as e:
            raise Exception(f"Failed to query order: {str(e)}")

    # Required interface methods to be implemented
    async def get_market_price(self, token: str):
        pass

    async def close_position(self, size: float):
        pass

    async def get_funding_rate(self):
        pass
    
    async def get_leverage(self):
        pass
    
    async def adjust_leverage(self, target: float):
        pass

    # Add WebSocket-specific methods
    def add_order_update_handler(self, callback: Callable):
        """Add custom handler for order updates"""
        if self.ws_handler is None:
            raise Exception("WebSocket handler not initialized")
        self.ws_handler.add_custom_handler("OrderUpdates", callback)
    
    def add_trade_update_handler(self, callback: Callable):
        """Add custom handler for trade updates"""
        self.ws_handler.add_custom_handler("UserFills", callback)

    def add_active_asset_data_handler(self, callback: Callable):
        """Add custom handler for active asset data updates"""
        self.ws_handler.add_custom_handler("activeAssetCtx", callback)

    def add_account_update_handler(self, callback: Callable):
        """Add custom handler for account updates"""
        self.ws_handler.add_custom_handler("webData2", callback)

    def withdraw_usdc(self, amount_usd: float) -> dict:
        """
        Withdraw USDC from Hyperliquid bridge
        
        Args:
            amount_usd: Amount to withdraw in USD (minimum 5 USD)
        
        Returns:
            dict: Withdrawal response from Hyperliquid
        """
        try:
            # Verify we're using wallet's address (not an agent)
            if self.exchange.account_address != self.exchange.wallet.address:
                raise Exception("Agents cannot perform withdrawals")
            
            # Execute withdrawal
            result = self.exchange.withdraw_from_bridge(
                amount_usd, 
                self.wallet_address
            )
            
            return result
            
        except Exception as e:
            raise Exception(f"Failed to withdraw USDC: {str(e)}")

def deposit_usdc_to_hyperliquid(amount_usdc: Decimal) -> str:
    """
    Deposit USDC to Hyperliquid bridge
    
    Args:
        amount_usdc: Amount of USDC to deposit (in decimal)
    
    Returns:
        transaction hash
    """
    # Connect to Arbitrum
    web3 = Web3(Web3.HTTPProvider(
        os.getenv('ARBITRUM_RPC_URL') + os.getenv('ALCHEMY_API_KEY')
    ))

    # USDC has 6 decimals
    amount_wei = Web3.to_wei(amount_usdc, 'mwei')
    
    # Load wallet and ensure checksum address
    wallet_address = Web3.to_checksum_address(os.getenv('WALLET_ADDRESS'))
    private_key = os.getenv('WALLET_PVT_KEY')

    # USDC contract ABI - minimal for transfer
    usdc_abi = [{
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }]

    usdc_contract = web3.eth.contract(
        address=USDC_ADDRESS,
        abi=usdc_abi
    )

    # Estimate gas first
    estimated_gas = usdc_contract.functions.transfer(
        HYPERLIQUID_BRIDGE,
        amount_wei
    ).estimate_gas({'from': wallet_address})

    # Build transaction with proper gas settings
    tx = usdc_contract.functions.transfer(
        HYPERLIQUID_BRIDGE,
        amount_wei
    ).build_transaction({
        "from": wallet_address,
        "nonce": web3.eth.get_transaction_count(wallet_address),
        "gas": estimated_gas * 2,  # Double the estimated gas to be safe
        # Get current gas prices
        "maxFeePerGas": web3.eth.max_priority_fee + (2 * web3.eth.get_block('latest')['baseFeePerGas']),
        "maxPriorityFeePerGas": web3.eth.max_priority_fee,
        "type": 2  # EIP-1559 transaction
    })

    # Sign and send
    signed_tx = web3.eth.account.sign_transaction(tx, private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

    return web3.to_hex(tx_hash)

