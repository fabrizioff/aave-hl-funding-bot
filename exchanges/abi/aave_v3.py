# ABIs for Aave V3 contracts
UI_POOL_DATA_PROVIDER_ABI = [
    {
        "inputs": [{"internalType": "contract IPoolAddressesProvider", "name": "provider", "type": "address"}],
        "name": "getReservesData",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "underlyingAsset", "type": "address"},
                    {"internalType": "string", "name": "name", "type": "string"},
                    {"internalType": "string", "name": "symbol", "type": "string"},
                    {"internalType": "uint256", "name": "decimals", "type": "uint256"},
                    {"internalType": "uint256", "name": "baseLTVasCollateral", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveLiquidationThreshold", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveLiquidationBonus", "type": "uint256"},
                    {"internalType": "uint256", "name": "reserveFactor", "type": "uint256"},
                    {"internalType": "bool", "name": "usageAsCollateralEnabled", "type": "bool"},
                    {"internalType": "bool", "name": "borrowingEnabled", "type": "bool"},
                    {"internalType": "bool", "name": "isActive", "type": "bool"},
                    {"internalType": "bool", "name": "isFrozen", "type": "bool"},
                    {"internalType": "uint128", "name": "liquidityIndex", "type": "uint128"},
                    {"internalType": "uint128", "name": "variableBorrowIndex", "type": "uint128"},
                    {"internalType": "uint128", "name": "liquidityRate", "type": "uint128"},
                    {"internalType": "uint128", "name": "variableBorrowRate", "type": "uint128"},
                    {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"}
                ],
                "internalType": "struct IUiPoolDataProviderV3.AggregatedReserveData[]",
                "name": "",
                "type": "tuple[]"
            },
            {
                "components": [
                    {"internalType": "uint256", "name": "marketReferenceCurrencyUnit", "type": "uint256"},
                    {"internalType": "int256", "name": "marketReferenceCurrencyPriceInUsd", "type": "int256"},
                    {"internalType": "int256", "name": "networkBaseTokenPriceInUsd", "type": "int256"},
                    {"internalType": "uint8", "name": "networkBaseTokenPriceDecimals", "type": "uint8"}
                ],
                "internalType": "struct IUiPoolDataProviderV3.BaseCurrencyInfo",
                "name": "",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "contract IPoolAddressesProvider", "name": "provider", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"}
        ],
        "name": "getUserReservesData",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "underlyingAsset", "type": "address"},
                    {"internalType": "uint256", "name": "scaledATokenBalance", "type": "uint256"},
                    {"internalType": "bool", "name": "usageAsCollateralEnabledOnUser", "type": "bool"},
                    {"internalType": "uint256", "name": "scaledVariableDebt", "type": "uint256"}
                ],
                "internalType": "struct IUiPoolDataProviderV3.UserReserveData[]",
                "name": "",
                "type": "tuple[]"
            },
            {"internalType": "uint8", "name": "", "type": "uint8"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

POOL_ADDRESSES_PROVIDER_ABI = [
    {
        "inputs": [],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
] 