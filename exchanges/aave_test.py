from asyncio.log import logger
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from utils.web3_utils import web3, init_web3  # Import from web3_utils instead of simulate

# Add the project root to Python path
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

from web3 import Web3
from web3.exceptions import ContractLogicError
from decimal import Decimal
from tabulate import tabulate
import time

# from exchanges.abi.aave_v3 import UI_POOL_DATA_PROVIDER_ABI, POOL_ADDRESSES_PROVIDER_ABI
from exchanges.abi.arbitrum_aave_v3 import UI_POOL_DATA_PROVIDER_ABI, POOL_ADDRESSES_PROVIDER_ABI
from exchanges.config.addresses import BASE_MAINNET, ARBITRUM_MAINNET
from exchanges.oracles import get_eth_price
from utils.calculations import calculate_net_apy

# Use addresses from config
ADDRESSES = ARBITRUM_MAINNET

def calculate_apy_from_apr(apr: Decimal) -> Decimal:
    """Convert APR to APY using compound interest formula
    APY = (1 + APR/n)^n - 1, where n is number of compounds per year
    Aave compounds every second"""
    compounds_per_year = Decimal('31536000')  # 365 days * 24 hours * 60 minutes * 60 seconds
    return (Decimal('1') + apr/compounds_per_year) ** compounds_per_year - Decimal('1')

def get_pool_address():
    provider_contract = web3.eth.contract(
        address=web3.to_checksum_address(ADDRESSES['pool_addresses_provider']),
        abi=POOL_ADDRESSES_PROVIDER_ABI
    )
    return provider_contract.functions.getPool().call()

