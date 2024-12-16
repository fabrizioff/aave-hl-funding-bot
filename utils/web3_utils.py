import os
from web3 import Web3
from dotenv import load_dotenv, find_dotenv

# Load environment variables first
env_path = find_dotenv()
if not env_path:
    raise ValueError("Could not find .env file")
load_dotenv(env_path)

def init_web3():
    """Initialize Web3 connection"""
    alchemy_api_key = os.getenv("ALCHEMY_API_KEY")
    if not alchemy_api_key:
        raise ValueError("ALCHEMY_API_KEY not found in environment variables")
    arbitrum_mainnet_url = f"https://arb-mainnet.g.alchemy.com/v2/{alchemy_api_key}"
    return Web3(Web3.HTTPProvider(arbitrum_mainnet_url))

# Initialize a global web3 instance
web3 = init_web3() 