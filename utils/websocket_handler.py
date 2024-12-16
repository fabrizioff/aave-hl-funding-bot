import asyncio
from typing import Callable, Dict, Any
from hyperliquid.info import Info
from hyperliquid.utils import constants
import logging
import websockets
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WebSocketHandler")

class WebSocketHandler:
    def __init__(self, wallet_address: str, base_url: str = constants.MAINNET_API_URL):
        self.wallet_address = wallet_address
        self.base_url = base_url.replace('https://', 'wss://') + '/ws'
        self.subscriptions = {}
        self.ws = None
        self.connected = asyncio.Event()
        self.running = True
        # Start connection
        asyncio.create_task(self._connect())
        
    async def _connect(self):
        while self.running:
            try:
                print("Initializing WebSocket connection...")
                async with websockets.connect(self.base_url, ping_interval=20, ping_timeout=20) as websocket:
                    self.ws = websocket
                    print("WebSocket connected successfully")
                    print("Subscribing to data feeds...")
                    self.connected.set()
                    
                    # Resubscribe to everything after connection
                    await self._subscribe_all()
                    print("Data feed subscriptions completed")
                    
                    # Listen for messages
                    while self.running:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)
                            await self._handle_message(data)
                        except websockets.exceptions.ConnectionClosed:
                            print("WebSocket connection closed, attempting to reconnect...")
                            break
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                            
            except Exception as e:
                print(f"WebSocket connection error, retrying... ({str(e)})")
                self.connected.clear()
                await asyncio.sleep(5)

    async def _subscribe_all(self):
        """Subscribe to all configured subscriptions"""
        if self.ws:
            # Subscribe to webData2 (account updates)
            await self.ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {
                    "type": "webData2",
                    "user": self.wallet_address
                }
            }))
            
            # Subscribe to funding
            await self.ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {
                    "type": "userFundings",
                    "user": self.wallet_address
                }
            }))
            
            # Only subscribe to ETH for now
            await self.ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {
                    "type": "activeAssetCtx",
                    "coin": "ETH"
                }
            }))
    
    async def _handle_message(self, message: Dict):
        """Handle incoming WebSocket messages"""
        try:
            channel = message.get("channel")
            if channel == "activeAssetCtx":
                if "data" in message and isinstance(message["data"], dict):
                    if "coin" in message["data"] and "ctx" in message["data"]:
                        if channel in self.subscriptions and message["data"]["coin"] in ["ETH", "BTC", "SOL"]:
                            self.subscriptions[channel](message["data"])
            elif channel in self.subscriptions:
                self.subscriptions[channel](message["data"])
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def add_custom_handler(self, subscription_type: str, callback: Callable):
        """Add custom message handler for a subscription type"""
        self.subscriptions[subscription_type] = callback

    async def wait_for_connection(self):
        """Wait for WebSocket to connect"""
        await self.connected.wait()

    async def _reconnect(self):
        """Explicitly trigger a reconnection"""
        self.connected.clear()
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
        self.ws = None
        # Connection will be re-established by the _connect loop

    def __del__(self):
        """Cleanup when object is destroyed"""
        self.running = False


