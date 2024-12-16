from abc import ABC, abstractmethod

class ExchangeInterface(ABC):
    @abstractmethod
    async def get_position(self):
        """Get current position details"""
        pass
    
    @abstractmethod
    async def get_market_price(self, token: str):
        """Get current market price"""
        pass
    
    @abstractmethod
    async def open_limit_order(self, size: float, side: str):
        """Open long/short limit position"""
        pass
    
    @abstractmethod
    async def close_position(self, size: float):
        """Close position"""
        pass 