from asyncio.log import logger
from decimal import Decimal
from typing import Dict, Any

def calculate_net_apy(
    supply_apy: float,
    borrow_apy: float,
    supply_usd: float,
    borrow_usd: float
) -> float:
    """Calculate net APY using Aave's formula
    
    Args:
        supply_apy: Supply APY as decimal (e.g., 0.05 for 5%)
        borrow_apy: Borrow APY as decimal
        supply_usd: Total USD value of supplied assets
        borrow_usd: Total USD value of borrowed assets
        
    Returns:
        Net APY as decimal
    """
    net_worth_usd = supply_usd - borrow_usd
    if net_worth_usd <= 0:
        return 0.0
    
    return (supply_apy * (supply_usd / net_worth_usd)) - \
           (borrow_apy * (borrow_usd / net_worth_usd))

class PositionCalculator:
    @staticmethod
    def calculate_optimal_position_size(collateral: float, ltv: float):
        pass
    
    @staticmethod
    def calculate_apy(
        rate: float, 
        payments_per_year: int = 24 * 365,  # Default for hourly payments (24*365)
        compound: bool = True
    ) -> float:
        """
        Calculate APY from a periodic rate
        
        Args:
            rate: The periodic rate (e.g., hourly funding rate)
            payments_per_year: Number of payments per year (default 8760 for hourly)
            compound: Whether to use compound interest calculation (default True)
            
        Returns:
            Annualized percentage yield
        """
        try:
            if compound:
                # Compound interest formula: APY = (1 + r/n)^n - 1
                # where r is annual rate and n is number of compounds per year
                annual_rate = rate * payments_per_year
                annual_yield = (1 + annual_rate/payments_per_year) ** payments_per_year - 1
            else:
                # Simple interest: APR = rate * payments_per_year
                annual_yield = rate * payments_per_year
                
            return annual_yield * 100  # Convert to percentage
            
        except Exception as e:
            logger.error(f"Error calculating the annual yield: {e}")
            return 0.0


    @staticmethod
    def calculate_maintenance_margin(max_leverage: int) -> float:
        """
        Calculate maintenance margin based on max leverage
        maintenance_margin = 50% * (1/max_leverage)
        """
        return (1 / max_leverage) * 0.5

    @staticmethod
    def calculate_liquidation_threshold(
        total_open_position_usd: float, 
        max_leverage: int
    ) -> float:
        """
        Calculate liquidation threshold
        liquidation_threshold = maintenance_margin * total_open_position_usd
        """
        maintenance_margin = PositionCalculator.calculate_maintenance_margin(max_leverage)
        return maintenance_margin * total_open_position_usd

    @staticmethod
    def is_near_liquidation(
        account_value: float,
        total_open_position_usd: float,
        max_leverage: int,
        warning_threshold_pct: float = 10
    ) -> Dict[str, Any]:
        """
        Check if account value is near liquidation
        warning_threshold_pct: percentage buffer above liquidation threshold (default 10%)
        
        Returns:
            {
                'is_near': bool,
                'current_margin': float,  # Current margin percentage
                'maintenance_margin': float,  # Required maintenance margin
                'margin_buffer': float,  # How much buffer remains before liquidation
                'buffer_percentage': float  # Buffer as percentage of maintenance margin
            }
        """
        maintenance_margin = PositionCalculator.calculate_maintenance_margin(max_leverage)
        liquidation_threshold = PositionCalculator.calculate_liquidation_threshold(
            total_open_position_usd, max_leverage
        )
        
        margin_buffer = account_value - liquidation_threshold
        buffer_percentage = (margin_buffer / liquidation_threshold * 100) if liquidation_threshold > 0 else float('inf')
        
        return {
            'is_near': buffer_percentage < warning_threshold_pct,
            'maintenance_margin': maintenance_margin,
            'liquidation_threshold': liquidation_threshold,
            'margin_buffer': margin_buffer,
            'buffer_percentage': buffer_percentage
        }