def get_user_data(user_address):
    web3 = init_web3()  # Initialize web3 here
    ui_pool_data_provider = web3.eth.contract(
        address=web3.to_checksum_address(ADDRESSES['ui_pool_data_provider']),
        abi=UI_POOL_DATA_PROVIDER_ABI
    )
    
    try:
        # Get data
        user_reserves, emode = ui_pool_data_provider.functions.getUserReservesData(
            web3.to_checksum_address(ADDRESSES['pool_addresses_provider']),
            web3.to_checksum_address(user_address)
        ).call()
        
        # Get reserves data
        reserves_data = ui_pool_data_provider.functions.getReservesData(
            web3.to_checksum_address(ADDRESSES['pool_addresses_provider'])
        ).call()
        
        # Handle different response formats between Base and Arbitrum
        if isinstance(reserves_data, tuple):
            reserves_data = reserves_data[0]  # Base returns (reserves_data, base_currency_info)
        
        # Create maps for reserves_data
        reserve_info = {
            reserve[0]: {  # address of the underlyingAsset
                'symbol': reserve[2],  # symbol of the underlyingAsset
                'decimals': int(reserve[3]) if isinstance(reserve[3], (int, str)) else 18,  # default to 18 if invalid
                'variableBorrowIndex': Decimal(str(reserve[13])) / Decimal(10**27),
                'liquidityIndex': Decimal(str(reserve[12])) / Decimal(10**27),
                'liquidityRate': Decimal(str(reserve[14])) / Decimal(10**27),
                'variableBorrowRate': Decimal(str(reserve[15])) / Decimal(10**27),
                'price_in_usd': get_eth_price(web3) if reserve[2] == 'WETH' 
                               else Decimal('1') if reserve[2] in ['USDC', 'USDT', 'DAI'] 
                               else Decimal('0')
            }
            for reserve in reserves_data
        }
        
        # print(reserve_info)
        
        # Calculate yields
        total_supply_usd = Decimal('0')
        total_borrow_usd = Decimal('0')
        total_weighted_supply_apr = Decimal('0')
        total_weighted_borrow_apr = Decimal('0')
        
        formatted_reserves = []
        for reserve in user_reserves:
            asset = reserve[0] # address of the underlyingAsset
            info = reserve_info[asset] # info about the underlyingAsset

            scaledATokenBalance = Decimal(int(reserve[1]))
            scaledVariableDebt = Decimal(int(reserve[3]))
            
            supply_balance = (scaledATokenBalance * info['liquidityIndex']) / Decimal(10**info['decimals'])
            borrow_balance = (scaledVariableDebt * info['variableBorrowIndex']) / Decimal(10**info['decimals'])
            
            supply_usd = supply_balance * info['price_in_usd']
            borrow_usd = borrow_balance * info['price_in_usd']

            # print(info['price_in_usd'])
            
            # Update totals for yield calculation
            total_supply_usd += supply_usd
            total_borrow_usd += borrow_usd
            
            # Weight APRs by USD values
            if supply_usd > 0:
                total_weighted_supply_apr += info['liquidityRate'] * supply_usd
            if borrow_usd > 0:
                total_weighted_borrow_apr += info['variableBorrowRate'] * borrow_usd
            
            # Calculate APY from APR for this position
            supply_apy = calculate_apy_from_apr(info['liquidityRate'])
            borrow_apy = calculate_apy_from_apr(info['variableBorrowRate'])
            
            formatted_reserves.append({
                'asset': asset,
                'symbol': info['symbol'],
                'supply_balance': supply_balance,
                'supply_usd': supply_usd,
                'collateral_enabled': reserve[2],
                'borrow_balance': borrow_balance,
                'borrow_usd': borrow_usd,
                'supply_apr': info['liquidityRate'],
                'supply_apy': supply_apy,
                'borrow_apr': info['variableBorrowRate'],
                'borrow_apy': borrow_apy
            })
        
        # Calculate final APRs and APYs
        earned_apr = (total_weighted_supply_apr / total_supply_usd) if total_supply_usd > 0 else Decimal('0')
        debt_apr = (total_weighted_borrow_apr / total_borrow_usd) if total_borrow_usd > 0 else Decimal('0')
        
        earned_apy = calculate_apy_from_apr(earned_apr)
        debt_apy = calculate_apy_from_apr(debt_apr)
        
        # Calculate net worth and net APY
        net_worth_usd = total_supply_usd - total_borrow_usd
        if net_worth_usd > 0:
            # Calculate net APY using Aave's formula
            net_apy = calculate_net_apy(
                float(earned_apy),
                float(debt_apy),
                float(total_supply_usd),
                float(total_borrow_usd)
            )
        else:
            net_apy = Decimal('0')
        
        # Calculate health factor components
        total_collateral_usd = Decimal('0')
        total_weighted_threshold = Decimal('0')
        
        for reserve in user_reserves:
            asset = reserve[0]
            info = reserve_info[asset]
            is_collateral = reserve[2]
            
            # Get liquidation threshold from reserves_data
            liquidation_threshold = next(
                Decimal(int(r[5])) / Decimal(10**4)  # Convert from basis points
                for r in reserves_data 
                if r[0] == asset
            )
            
            scaledATokenBalance = Decimal(int(reserve[1]))
            supply_balance = (scaledATokenBalance * info['liquidityIndex']) / Decimal(10**info['decimals'])
            supply_usd = supply_balance * info['price_in_usd']
            
            if is_collateral:
                total_collateral_usd += supply_usd
                total_weighted_threshold += supply_usd * liquidation_threshold
        
        # Calculate health factor
        health_factor = (
            (total_weighted_threshold) / total_borrow_usd 
            if total_borrow_usd > 0 
            else Decimal('999999999')  # If no borrows, health factor is infinite
        )
        
        return {
            'reserves': formatted_reserves,
            'emode': emode,
            'total_supply_usd': total_supply_usd,
            'total_borrow_usd': total_borrow_usd,
            'net_worth_usd': net_worth_usd,
            'health_factor': health_factor,
            'earned_apr': earned_apr,
            'earned_apy': earned_apy,
            'debt_apr': debt_apr,
            'debt_apy': debt_apy,
            'net_apy': Decimal(str(net_apy))
        }
    except Exception as e:
        print(f"Error getting user data: {e}")
        return None

def get_reserves_data():
    web3 = init_web3()
    ui_pool_data_provider = web3.eth.contract(
        address=web3.to_checksum_address(ADDRESSES['ui_pool_data_provider']),
        abi=UI_POOL_DATA_PROVIDER_ABI
    )
    
    try:
        reserves_data = ui_pool_data_provider.functions.getReservesData(
            web3.to_checksum_address(ADDRESSES['pool_addresses_provider'])
        ).call()
        
        if isinstance(reserves_data, tuple):
            reserves_data = reserves_data[0]
        
        # Create a dict to track unique symbols
        seen_symbols = {}
        formatted_reserves = []
        
        NATIVE_USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        for reserve in reserves_data:
            symbol = reserve[2]
            asset_address = reserve[0]
            
            # For USDC, only take the native version
            if symbol == 'USDC':
                if asset_address.lower() != NATIVE_USDC.lower():
                    continue
            
            if symbol not in seen_symbols:
                seen_symbols[symbol] = True
                formatted_reserves.append({
                    'asset': asset_address,
                    'name': reserve[1],
                    'symbol': symbol,
                    'decimals': int(reserve[3]) if isinstance(reserve[3], (int, str)) else 18,
                    'ltv': Decimal(str(reserve[4])) / Decimal(10**4),
                    'liquidation_threshold': Decimal(str(reserve[5])) / Decimal(10**4),
                    'liquidation_bonus': (Decimal(str(reserve[6])) / Decimal(10**4)) - 1,
                    'reserve_factor': Decimal(str(reserve[7])) / Decimal(10**4),
                    'collateral_enabled': reserve[8],
                    'borrowing_enabled': reserve[9],
                    'is_active': reserve[10],
                    'is_frozen': reserve[11],
                    'liquidity_rate': Decimal(str(reserve[14])) / Decimal(10**27),
                    'liquidity_apy': calculate_apy_from_apr(Decimal(str(reserve[14])) / Decimal(10**27)),
                    'variable_borrow_rate': Decimal(str(reserve[15])) / Decimal(10**27),
                    'variable_borrow_apy': calculate_apy_from_apr(Decimal(str(reserve[15])) / Decimal(10**27))
                })
        
        return formatted_reserves
        
    except Exception as e:
        logger.error(f"Error getting reserves data: {e}")
        return []

