from asyncio.log import logger
from exchanges.aave import AaveProtocol
from exchanges.hyperliquid import HyperliquidExchange
from utils.calculations import PositionCalculator
from typing import Optional, Dict, Any
from dataclasses import dataclass
from decimal import Decimal
import asyncio
import os
import time
from utils.web3_utils import web3
from exchanges.aave_test import get_user_data

@dataclass
class PositionInfo:
    coin: str
    position_usd: float
    notional_usd: float
    max_leverage: int
    account_value: float
    liquidation_price: float
    entry_price: float
    size: float
    leverage: int
    unrealized_pnl: float
    funding: Dict[str, float]
    risk_metrics: Dict[str, Any]
    funding_apy: float
    current_funding_rate: float
    current_mark_price: float

class PositionMonitor:
    def __init__(self, aave: AaveProtocol, hyperliquid: HyperliquidExchange):
        self.aave = aave
        self.hyperliquid = hyperliquid
        self.calculator = PositionCalculator()
        self.latest_state: Optional[Dict] = None
        self.asset_contexts: Dict[str, Dict] = {}  # Store activeAssetCtx data by coin
        self.positions: Dict[str, PositionInfo] = {}
    
    def update_state(self, msg):
        """Update account state from webData2"""
        self.latest_state = msg
    
    def update_asset_context(self, data: Dict):
        """Update asset context from activeAssetCtx"""
        coin = data["coin"]
        self.asset_contexts[coin] = {
            "funding": float(data["ctx"]["funding"]),
            "markPx": float(data["ctx"]["markPx"])
        }
        
    def get_funding_rate(self, coin: str) -> float:
        """Get current funding rate for a coin"""
        if coin in self.asset_contexts:
            return float(self.asset_contexts[coin]["funding"])
        return 0.0
    
    def get_mark_price(self, coin: str) -> float:
        """Get current mark price for a coin"""
        if coin in self.asset_contexts:
            return float(self.asset_contexts[coin]["markPx"])
        return 0.0
    
    def process_position_data(self) -> None:
        """Process and store position data from latest state"""
        if not self.latest_state:
            logger.warning("No account state data available yet")
            return
        
        ch_state = self.latest_state.get("clearinghouseState")
        if not ch_state:
            logger.warning("No clearinghouse state found")
            return
        
        # Clear existing positions - important to remove closed positions
        self.positions = {}
        
        # Only process positions that exist in assetPositions
        for position in ch_state.get("assetPositions", []):
            pos = position.get("position")
            if not pos:
                continue
            
            coin = pos.get("coin")
            size = float(pos.get("szi", 0))
            
            # Skip if position size is 0 (closed position)
            if size == 0:
                continue
            
            # Rest of the processing...
            current_funding_rate = self.get_funding_rate(coin)
            current_mark_price = self.get_mark_price(coin)
            adjusted_funding_rate = -current_funding_rate if size > 0 else current_funding_rate
            
            # Calculate projected APY from adjusted funding rate
            funding_apy = self.calculator.calculate_apy(
                adjusted_funding_rate,
                payments_per_year=8760,  # Hourly payments
                compound=False
            )
            
            # Extract position values
            position_usd = float(pos["positionValue"])
            notional_usd = size * float(pos["entryPx"])
            max_leverage = int(pos["maxLeverage"])
            account_value = float(ch_state["marginSummary"]["accountValue"])
            liquidation_price = float(pos["liquidationPx"]) if pos["liquidationPx"] else 0
            entry_price = float(pos["entryPx"])
            leverage = int(float(pos["leverage"]["value"]))
            unrealized_pnl = float(pos["unrealizedPnl"])
            
            # Calculate risk metrics
            risk_metrics = self.calculator.is_near_liquidation(
                account_value=account_value,
                total_open_position_usd=position_usd, # check this
                max_leverage=max_leverage,
                warning_threshold_pct=10
            )
            
            # Get cumulative funding values
            since_open_funding = float(pos["cumFunding"]["sinceOpen"])
            # Adjust sinceOpen funding: positive means cost, negative means reward
            adjusted_since_open = -since_open_funding
            
            # Store funding info with adjusted rates
            funding_info = {
                'allTime': float(pos["cumFunding"]["allTime"]),
                'sinceOpen': adjusted_since_open,  # Store adjusted value
                'sinceChange': float(pos["cumFunding"]["sinceChange"]),
                'currentRate': adjusted_funding_rate,
                'projectedApy': funding_apy
            }
            
            # Store position info
            self.positions[coin] = PositionInfo(
                coin=coin,
                position_usd=position_usd,
                notional_usd=notional_usd,
                max_leverage=max_leverage,
                account_value=account_value,
                liquidation_price=liquidation_price,
                entry_price=entry_price,
                size=size,
                leverage=leverage,
                unrealized_pnl=unrealized_pnl,
                funding=funding_info,
                risk_metrics=risk_metrics,
                funding_apy=funding_apy,
                current_funding_rate=adjusted_funding_rate,
                current_mark_price=current_mark_price
            )

    async def monitor_liquidation_risk(self, warning_threshold_pct: float = 10):
        """Only monitor liquidation risk using existing position data"""
        try:
            for coin, position in self.positions.items():
                if position.risk_metrics['is_near']:
                    self._log_liquidation_warning(position)
                    
        except Exception as e:
            logger.error(f"Error monitoring liquidation risk: {e}")
    
    def _log_liquidation_warning(self, position: PositionInfo):
        """Log liquidation warning for a position"""
        logger.warning(f"""
            LIQUIDATION RISK ALERT for {position.coin}:
            Account Value: ${position.account_value}
            Position Value: ${position.position_usd}
            Required Maintenance Margin: {position.risk_metrics['maintenance_margin']:.2%}
            Liquidation Threshold: ${position.risk_metrics['liquidation_threshold']:.2f}
            Current Buffer: ${position.risk_metrics['margin_buffer']:.2f}
            Buffer Percentage: {position.risk_metrics['buffer_percentage']:.2f}%
            Liquidation Price: ${position.liquidation_price}
        """)
    
    def get_funding_info(self, coin: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """Get funding info for one or all positions"""
        if coin:
            return {coin: self.positions[coin].funding} if coin in self.positions else {}
        return {coin: pos.funding for coin, pos in self.positions.items()}
    
    def get_risk_metrics(self, coin: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get risk metrics for one or all positions"""
        if coin:
            return {coin: self.positions[coin].risk_metrics} if coin in self.positions else {}
        return {coin: pos.risk_metrics for coin, pos in self.positions.items()}
    
    def get_position_info(self, coin: Optional[str] = None) -> Dict[str, PositionInfo]:
        """Get full position info for one or all positions"""
        if coin:
            return {coin: self.positions[coin]} if coin in self.positions else {}
        return self.positions

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
        self.position_monitor.update_state(msg)
        self.position_monitor.process_position_data()
        self.hl_data = self.position_monitor.get_position_info()

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
