import os
from decimal import Decimal
from typing import Optional
from web3 import Web3
from exchanges.aave import AaveProtocol
from exchanges.hyperliquid import HyperliquidExchange, deposit_usdc_to_hyperliquid
from utils.calculations import calculate_net_apy
from exchanges.oracles import get_eth_price
from exchanges.aave_test import get_reserves_data
import logging
import asyncio

logger = logging.getLogger(__name__)

class DeltaNeutralExecutor:
    def __init__(
        self,
        aave: AaveProtocol,
        hyperliquid: HyperliquidExchange,
        web3: Web3
    ):
        self.aave = aave
        self.hyperliquid = hyperliquid
        self.web3 = web3
        self.min_profitability = float(os.getenv("MIN_GLOBAL_PROFITABILITY", "2"))  # 200%
        self.borrow_perc_of_ltv = float(os.getenv("BORROW_PERC_OF_LTV", "0.5"))  # 50%
        self.initial_usdc = float(os.getenv("INITIAL_USDC", "1000"))  # Initial USDC amount
        self.swap_percentage = float(os.getenv("SWAP_PERCENTAGE", "0.1"))  # 10%
        self.USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC on Arbitrum
        
    async def should_execute(self, simulated_apy: float) -> bool:
        """Check if strategy should be executed based on simulated APY"""
        min_profitability = self.min_profitability * 100
        logger.info(f"Checking if {simulated_apy:.2f}% > {min_profitability:.2f}%")
        return simulated_apy > min_profitability
    
    async def execute_strategy(self) -> bool:
        try:
            # 1. Swap USDC to ETH
            usdc_to_swap = int(self.initial_usdc * self.swap_percentage * 10**6)  # Convert to USDC decimals
            eth_price = float(get_eth_price(self.web3))
            min_eth_amount = int((Decimal(str(usdc_to_swap)) / Decimal(10**6) / Decimal(str(eth_price)) * Decimal('0.995')) * Decimal(10**18))
            
            print(f"\n1. Swapping {usdc_to_swap/10**6} USDC to ETH...")
            swap_receipt = await self.aave.swap_usdc_to_eth(
                amount=usdc_to_swap,
                min_amount_out=min_eth_amount
            )
            logger.info(f"Swap tx hash: {swap_receipt['transactionHash'].hex()}")
            
            # 2. Supply only the ETH we got from swap
            eth_to_supply = min_eth_amount  # Use the exact amount we got from swap
            print(f"\n2. Supplying {eth_to_supply/10**18:.6f} ETH as collateral...")
            supply_receipt = await self.aave.supply_eth(eth_to_supply)
            logger.info(f"Supply tx hash: {supply_receipt['transactionHash'].hex()}")
            
            # 3. Borrow USDC using BORROW_PERC_OF_LTV * LTV
            # Get ETH LTV from reserves
            reserves = get_reserves_data()
            weth = next((r for r in reserves if r['symbol'] == 'WETH'), None)
            eth_ltv = float(weth['ltv'])
            
            # Calculate borrow amount based on supplied ETH value and LTV
            eth_value_usd = (eth_to_supply / 10**18) * eth_price
            borrow_amount = int(eth_value_usd * eth_ltv * self.borrow_perc_of_ltv * 10**6)  # Convert to USDC decimals
            
            print(f"\n3. Borrowing {borrow_amount/10**6:.2f} USDC ({self.borrow_perc_of_ltv*100:.0f}% of {eth_ltv*100:.0f}% LTV)...")
            borrow_receipt = await self.aave.borrow_asset(
                asset_address=self.USDC,
                amount=borrow_amount,
                interest_rate_mode=2
            )
            logger.info(f"Borrow tx hash: {borrow_receipt['transactionHash'].hex()}")
            
            # 4. Deposit USDC to Hyperliquid
            print(f"\n4. Depositing {borrow_amount/10**6:.2f} USDC to Hyperliquid...")
            deposit_tx_hash = deposit_usdc_to_hyperliquid(Decimal(str(borrow_amount/10**6)))
            deposit_receipt = self.web3.eth.wait_for_transaction_receipt(deposit_tx_hash)
            logger.info(f"Deposit tx hash: {deposit_tx_hash}")
            
            # Wait for deposit to be available
            print("\nWaiting for Hyperliquid deposit to be available...")
            max_retries = 30
            for _ in range(max_retries):
                hl_balance = self.hyperliquid.info.user_state(self.hyperliquid.wallet_address)
                if float(hl_balance.get('marginSummary', {}).get('accountValue', 0)) >= borrow_amount/10**6:
                    break
                await asyncio.sleep(1)
            
            # 5. Open short position on Hyperliquid
            eth_to_short = eth_to_supply / 10**18  # Use same amount as supplied
            
            # Get metadata for size decimals
            meta = self.hyperliquid.info.meta()
            sz_decimals = {}
            for asset_info in meta["universe"]:
                sz_decimals[asset_info["name"]] = asset_info["szDecimals"]
            
            # Round size according to ETH decimals
            eth_to_short = round(eth_to_short, sz_decimals["ETH"])
            
            print(f"\n5. Opening {eth_to_short:.6f} ETH short position on Hyperliquid...")
            order_result = self.hyperliquid.exchange.market_open(
                name="ETH",
                is_buy=False,  # short
                sz=eth_to_short,
                slippage=0.01  # 1% slippage
            )
            
            if order_result and order_result.get('status') == 'ok':
                for status in order_result["response"]["data"]["statuses"]:
                    try:
                        filled = status["filled"]
                        logger.info(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                    except KeyError:
                        logger.error(f'Error: {status["error"]}')
                        return False
                logger.info("Strategy executed successfully")
                return True
            else:
                logger.error("Failed to open Hyperliquid position")
                return False
            
        except Exception as e:
            logger.error(f"Error executing strategy: {e}")
            return False 