def main():
    try:
        user_address = "0x2120930162210085838314efa84c0e7539d41a06"
        
        while True:
            # Get and format data
            user_data = get_user_data(user_address)
            
            # Add yield summary
            yield_summary = [
                ['Total Supply USD', f"${user_data['total_supply_usd']:.2f}"],
                ['Total Borrow USD', f"${user_data['total_borrow_usd']:.2f}"],
                ['Net Worth USD', f"${user_data['net_worth_usd']:.2f}"],
                ['Health Factor', f"{user_data['health_factor']:.2f}"],
                ['Earned APR/APY', f"{user_data['earned_apr']*100:.2f}% / {user_data['earned_apy']*100:.2f}%"],
                ['Debt APR/APY', f"{user_data['debt_apr']*100:.2f}% / {user_data['debt_apy']*100:.2f}%"],
                ['Net APY', f"{user_data['net_apy']*100:.2f}%"]
            ]
            
            # Update user positions to include APYs
            user_positions = [
                [
                    position['symbol'],
                    f"{position['supply_balance']:.4f}",
                    f"${position['supply_usd']:.2f}",
                    f"{position['supply_apr']*100:.2f}% / {position['supply_apy']*100:.2f}%",
                    f"{position['borrow_balance']:.4f}",
                    f"${position['borrow_usd']:.2f}",
                    f"{position['borrow_apr']*100:.2f}% / {position['borrow_apy']*100:.2f}%",
                    "Yes" if position['collateral_enabled'] else "No"
                ]
                for position in user_data['reserves']
                if position['supply_balance'] > 0 or position['borrow_balance'] > 0
            ]
            
            reserves = get_reserves_data()
            reserves_data = [
                [
                    reserve['symbol'],
                    f"{reserve['liquidity_rate']*100:.2f}% / {reserve['liquidity_apy']*100:.2f}%",
                    f"{reserve['variable_borrow_rate']*100:.2f}% / {reserve['variable_borrow_apy']*100:.2f}%",
                    "Yes" if reserve['collateral_enabled'] else "No",
                    "Yes" if reserve['borrowing_enabled'] else "No",
                    f"{reserve['ltv']:.2f}%",
                    f"{reserve['liquidation_threshold']:.2f}%",
                    f"{reserve['liquidation_bonus']:.2f}%"
                ]
                for reserve in reserves
            ]
            
            # Build the output string
            output = f"\rLast Update: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            output += "=== Portfolio Summary ===\n"
            output += tabulate(
                yield_summary,
                tablefmt='grid',
                colalign=('left', 'right')
            )
            
            output += "\n\n=== User Positions ===\n"
            output += tabulate(
                user_positions,
                headers=['Asset', 'Supply', 'Supply USD', 'Supply APR/APY', 'Borrow', 'Borrow USD', 'Borrow APR/APY', 'Collateral'],
                tablefmt='grid',
                colalign=('left', 'right', 'right', 'right', 'right', 'right', 'right', 'center')
            )
            
            output += f"\nE-Mode Category: {user_data['emode']}\n\n"
            output += "=== Reserves Data ===\n"
            output += tabulate(
                reserves_data,
                headers=[
                    'Asset',
                    'Supply APR/APY',
                    'Borrow APR/APY',
                    'Collateral',
                    'Borrowable',
                    'LTV',
                    'Liq. Threshold',
                    'Liq. Penalty'
                ],
                tablefmt='grid',
                colalign=('left', 'right', 'right', 'center', 'center', 'right', 'right', 'right')
            )
            
            # Print the entire output at once
            sys.stdout.write(output)
            sys.stdout.flush()
            
            # Wait before next update
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopped by user")
        sys.exit(0)

if __name__ == "__main__":
    load_dotenv(find_dotenv())
    main() 