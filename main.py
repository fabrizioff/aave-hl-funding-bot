import os
import json
import asyncio
from dotenv import load_dotenv, find_dotenv
from config import Config
from exchanges.hyperliquid import HyperliquidExchange
import logging
from utils.monitoring import PositionMonitor
from utils.web3_utils import web3, init_web3  
from decimal import Decimal
from tabulate import tabulate
import time
import sys
from pathlib import Path
import warnings
from utils.calculations import calculate_net_apy
from exchanges.aave_test import get_user_data, get_reserves_data
from exchanges.oracles import get_eth_price
from strategies.delta_neutral_executor import DeltaNeutralExecutor
from exchanges.aave import AaveProtocol
from exchanges.config.addresses import USDC_ADDRESS

# Add the project root to Python path
root_path = str(Path(__file__).parent)
if root_path not in sys.path:
    sys.path.append(root_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MainScript")

# Load environment variables
env_path = find_dotenv()
if not env_path:
    raise ValueError("Could not find .env file")

load_dotenv(env_path)

warnings.filterwarnings('ignore', message='.*ChainId.*')

class ProtocolDataManager:
    def __init__(self):
        self.hl_data = {}
        self.aave_data = {}
        self.last_update = None
        self.position_monitor = None
        self.hyperliquid = None
        self.aave = None
        self.is_hl_ready = asyncio.Event()
        self.is_aave_ready = asyncio.Event()

    async def initialize_hyperliquid(self):
        """Initialize Hyperliquid connection"""
        self.hyperliquid = HyperliquidExchange()
        self.position_monitor = PositionMonitor(self.aave, self.hyperliquid)
        
        # Set up ws handlers for hyperliquid
        self.hyperliquid.add_order_update_handler(self._handle_order_update)
        self.hyperliquid.add_trade_update_handler(self._handle_trade_update)
        self.hyperliquid.add_active_asset_data_handler(self._handle_asset_update)
        self.hyperliquid.add_account_update_handler(self._handle_account_update)
        
        # Wait for WebSocket connection
        await self.hyperliquid.ws_handler.wait_for_connection()
        self.is_hl_ready.set()

    async def initialize_aave(self):
        """Initialize Aave connection"""
        pool_address = os.getenv("AAVE_POOL_ADDRESS")
        wallet_address = os.getenv("WALLET_ADDRESS")
        private_key = os.getenv("WALLET_PVT_KEY")
        
        if not all([pool_address, wallet_address, private_key]):
            raise ValueError("Missing required Aave configuration in .env")
        
        self.aave = AaveProtocol(
            web3=web3,
            pool_address=web3.to_checksum_address(pool_address),
            wallet_address=web3.to_checksum_address(wallet_address),
            private_key=private_key
        )
        self.is_aave_ready.set()

    def update_aave_data(self, wallet_address):
        """Update Aave data"""
        self.aave_data = get_user_data(wallet_address)
        self.last_update = time.time()

    def update_hl_data(self, data):
        """Update Hyperliquid data"""
        self.hl_data = data
        self.last_update = time.time()

    def _handle_order_update(self, msg):
        """Handle order updates from Hyperliquid"""
        pass

    def _handle_trade_update(self, msg):
        """Handle trade updates from Hyperliquid"""
        pass

    def _handle_asset_update(self, msg):
        """Handle asset context updates from Hyperliquid"""
        self.position_monitor.update_asset_context(msg)

    def _handle_account_update(self, msg):
        """Handle account state updates from Hyperliquid"""
        if "clearinghouseState" in msg:
            self.position_monitor.update_state(msg)
            self.position_monitor.process_position_data()
            self.hl_data = {
                'positions': self.position_monitor.get_position_info(),
                'total_position_usd': sum(pos.position_usd for pos in self.position_monitor.positions.values()),
                'total_notional_usd': sum(pos.notional_usd for pos in self.position_monitor.positions.values()),
                'weighted_funding_rate': sum(pos.current_funding_rate * pos.notional_usd for pos in self.position_monitor.positions.values()) / 
                                       (sum(pos.notional_usd for pos in self.position_monitor.positions.values()) if self.position_monitor.positions else 1),
                'weighted_funding_apr': sum(pos.funding_apy * pos.notional_usd for pos in self.position_monitor.positions.values()) / 
                                      (sum(pos.notional_usd for pos in self.position_monitor.positions.values()) if self.position_monitor.positions else 1)
            }

    async def wait_for_ready(self):
        """Wait for both protocols to be ready"""
        await asyncio.gather(
            self.is_hl_ready.wait(),
            self.is_aave_ready.wait()
        )

    def has_open_positions(self) -> bool:
        """Check if there are any open positions"""
        has_hl_positions = bool(self.position_monitor.positions)
        has_aave_positions = bool(self.aave_data and any(
            pos['supply_balance'] > 0 or pos['borrow_balance'] > 0
            for pos in self.aave_data.get('reserves', [])
        ))
        return has_hl_positions or has_aave_positions

class DisplayManager:
    def __init__(self):
        self.last_display_time = 0
        self.update_interval = 1  # seconds

    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def display_all(self, data_manager):
        """Display all information with screen clearing"""
        current_time = time.time()
        if current_time - self.last_display_time >= self.update_interval:
            self.clear_screen()
            print(f"\n=== Last Update: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            
            # Display Hyperliquid positions
            self.print_hl_positions(data_manager.hl_data)
            
            # Display Aave positions
            self.print_aave_positions(data_manager.aave_data)
            
            # Display global metrics
            self.print_global_metrics(data_manager)
            
            # Display reserves info
            self.print_reserves_info(data_manager.aave_data, data_manager)
            
            self.last_display_time = current_time

    @staticmethod
    def print_hl_positions(hl_data):
        positions = hl_data.get('positions', {})
        
        # Print timestamp with first table header
        print(f"\nLast Update: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n=== Hyperliquid Positions ===")
        
        if not positions:
            print("\nNo open Hyperliquid positions")
            return

        positions_table = [[
            pos.coin,
            f"{pos.size:,.4f}",
            f"${pos.entry_price:,.2f}",
            f"${pos.current_mark_price:,.2f}",
            f"${pos.notional_usd:,.2f}",
            f"${pos.position_usd:,.2f}",
            f"{pos.leverage}x",
            f"${pos.liquidation_price:,.2f}",
            f"${pos.unrealized_pnl:,.2f}",
            f"{pos.funding['currentRate']:.4%}",
            f"{pos.funding['projectedApy']:.2f}%",
            f"${pos.funding['sinceOpen']:.4f}",
            f"${pos.risk_metrics['margin_buffer']:,.2f}",
            f"{pos.risk_metrics['buffer_percentage']:.2f}%"
        ] for pos in positions.values()]
        
        # Add totals row if there are positions
        if positions:
            total_position_usd = hl_data['total_position_usd']
            total_notional_usd = hl_data['total_notional_usd']
            total_cum_funding = sum(pos.funding['sinceOpen'] for pos in positions.values())
            total_upnl = sum(pos.unrealized_pnl for pos in positions.values())
            
            positions_table.append([
                "TOTAL",
                "",
                "",
                "",
                f"${total_notional_usd:,.2f}",
                f"${total_position_usd:,.2f}",
                "",
                "",
                f"${total_upnl:,.2f}",
                f"{hl_data['weighted_funding_rate']:.4%}",
                f"{hl_data['weighted_funding_apr']:.2f}%",
                f"${total_cum_funding:.4f}",
                "",
                ""
            ])
        
        print(tabulate(
            positions_table,
            headers=[
                'Asset',
                'Sz',
                'EntryPx',
                'MarkPx',
                'Notional',
                'Position@Mkt',
                'Leverage',
                'Liq. Px',
                'UPnL',
                'FR',
                'FR APR',
                'Funding Since Open',
                'Margin Buffer',
                'Buffer %'
            ],
            tablefmt='grid',
            colalign=('left', 'right', 'right', 'right', 'right', 'right', 'right', 'right', 
                     'right', 'right', 'right', 'right', 'right', 'right')
        ))

        # Print liquidation warnings if any
        for position in positions.values():
            if position.risk_metrics['is_near']:
                print(f"\n⚠️ WARNING: {position.coin} position near liquidation!")

    @staticmethod
    def print_aave_positions(aave_data):
        if not aave_data:
            print("\nNo Aave data available")
            return

        active_positions = [pos for pos in aave_data['reserves'] 
                          if pos['supply_balance'] > 0 or pos['borrow_balance'] > 0]
        
        print("\n=== Active Aave Positions ===")
        
        if not active_positions:
            print("No open Aave positions")
            return
        
        positions_table = [[
            pos['symbol'],
            f"{pos['supply_balance']:.4f}",
            f"${pos['supply_usd']:.2f}",
            f"{pos['supply_apy']*100:.2f}%",
            f"{pos['borrow_balance']:.4f}",
            f"${pos['borrow_usd']:.2f}",
            f"{pos['borrow_apy']*100:.2f}%",
            f"${pos['supply_usd'] - pos['borrow_usd']:.2f}",
            "-",  # Health Factor (only shown in total)
            "-"   # Net APY (only shown in total)
        ] for pos in active_positions]
        
        # Add totals row
        positions_table.append([
            "TOTAL",
            "",
            f"${aave_data['total_supply_usd']:.2f}",
            f"{aave_data['earned_apy']*100:.2f}%",
            "",
            f"${aave_data['total_borrow_usd']:.2f}",
            f"{aave_data['debt_apy']*100:.2f}%",
            f"${aave_data['net_worth_usd']:.2f}",
            f"{aave_data['health_factor']:.2f}",
            f"{aave_data['net_apy']*100:.2f}%"
        ])
        
        print(tabulate(
            positions_table,
            headers=['Asset', 'Supply', 'Supply USD', 'Supply APY', 
                    'Borrow', 'Borrow USD', 'Borrow APY', 'Net Worth USD',
                    'Health Factor', 'Net APY'],
            tablefmt='grid',
            colalign=('left', 'right', 'right', 'right', 'right', 'right', 
                     'right', 'right', 'right', 'right')
        ))

    @staticmethod
    def print_global_metrics(data_manager):
        if data_manager.aave_data and data_manager.position_monitor:
            eth_position = next((pos for pos in data_manager.aave_data['reserves'] 
                               if pos['symbol'] == 'WETH'), None)
            usdc_position = next((pos for pos in data_manager.aave_data['reserves']
                                if pos['asset'].lower() == USDC_ADDRESS.lower()), None)
            eth_hl_position = data_manager.position_monitor.positions.get('ETH')
            
            if eth_position and usdc_position and eth_hl_position:
                # Use actual values from positions
                eth_supply_usd = float(eth_position['supply_usd'])
                usdc_borrow_usd = float(usdc_position['borrow_usd'])
                # logger.info(f"USDC borrow USD: ${usdc_borrow_usd:,.2f}")
                
                # Use actual APYs from positions
                eth_supply_earnings = eth_supply_usd * float(eth_position['supply_apy'])
                usdc_borrow_cost = usdc_borrow_usd * float(usdc_position['borrow_apy'])
                hl_funding_earnings = float(-eth_hl_position.notional_usd) * (eth_hl_position.funding_apy/100)
                # logger.info(f"ETH supply earnings: ${eth_supply_earnings:,.2f}")
                # logger.info(f"USDC borrow cost: ${usdc_borrow_cost:,.2f}")
                # logger.info(f"HL funding earnings: ${hl_funding_earnings:,.2f}")
                
                # Calculate net profit and APY based on initial capital (ETH supply)
                net_profit_usd = eth_supply_earnings - usdc_borrow_cost + hl_funding_earnings
                global_net_apy = (net_profit_usd / (eth_supply_usd - usdc_borrow_usd)) * 100
                
                metrics_table = [[
                    # f"{eth_hl_position.funding_apy:.2f}%",
                    # f"{float(data_manager.aave_data['net_apy'])*100:.2f}%",
                    f"{global_net_apy:.2f}%",
                    f"{net_profit_usd:,.2f}"
                ]]
                
                print("\n=== Total Annualized Return ===")
                print(tabulate(
                    metrics_table,
                    headers=['E[Net Return (%)]', 'E[Net Profit (USD)]'],
                    tablefmt='grid',
                    colalign=('right', 'right')
                ))

    @staticmethod
    def print_reserves_info(aave_data, data_manager):
        """Print all available Aave reserves and their info"""
        reserves = get_reserves_data()
        filtered_reserves = [r for r in reserves if r['symbol'] in ['WETH', 'USDC']]
        
        reserves_table = [[
            reserve['symbol'],
            f"{float(reserve['liquidity_rate'])*100:.2f}% / {float(reserve['liquidity_apy'])*100:.2f}%",
            f"{float(reserve['variable_borrow_rate'])*100:.2f}% / {float(reserve['variable_borrow_apy'])*100:.2f}%",
            "Yes" if reserve['collateral_enabled'] else "No",
            "Yes" if reserve['borrowing_enabled'] else "No",
            f"{float(reserve['ltv'])*100:.0f}%",
            f"{float(reserve['liquidation_threshold'])*100:.0f}%",
            f"{float(reserve['liquidation_bonus'])*100:.0f}%"
        ] for reserve in filtered_reserves]
        
        print("\n=== Aave Filtered Markets ===")
        print(tabulate(
            reserves_table,
            headers=[
                'Asset',
                'Supply APR/APY',
                'Borrow APR/APY',
                'Collateral',
                'Borrowable',
                'LTV',
                'Liq.Thresh',
                'Liq.Bonus'
            ],
            tablefmt='grid',
            colalign=('left', 'right', 'right', 'center', 'center', 'right', 'right', 'right')
        ))
        
        # Calculate optimal strategy APY
        weth = next((r for r in filtered_reserves if r['symbol'] == 'WETH'), None)
        usdc = next((r for r in filtered_reserves if r['symbol'] == 'USDC'), None)
        
        if weth and usdc:
            eth_price = float(get_eth_price(web3))
            weth_supply_apy = float(weth['liquidity_apy'])
            weth_ltv = float(weth['ltv'])
            usdc_borrow_apy = float(usdc['variable_borrow_apy'])
            
            # For 1 WETH supplied:
            eth_supply_usd = eth_price  # Value of 1 ETH in USD
            borrow_perc_of_ltv = float(os.getenv("BORROW_PERC_OF_LTV"))
            usdc_borrow_usd = eth_price * borrow_perc_of_ltv * weth_ltv
            
            # Calculate earnings/costs based on USD values
            eth_supply_earnings = eth_supply_usd * weth_supply_apy  # Earnings from ETH supply
            usdc_borrow_cost = usdc_borrow_usd * usdc_borrow_apy   # Cost of USDC borrow
            
            # Get funding rate from Hyperliquid
            if data_manager.position_monitor:
                eth_funding = data_manager.position_monitor.get_funding_rate("ETH")
                if eth_funding is not None:
                    funding_apy = data_manager.position_monitor.calculator.calculate_apy(
                        eth_funding, 
                        payments_per_year=8760,
                        compound=False
                    )
                    hl_funding_earnings = eth_supply_usd * (funding_apy/100)  
                    
                    # Calculate net profit in USD
                    net_profit_usd = eth_supply_earnings - usdc_borrow_cost + hl_funding_earnings
                    
                    # Calculate net APY based on initial capital (1 ETH value)
                    net_apy_usd = (net_profit_usd / (eth_supply_usd - usdc_borrow_usd)) * 100
                    
                    # Calculate using the original net_apy function for comparison
                    net_apy_weighted = calculate_net_apy(
                        weth_supply_apy,
                        usdc_borrow_apy,
                        eth_supply_usd,
                        usdc_borrow_usd
                    ) * 100
                    
                    print(f"\nStrategy Breakdown (1 WETH @ ${eth_price:.2f}):")
                    print(f"ETH Supply APY: {weth_supply_apy*100:.2f}% (${eth_supply_earnings:.2f})")
                    print(f"USDC Borrow APY ({borrow_perc_of_ltv*100:.0f}% of {weth_ltv*100:.0f}% LTV): {usdc_borrow_apy*100:.2f}% (${usdc_borrow_cost:.2f})")
                    print(f"Net Aave APY (weighted method): {net_apy_weighted:.2f}%")
                    print(f"HL Funding Rate: {eth_funding:.6%} (hourly) / {funding_apy:.2f}% (${hl_funding_earnings:.2f})")
                    print(f"Global Net APY (USD method): {net_apy_usd:.2f}% (${net_profit_usd:.2f})")

async def main():
    try:
        data_manager = ProtocolDataManager()
        display_manager = DisplayManager()
        strategy_executed = False
        
        print("Initializing connections...")
        await asyncio.gather(
            data_manager.initialize_hyperliquid(),
            data_manager.initialize_aave()
        )
        
        executor = DeltaNeutralExecutor(
            aave=data_manager.aave,
            hyperliquid=data_manager.hyperliquid,
            web3=web3
        )
        
        print("Waiting for initial data...")
        await data_manager.wait_for_ready()
        print("All data sources ready!")
        
        await asyncio.sleep(2)  # Give time to read initialization messages
        
        while True:
            try:
                data_manager.update_aave_data(os.getenv("WALLET_ADDRESS"))
                
                # Use the new display method
                display_manager.display_all(data_manager)
                
                await data_manager.position_monitor.monitor_liquidation_risk()
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                if data_manager.hyperliquid.ws_handler:
                    await data_manager.hyperliquid.ws_handler._reconnect()
                    
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 