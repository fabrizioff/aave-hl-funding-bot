from typing import Optional
from eth_typing import Address
from web3 import Web3
from web3.contract import Contract
from decimal import Decimal
import time

from .abi.arbitrum_aave_v3 import POOL_ABI, ERC20_ABI, WETH_GATEWAY_ABI

# Add these constants at the top of the file
WETH_GATEWAY = "0xC09e69E79106861dF5d289dA88349f10e2dc6b5C"
WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"  # WETH on Arbitrum
WETH_ABI = [
    {
        "constant": False,
        "inputs": [{"name": "wad", "type": "uint256"}],
        "name": "withdraw",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]
USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC on Arbitrum

# Update the WETH_GATEWAY_ABI at the top of the file
WETH_GATEWAY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "lendingPool", "type": "address"},
            {"internalType": "address", "name": "onBehalfOf", "type": "address"},
            {"internalType": "uint16", "name": "referralCode", "type": "uint16"}
        ],
        "name": "depositETH",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "withdrawETH",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

class AaveProtocol:
    def __init__(
        self,
        web3: Web3,
        pool_address: Address,
        wallet_address: Address,
        private_key: str
    ):
        self.web3 = web3
        self.wallet_address = self.web3.to_checksum_address(wallet_address)
        self.private_key = private_key
        
        # Initialize Pool contract with checksum address
        self.pool = self.web3.eth.contract(
            address=self.web3.to_checksum_address(pool_address),
            abi=POOL_ABI
        )
    
    async def supply(
        self,
        asset_address: str,
        amount: int,
        on_behalf_of: Optional[Address] = None,
        is_eth: bool = False
    ) -> dict:
        """Supply any asset (ETH or ERC20) as collateral to Aave V3 pool
        
        Args:
            asset_address: Address of token to supply (use "ETH" for ETH)
            amount: Amount to supply in wei
            on_behalf_of: Optional address to supply on behalf of
            is_eth: True if supplying ETH, False for ERC20 tokens
        """
        if is_eth:
            return await self._supply_eth(amount, on_behalf_of)
        else:
            return await self._supply_erc20(asset_address, amount, on_behalf_of)

    async def _supply_eth(
        self,
        amount: int,
        on_behalf_of: Optional[Address] = None
    ) -> dict:
        """Internal method to supply ETH"""
        # Initialize WETHGateway contract
        weth_gateway = self.web3.eth.contract(
            address=self.web3.to_checksum_address(WETH_GATEWAY),
            abi=WETH_GATEWAY_ABI
        )
        
        # Check ETH balance
        balance = self.web3.eth.get_balance(self.wallet_address)
        if balance < amount:
            raise ValueError(f"Insufficient ETH balance. Have: {balance / 10**18:.6f} ETH, Need: {amount / 10**18:.6f} ETH")
        
        # Get current gas price and estimate gas
        base_fee = self.web3.eth.gas_price
        priority_fee = int(base_fee * 0.1)  # 10% of base fee
        max_fee = base_fee * 2  # Double the base fee

        try:
            estimated_gas = weth_gateway.functions.depositETH(
                self.pool.address,
                on_behalf_of or self.wallet_address,
                0
            ).estimate_gas({
                'from': self.wallet_address,
                'value': amount,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': priority_fee
            })
            gas_limit = int(estimated_gas * 1.2)  # Add 20% buffer
        except Exception as e:
            print(f"Gas estimation failed: {str(e)}")
            gas_limit = 500000  # fallback gas limit
        
        # Build supply transaction
        supply_tx = weth_gateway.functions.depositETH(
            self.pool.address,
            on_behalf_of or self.wallet_address,
            0  # referralCode
        ).build_transaction({
            'from': self.wallet_address,
            'value': amount,
            'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': priority_fee,
            'gas': gas_limit,
            'chainId': 42161
        })
        
        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(supply_tx, self.private_key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # Wait for transaction with longer timeout
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        
        if receipt['status'] != 1:
            raise Exception("Supply ETH transaction failed")
            
        return receipt

    async def _supply_erc20(
        self,
        asset_address: Address,
        amount: int,
        on_behalf_of: Optional[Address] = None
    ) -> dict:
        """Internal method to supply ERC20 tokens"""
        # Convert addresses to checksum format
        asset_address = self.web3.to_checksum_address(asset_address)
        pool_address = self.web3.to_checksum_address(self.pool.address)
        wallet_address = self.web3.to_checksum_address(self.wallet_address)
        
        # Get token contract
        token = self.web3.eth.contract(
            address=asset_address,
            abi=ERC20_ABI
        )
        
        # Get token decimals
        decimals = token.functions.decimals().call()
        
        # Check balance first
        balance = token.functions.balanceOf(wallet_address).call()
        if balance < amount:
            raise ValueError(f"Insufficient balance. Have: {balance / 10**decimals:.6f}, Need: {amount / 10**decimals:.6f}")
        
        # Check and approve if needed
        allowance = token.functions.allowance(
            wallet_address,
            pool_address
        ).call()
        
        if allowance < amount:
            # Approve 1.5x the amount needed
            approve_amount = int(amount * 1.5)
            
            # Get current gas price from network
            gas_price = self.web3.eth.gas_price
            
            approve_tx = token.functions.approve(
                pool_address,
                approve_amount
            ).build_transaction({
                'from': wallet_address,
                'nonce': self.web3.eth.get_transaction_count(wallet_address),
                'gasPrice': gas_price,
                'gas': 100000,
                'chainId': 42161
            })
            
            signed_tx = self.web3.eth.account.sign_transaction(
                approve_tx,
                self.private_key
            )
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"Approval tx hash: {receipt['transactionHash'].hex()}")
            print(f"Approved {approve_amount / 10**decimals:.6f}")
            
            # Add a delay to ensure the approval is confirmed
            # Get current allowance to confirm approval
            while True:
                new_allowance = token.functions.allowance(
                    wallet_address,
                    pool_address
                ).call()
                if new_allowance >= amount:
                    break
                print("Waiting for approval confirmation...")
                time.sleep(1)

        # Get fresh gas price
        gas_price = self.web3.eth.gas_price
        
        # Estimate gas for supply transaction
        try:
            estimated_gas = self.pool.functions.supply(
                asset_address,
                amount,
                on_behalf_of or wallet_address,
                0
            ).estimate_gas({
                'from': wallet_address,
                'gasPrice': gas_price
            })
            gas_limit = int(estimated_gas * 1.2)  # Add 20% buffer
        except Exception as e:
            print(f"Gas estimation failed: {str(e)}")
            gas_limit = 300000  # fallback gas limit

        # Build supply transaction with updated nonce and gas
        supply_tx = self.pool.functions.supply(
            asset_address,
            amount,
            on_behalf_of or wallet_address,
            0  # referralCode
        ).build_transaction({
            'from': wallet_address,
            'nonce': self.web3.eth.get_transaction_count(wallet_address),
            'gasPrice': int(gas_price * 1.1),  # Add 10% to gas price
            'gas': gas_limit,
            'chainId': 42161  # Arbitrum One chainId
        })

        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(
            supply_tx,
            self.private_key
        )
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        # Wait for transaction receipt synchronously
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt['status'] != 1:
            raise Exception("Supply transaction failed")
            
        return receipt
    
    async def borrow_asset(
        self,
        asset_address: Address,
        amount: int,
        interest_rate_mode: int = 2,  # 2 = variable rate
        on_behalf_of: Optional[Address] = None
    ) -> dict:
        """Borrow assets from Aave V3 pool
        
        Args:
            asset_address: Address of token to borrow
            amount: Amount to borrow in wei
            interest_rate_mode: 2 for variable rate (recommended)
            on_behalf_of: Optional address to borrow on behalf of
        """
        # Convert addresses to checksum format
        asset_address = self.web3.to_checksum_address(asset_address)
        wallet_address = self.web3.to_checksum_address(self.wallet_address)
        
        # Get current gas price
        gas_price = self.web3.eth.gas_price
        
        # Estimate gas
        try:
            estimated_gas = self.pool.functions.borrow(
                asset_address,
                amount,
                interest_rate_mode,
                0,  # referralCode
                on_behalf_of or wallet_address
            ).estimate_gas({
                'from': wallet_address,
                'gasPrice': gas_price
            })
            gas_limit = int(estimated_gas * 1.2)  # Add 20% buffer
        except Exception as e:
            print(f"Gas estimation failed: {str(e)}")
            gas_limit = 500000  # fallback gas limit

        # Build borrow transaction
        borrow_tx = self.pool.functions.borrow(
            asset_address,
            amount,
            interest_rate_mode,
            0,  # referralCode
            on_behalf_of or wallet_address
        ).build_transaction({
            'from': wallet_address,
            'nonce': self.web3.eth.get_transaction_count(wallet_address),
            'gasPrice': int(gas_price * 1.1),  # Add 10% to gas price
            'gas': gas_limit,
            'chainId': 42161
        })

        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(
            borrow_tx,
            self.private_key
        )
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt['status'] != 1:
            raise Exception("Borrow transaction failed")
            
        return receipt
    
    async def repay_loan(
        self,
        asset_address: Address,
        amount: int,
        interest_rate_mode: int = 2,  # 2 = variable rate
        on_behalf_of: Optional[Address] = None
    ) -> dict:
        """Repay borrowed assets to Aave V3 pool"""
        # Convert addresses to checksum format
        asset_address = self.web3.to_checksum_address(asset_address)
        pool_address = self.web3.to_checksum_address(self.pool.address)
        wallet_address = self.web3.to_checksum_address(self.wallet_address)
        
        # Get token contract and decimals
        token = self.web3.eth.contract(address=asset_address, abi=ERC20_ABI)
        decimals = token.functions.decimals().call()
        
        # Calculate base gas limit based on amount
        amount_normalized = Decimal(amount) / Decimal(10**decimals)
        base_gas_limit = 2000000 if amount_normalized > 100 else 1000000  # Higher base gas limits
        
        # Get current gas price with multiplier for larger amounts
        gas_price = int(self.web3.eth.gas_price * 1.5)  # 50% higher than base price
        
        # Check balance and handle approval
        balance = token.functions.balanceOf(wallet_address).call()
        if balance < amount:
            raise ValueError(f"Insufficient balance. Have: {balance / 10**decimals:.6f}, Need: {amount / 10**decimals:.6f}")
        
        allowance = token.functions.allowance(wallet_address, pool_address).call()
        if allowance < amount:
            # Approve 2x the amount needed
            approve_amount = int(amount * 2)
            
            approve_tx = token.functions.approve(
                pool_address,
                approve_amount
            ).build_transaction({
                'from': wallet_address,
                'nonce': self.web3.eth.get_transaction_count(wallet_address),
                'gasPrice': gas_price,
                'gas': 300000,  # Higher gas for approval
                'chainId': 42161
            })
            
            signed_tx = self.web3.eth.account.sign_transaction(approve_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            print(f"Approval tx hash: {receipt['transactionHash'].hex()}")
            
            # Wait for approval confirmation
            while True:
                new_allowance = token.functions.allowance(wallet_address, pool_address).call()
                if new_allowance >= amount:
                    break
                print("Waiting for approval confirmation...")
                time.sleep(1)

        # Try to estimate gas with higher limits
        try:
            estimated_gas = self.pool.functions.repay(
                asset_address,
                amount,
                interest_rate_mode,
                on_behalf_of or wallet_address
            ).estimate_gas({
                'from': wallet_address,
                'gasPrice': gas_price,
                'gas': base_gas_limit
            })
            gas_limit = int(estimated_gas * 2)  # 100% buffer
            print(f"Estimated repay gas: {estimated_gas:,}")
        except Exception as e:
            print(f"Gas estimation failed: {str(e)}")
            gas_limit = base_gas_limit  # Use base limit as fallback

        print(f"Using gas limit: {gas_limit:,}")
        print(f"Gas price: {gas_price / 10**9:.2f} gwei")

        # Build repay transaction with legacy gas settings
        repay_tx = self.pool.functions.repay(
            asset_address,
            amount,
            interest_rate_mode,
            on_behalf_of or wallet_address
        ).build_transaction({
            'from': wallet_address,
            'nonce': self.web3.eth.get_transaction_count(wallet_address),
            'gasPrice': gas_price,
            'gas': gas_limit,
            'chainId': 42161
        })

        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(repay_tx, self.private_key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        
        if receipt['status'] != 1:
            raise Exception("Repay transaction failed")
        
        return receipt
    
    async def withdraw_collateral(
        self,
        asset_address: Address,
        amount: int,
        to: Optional[Address] = None
    ) -> dict:
        """Withdraw supplied collateral from Aave V3 pool"""
        # Get current gas price and estimate gas
        base_fee = self.web3.eth.gas_price
        priority_fee = int(base_fee * 0.1)  # 10% of base fee
        max_fee = base_fee * 2  # Double the base fee
        
        try:
            estimated_gas = self.pool.functions.withdraw(
                asset_address,
                amount,
                to or self.wallet_address
            ).estimate_gas({
                'from': self.wallet_address,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': priority_fee,
                'gas': 1000000  # Higher gas limit for estimation
            })
            gas_limit = int(estimated_gas * 1.2)  # Add 20% buffer
            print(f"Estimated withdraw gas: {estimated_gas:,}")
        except Exception as e:
            print(f"Gas estimation failed: {str(e)}")
            gas_limit = 500000  # fallback gas limit

        # Build withdraw transaction
        withdraw_tx = self.pool.functions.withdraw(
            asset_address,
            amount,
            to or self.wallet_address
        ).build_transaction({
            'from': self.wallet_address,
            'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': priority_fee,
            'gas': gas_limit,
            'chainId': 42161
        })

        # Sign and send transaction
        signed_tx = self.web3.eth.account.sign_transaction(withdraw_tx, self.private_key)
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        
        if receipt['status'] != 1:
            raise Exception("Withdraw transaction failed")
    
        return receipt

    async def switch_collateral(
        self,
        from_asset: Address,
        to_asset: Address,
        amount: int,
        max_slippage: int = 100,  # 1% default
        flash: bool = True
    ) -> dict:
        """Switch collateral from one asset to another using Aave V3 pool
        
        Args:
            from_asset: Address of current collateral token
            to_asset: Address of desired collateral token  
            amount: Amount to switch in wei
            max_slippage: Maximum acceptable slippage in basis points (100 = 1%)
            flash: Whether to use flashloan for the swap
        """
        # Get aToken address for from_asset
        a_token = self.pool.functions.getReserveData(from_asset).call()[7]
        
        switch_tx = self.pool.functions.swapCollateral(
            from_asset,
            to_asset,
            amount,
            flash,
            max_slippage,
            a_token
        ).build_transaction({
            'from': self.wallet_address,
            'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
        })

        signed_tx = self.web3.eth.account.sign_transaction(
            switch_tx, 
            self.private_key
        )
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = await self.web3.eth.wait_for_transaction_receipt(tx_hash)
        
        return receipt
    
    async def get_user_data(self) -> dict:
        """Get user account data including health factor"""
        data = self.pool.functions.getUserAccountData(
            self.wallet_address
        ).call()
        
        return {
            'total_collateral_base': data[0],
            'total_debt_base': data[1], 
            'available_borrows_base': data[2],
            'current_liquidation_threshold': data[3],
            'ltv': data[4],
            'health_factor': data[5]
        }

    async def get_borrow_rate(self, asset_address: Address) -> Decimal:
        """Get current variable borrow rate for an asset"""
        data = self.pool.functions.getReserveData(asset_address).call()
        return Decimal(data[4]) / Decimal(10**27)  # Normalized to percentage

    async def supply_eth(self, amount: int, on_behalf_of: Optional[Address] = None) -> dict:
        """Helper method to supply ETH"""
        return await self.supply(None, amount, on_behalf_of, is_eth=True)

    async def supply_erc20(self, token_address: str, amount: int, on_behalf_of: Optional[Address] = None) -> dict:
        """Helper method to supply ERC20 tokens"""
        return await self.supply(token_address, amount, on_behalf_of, is_eth=False)

    async def withdraw_eth(
        self,
        amount: int,
        to: Optional[Address] = None
    ) -> dict:
        """Withdraw ETH from Aave V3 pool"""
        try:
            # Use WETH address for withdrawal
            weth_address = self.web3.to_checksum_address(WETH)
            
            # Get current gas price with higher multiplier
            gas_price = int(self.web3.eth.gas_price * 2)  # Double the base price
            
            # First withdraw WETH from pool
            try:
                estimated_gas = self.pool.functions.withdraw(
                    weth_address,  # WETH address
                    amount,
                    to or self.wallet_address
                ).estimate_gas({
                    'from': self.wallet_address,
                    'gasPrice': gas_price,
                    'gas': 2000000  # Much higher gas limit for estimation
                })
                gas_limit = int(estimated_gas * 1.5)  # 50% buffer
                print(f"Estimated withdraw gas: {estimated_gas:,}")
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                gas_limit = 1000000  # Higher fallback gas limit

            print(f"Using gas limit: {gas_limit:,}")
            print(f"Gas price: {gas_price / 10**9:.2f} gwei")

            # Build withdraw transaction
            withdraw_tx = self.pool.functions.withdraw(
                weth_address,  # WETH address
                amount,
                to or self.wallet_address
            ).build_transaction({
                'from': self.wallet_address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                'gasPrice': gas_price,
                'gas': gas_limit,
                'chainId': 42161
            })

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(withdraw_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            
            if receipt['status'] != 1:
                raise Exception("Withdraw transaction failed")
            
            # Now unwrap WETH to ETH with higher gas settings
            weth_contract = self.web3.eth.contract(
                address=weth_address,
                abi=WETH_ABI
            )
            
            # Get fresh nonce and gas price
            gas_price = int(self.web3.eth.gas_price * 2)  # Double the base price again
            
            unwrap_tx = weth_contract.functions.withdraw(amount).build_transaction({
                'from': self.wallet_address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                'gasPrice': gas_price,
                'gas': 300000,  # Higher gas limit for unwrapping
                'chainId': 42161
            })
            
            signed_tx = self.web3.eth.account.sign_transaction(unwrap_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            unwrap_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if unwrap_receipt['status'] != 1:
                raise Exception("WETH unwrap failed")
            
            return unwrap_receipt
                
        except Exception as e:
            print(f"Error in withdraw_eth: {str(e)}")
            raise

    async def unwrap_weth(self, amount: int) -> dict:
        """Unwrap WETH to ETH
        
        Args:
            amount: Amount of WETH to unwrap in wei
        """
        try:
            # Initialize WETH contract
            weth_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(WETH),
                abi=WETH_ABI
            )
            
            # Build unwrap transaction
            unwrap_tx = weth_contract.functions.withdraw(
                amount
            ).build_transaction({
                'from': self.wallet_address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                'maxFeePerGas': int(self.web3.eth.gas_price * 1.5),  # 50% buffer
                'maxPriorityFeePerGas': int(self.web3.eth.gas_price * 1.1),
                'gas': 500000,  # Increased gas limit
                'chainId': 42161
            })

            # Try to estimate gas
            try:
                estimated_gas = self.web3.eth.estimate_gas({
                    **unwrap_tx,
                    'gas': 1000000  # Higher gas limit for estimation
                })
                unwrap_tx['gas'] = int(estimated_gas * 1.2)  # 20% buffer
                print(f"Estimated unwrap gas: {estimated_gas:,}")
            except Exception as e:
                print(f"Unwrap gas estimation failed: {str(e)}")
                # Keep the default gas limit

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(unwrap_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] != 1:
                raise Exception("Unwrap transaction failed")
        
            return receipt
            
        except Exception as e:
            print(f"Error in unwrap_weth: {str(e)}")
            raise

    async def swap_weth_to_usdc(self, amount: int, min_amount_out: Optional[int] = None) -> dict:
        """Swap WETH to USDC using Uniswap V3"""
        try:
            # Uniswap V3 Router on Arbitrum
            UNISWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
            # Using native USDC, not bridged
            USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC on Arbitrum
            
            # Initialize WETH contract
            weth_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(WETH),
                abi=ERC20_ABI
            )
            
            # Check WETH balance
            weth_balance = weth_contract.functions.balanceOf(self.wallet_address).call()
            print(f"WETH balance before approval: {weth_balance / 10**18:.6f}")
            
            if weth_balance < amount:
                raise ValueError(f"Insufficient WETH balance. Have: {weth_balance / 10**18:.6f}, Need: {amount / 10**18:.6f}")
            
            # Check and approve WETH spending
            allowance = weth_contract.functions.allowance(
                self.wallet_address,
                UNISWAP_ROUTER
            ).call()
            
            if allowance < amount:
                print("Approving WETH spending...")
                approve_tx = weth_contract.functions.approve(
                    UNISWAP_ROUTER,
                    2**256 - 1  # Max approval
                ).build_transaction({
                    'from': self.wallet_address,
                    'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                    'gasPrice': int(self.web3.eth.gas_price * 1.1),
                    'gas': 300000,
                    'chainId': 42161
                })
                
                signed_tx = self.web3.eth.account.sign_transaction(approve_tx, self.private_key)
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                print(f"Approval tx hash: {receipt['transactionHash'].hex()}")
                
                # Wait for approval confirmation
                while True:
                    new_allowance = weth_contract.functions.allowance(
                        self.wallet_address,
                        UNISWAP_ROUTER
                    ).call()
                    if new_allowance >= amount:
                        break
                    print("Waiting for approval confirmation...")
                    time.sleep(1)
            
            # Initialize Uniswap Router contract
            router_abi = [{
                "inputs": [{
                    "components": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "address", "name": "tokenOut", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                        {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                    ],
                    "internalType": "struct ISwapRouter.ExactInputSingleParams",
                    "name": "params",
                    "type": "tuple"
                }],
                "name": "exactInputSingle",
                "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function"
            }]
            
            router = self.web3.eth.contract(address=UNISWAP_ROUTER, abi=router_abi)
            
            # Build swap params as a tuple in the correct order
            params = (
                self.web3.to_checksum_address(WETH),  # tokenIn
                self.web3.to_checksum_address(USDC),  # tokenOut
                500,                                   # fee (0.05%)
                self.wallet_address,                   # recipient
                int(time.time() + 300),               # deadline (5 minutes)
                amount,                               # amountIn
                min_amount_out or 0,                  # amountOutMinimum
                0                                     # sqrtPriceLimitX96
            )
            
            # Build swap transaction
            swap_tx = router.functions.exactInputSingle(params).build_transaction({
                'from': self.wallet_address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                'gasPrice': int(self.web3.eth.gas_price * 1.1),
                'gas': 1000000,  # Increased gas limit
                'value': 0,  # Not sending ETH directly
                'chainId': 42161
            })

            # Try to estimate gas with higher limit
            try:
                estimated_gas = self.web3.eth.estimate_gas({
                    **swap_tx,
                    'gas': 2000000  # Higher gas limit for estimation
                })
                swap_tx['gas'] = int(estimated_gas * 1.2)  # 20% buffer
                print(f"Estimated gas: {estimated_gas:,}")
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                # Keep the high default gas limit

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(swap_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] != 1:
                raise Exception("Swap transaction failed")
            
            return receipt
            
        except Exception as e:
            print(f"Error in swap_weth_to_usdc: {str(e)}")
            raise

    async def swap_usdc_to_eth(self, amount: int, min_amount_out: Optional[int] = None) -> dict:
        """Swap USDC to native ETH using Uniswap V3 and unwrap WETH"""
        try:
            # First swap USDC to WETH
            swap_receipt = await self.swap_usdc_to_weth(amount, min_amount_out)
            
            # Get WETH balance after swap
            weth_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(WETH),
                abi=ERC20_ABI
            )
            weth_balance = weth_contract.functions.balanceOf(self.wallet_address).call()
            
            # Then unwrap WETH to ETH
            if weth_balance > 0:
                unwrap_receipt = await self.unwrap_weth(weth_balance)
                print(f"Unwrapped {weth_balance / 10**18:.6f} WETH to ETH")
                return unwrap_receipt
            
            return swap_receipt
                
        except Exception as e:
            print(f"Error in swap_usdc_to_eth: {str(e)}")
            raise

    async def swap_usdc_to_weth(self, amount: int, min_amount_out: Optional[int] = None) -> dict:
        """Swap USDC to WETH using Uniswap V3"""
        try:
            # Uniswap V3 Router on Arbitrum
            UNISWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
            
            # Initialize USDC contract
            usdc_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(USDC),
                abi=ERC20_ABI
            )
            
            # Check USDC balance
            usdc_balance = usdc_contract.functions.balanceOf(self.wallet_address).call()
            print(f"USDC balance before approval: {usdc_balance / 10**6:.2f}")
            
            if usdc_balance < amount:
                raise ValueError(f"Insufficient USDC balance. Have: {usdc_balance / 10**6:.2f}, Need: {amount / 10**6:.2f}")
            
            # Check and approve USDC spending
            allowance = usdc_contract.functions.allowance(
                self.wallet_address,
                UNISWAP_ROUTER
            ).call()
            
            if allowance < amount:
                print("Approving USDC spending...")
                approve_tx = usdc_contract.functions.approve(
                    UNISWAP_ROUTER,
                    2**256 - 1  # Max approval
                ).build_transaction({
                    'from': self.wallet_address,
                    'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                    'gasPrice': int(self.web3.eth.gas_price * 1.5),  # 50% buffer
                    'maxPriorityFeePerGas': int(self.web3.eth.gas_price * 1.1),
                    'gas': 500000,  # Increased gas limit
                    'chainId': 42161
                })
                
                # Try to estimate gas for approval
                try:
                    estimated_gas = self.web3.eth.estimate_gas({
                        **approve_tx,
                        'gas': 1000000  # Higher gas limit for estimation
                    })
                    approve_tx['gas'] = int(estimated_gas * 1.2)  # 20% buffer
                    print(f"Estimated approval gas: {estimated_gas:,}")
                except Exception as e:
                    print(f"Approval gas estimation failed: {str(e)}")
                    # Keep the default gas limit
                
                signed_tx = self.web3.eth.account.sign_transaction(approve_tx, self.private_key)
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                print(f"Approval tx hash: {receipt['transactionHash'].hex()}")
                
                # Wait for approval confirmation
                while True:
                    new_allowance = usdc_contract.functions.allowance(
                        self.wallet_address,
                        UNISWAP_ROUTER
                    ).call()
                    if new_allowance >= amount:
                        break
                    print("Waiting for approval confirmation...")
                    time.sleep(1)
            
            # Initialize Uniswap Router contract
            router_abi = [{
                "inputs": [{
                    "components": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "address", "name": "tokenOut", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                        {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                    ],
                    "internalType": "struct ISwapRouter.ExactInputSingleParams",
                    "name": "params",
                    "type": "tuple"
                }],
                "name": "exactInputSingle",
                "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function"
            }]
            
            router = self.web3.eth.contract(address=UNISWAP_ROUTER, abi=router_abi)
            
            # Build swap params as a tuple in the correct order
            params = (
                self.web3.to_checksum_address(USDC),  # tokenIn
                self.web3.to_checksum_address(WETH),  # tokenOut
                500,                                   # fee (0.05%)
                self.wallet_address,                   # recipient
                int(time.time() + 300),               # deadline (5 minutes)
                amount,                               # amountIn
                min_amount_out or 0,                  # amountOutMinimum
                0                                     # sqrtPriceLimitX96
            )
            
            # Build swap transaction
            swap_tx = router.functions.exactInputSingle(params).build_transaction({
                'from': self.wallet_address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet_address),
                'maxFeePerGas': int(self.web3.eth.gas_price * 1.5),  # 50% buffer
                'maxPriorityFeePerGas': int(self.web3.eth.gas_price * 1.1),
                'gas': 1000000,  # Increased gas limit
                'value': 0,  # Not sending ETH directly
                'chainId': 42161
            })

            # Try to estimate gas with higher limit
            try:
                estimated_gas = self.web3.eth.estimate_gas({
                    **swap_tx,
                    'gas': 2000000  # Higher gas limit for estimation
                })
                swap_tx['gas'] = int(estimated_gas * 1.2)  # 20% buffer
                print(f"Estimated gas: {estimated_gas:,}")
            except Exception as e:
                print(f"Gas estimation failed: {str(e)}")
                # Keep the high default gas limit

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(swap_tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] != 1:
                raise Exception("Swap transaction failed")
            
            return receipt
            
        except Exception as e:
            print(f"Error in swap_usdc_to_weth: {str(e)}")
            raise
