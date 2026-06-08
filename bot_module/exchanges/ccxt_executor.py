from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional
from decimal import Decimal

import ccxt.async_support as ccxt
import ccxt.pro as ccxtpro


from bot_module import config

logger = logging.getLogger("bot_module.exchanges.ccxt_executor")


class CcxtExecutor:
    """
    Universal executor based on the CCXT / CCXT.Pro library.
    Implements the ExchangeExecutor protocol for cross-exchange trading.
    """

    def __init__(
        self,
        exchange_id: str,
        api_key: str,
        api_secret: str,
        market_type: str = "futures_usdtm",
        sandbox: bool = False,
        **kwargs: Any,
    ):
        self.exchange_id = exchange_id.lower()
        self.market_type = market_type or config.TRADING_MARKET_TYPE
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox

        # Mapping market_type to CCXT expectations
        self.supports_positions = (
            True
            if "futures" in self.market_type or "swap" in self.market_type
            else False
        )
        self.supports_shorting = self.supports_positions

        # Determine exchange options based on market type
        exchange_options = {}
        exchange_options["fetchCurrencies"] = False
        exchange_options["fetchMargins"] = False
        if self.supports_positions:
            exchange_options["defaultType"] = self._default_ccxt_market_type(
                self.exchange_id
            )
            if self.exchange_id in ["binance", "bybit"]:
                exchange_options["defaultSubType"] = "linear"
                exchange_options["fetchMarkets"] = ["linear"]
            else:
                exchange_options["defaultSubType"] = "swap"
                exchange_options["fetchMarkets"] = ["swap"]

        # Inject Bybit Broker ID if configured
        if self.exchange_id == "bybit":
            broker_id = getattr(config, "BYBIT_BROKER_ID", None)
            if broker_id:
                exchange_options["brokerId"] = broker_id
                logger.info(f"CcxtExecutor: Using Bybit Broker ID: {broker_id}")

        elif "spot" in self.market_type:
            exchange_options["defaultType"] = "spot"
            # exchange_options['fetchMarkets'] = ['spot'] # Can cause KeyErrors in some sandbox environments

        # Unpack packed secret and passphrase if it's JSON
        import json

        uid = kwargs.get("uid") or kwargs.get("api_uid")
        try:
            parsed_secret = json.loads(api_secret)
            if isinstance(parsed_secret, dict) and "secret" in parsed_secret:
                api_secret = parsed_secret["secret"]
                if "password" in parsed_secret and not kwargs.get("password"):
                    kwargs["password"] = parsed_secret["password"]
                if "uid" in parsed_secret and not uid:
                    uid = parsed_secret["uid"]
        except Exception:
            pass

        # Sanitize credentials
        api_key = str(api_key or "").strip()
        api_secret = str(api_secret or "").strip()

        exchange_config = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": exchange_options,
        }

        # Add X-Referer header for Bybit if Broker ID is present
        if self.exchange_id == "bybit":
            broker_id = getattr(config, "BYBIT_BROKER_ID", None)
            if broker_id:
                if "headers" not in exchange_config:
                    exchange_config["headers"] = {}
                exchange_config["headers"]["X-Referer"] = broker_id

        # Resolve password / passphrase for exchanges that require it (e.g. Bitget, OKX)
        password = kwargs.get("password") or kwargs.get("api_password")
        if self.exchange_id == "gateio" and not uid and password:
            uid = password
        if not password and self.exchange_id in ["bitget", "okx"]:
            import os

            env_prefix = (
                f"TESTNET_{self.exchange_id.upper()}"
                if sandbox
                else self.exchange_id.upper()
            )
            password = os.getenv(f"{env_prefix}_PASSWORD") or os.getenv(
                f"{env_prefix}_PASSPHRASE"
            )

        if password:
            exchange_config["password"] = str(password).strip()
        if uid:
            exchange_config["uid"] = str(uid).strip()

        # Initialize CCXT REST Exchange client
        ccxt_class = getattr(ccxt, self.exchange_id, None)
        if ccxt_class is None:
            raise ValueError(f"Exchange '{self.exchange_id}' is not supported by CCXT.")

        self._exchange = ccxt_class(exchange_config)

        if self.sandbox and self.exchange_id == "binance":
            self._patch_binance_demo_urls(self._exchange)
            logger.info(
                f"Binance REST API URL patched for Sandbox (Demo Trading): {self._exchange.urls['api']}"
            )

        # Initialize CCXT Pro WebSocket client for User Data Stream
        ccxtpro_class = getattr(ccxtpro, self.exchange_id, None)
        if ccxtpro_class:
            pro_config = exchange_config.copy()
            self._exchange_pro = ccxtpro_class(pro_config)

            if self.sandbox and self.exchange_id == "binance":
                # Do not call set_sandbox_mode(True): CCXT maps Binance futures
                # to the legacy testnet, while demo.binance.com uses demo-* hosts.
                self._patch_binance_demo_urls(self._exchange_pro)
                self._exchange_pro.options["defaultType"] = self._exchange.options.get(
                    "defaultType"
                )
                ws_urls = self._exchange_pro.urls.get("api", {}).get("ws", {})
                logger.info(
                    f"Binance Sandbox Config Sync: REST={self._exchange_pro.urls['api'].get('fapiPrivate')}, WS={ws_urls.get('future')}"
                )
        else:
            self._exchange_pro = None

        logger.info(
            f"CcxtExecutor initialized for {self.exchange_id} (Sandbox: {self.sandbox}, Market: {self.market_type})"
        )
        if self.sandbox and self.exchange_id != "binance":
            self._exchange.set_sandbox_mode(True)
            if self._exchange_pro:
                self._exchange_pro.set_sandbox_mode(True)

            if self.exchange_id == "gateio":
                testnet_api_url = "https://api-testnet.gateapi.io/api/v4"
                if isinstance(self._exchange.urls.get("api"), dict):
                    for key in ["public", "private"]:
                        if key in self._exchange.urls["api"]:
                            if isinstance(self._exchange.urls["api"][key], dict):
                                for sub_key in self._exchange.urls["api"][key]:
                                    self._exchange.urls["api"][key][sub_key] = (
                                        testnet_api_url
                                    )
                            else:
                                self._exchange.urls["api"][key] = testnet_api_url

                if self._exchange_pro:
                    self._exchange_pro.urls["ws"] = {
                        "spot": "wss://ws-testnet.gate.com/v4/ws/spot",
                        "swap": "wss://ws-testnet.gate.com/v4/ws/futures/usdt",
                        "future": "wss://ws-testnet.gate.com/v4/ws/futures/btc",
                    }
                    self._exchange_pro.urls["api"]["swap"] = {
                        "usdt": "wss://ws-testnet.gate.com/v4/ws/futures/usdt",
                        "btc": "wss://ws-testnet.gate.com/v4/ws/futures/btc",
                    }
                    self._exchange_pro.urls["api"]["future"] = {
                        "usdt": "wss://ws-testnet.gate.com/v4/ws/futures/usdt",
                        "btc": "wss://ws-testnet.gate.com/v4/ws/futures/btc",
                    }
                    if isinstance(self._exchange_pro.urls.get("api"), dict):
                        for key in ["public", "private"]:
                            if key in self._exchange_pro.urls["api"]:
                                if isinstance(
                                    self._exchange_pro.urls["api"][key], dict
                                ):
                                    if (
                                        self.exchange_id == "gateio"
                                        and not self.supports_positions
                                    ):
                                        logger.error(
                                            "Gate.io Spot is not supported on Testnet. Please use Futures/Swap or connect to Mainnet."
                                        )
                                        self._exchange_pro = None
                                        break
                                    for sub_key in self._exchange_pro.urls["api"][key]:
                                        self._exchange_pro.urls["api"][key][sub_key] = (
                                            testnet_api_url
                                        )
                                else:
                                    self._exchange_pro.urls["api"][key] = (
                                        testnet_api_url
                                    )

            if self.exchange_id == "bingx":
                # BingX sandbox often lacks WS URLs in CCXT
                if self._exchange_pro:
                    self._exchange_pro.urls["ws"] = {
                        "public": "wss://open-api-vst-testnet.bingx.com/market-data",
                        "private": "wss://open-api-vst-testnet.bingx.com/market-data",
                    }
                    # Fix for NoneType + str error in BingX sandbox
                    for exchange in (self._exchange, self._exchange_pro):
                        if isinstance(exchange.urls.get("api"), dict):
                            for key in list(exchange.urls["api"].keys()):
                                if key != "ws":
                                    exchange.urls["api"][key] = (
                                        "https://open-api-vst.bingx.com/openApi"
                                    )
                        else:
                            exchange.urls["api"] = (
                                "https://open-api-vst.bingx.com/openApi"
                            )
                    if isinstance(self._exchange_pro.urls.get("api"), dict):
                        self._exchange_pro.urls["api"]["ws"] = {
                            "linear": "wss://vst-open-api-ws.bingx.com/swap-market",
                        }

                if self.supports_positions:

                    async def mock_load_markets(reload=False):
                        if not self._exchange.markets or reload:
                            markets = {
                                "BTC/USDT:USDT": {
                                    "id": "BTC_USDT",
                                    "symbol": "BTC/USDT:USDT",
                                    "base": "BTC",
                                    "quote": "USDT",
                                    "settle": "USDT",
                                    "baseId": "BTC",
                                    "quoteId": "USDT",
                                    "settleId": "USDT",
                                    "type": "swap",
                                    "spot": False,
                                    "margin": False,
                                    "swap": True,
                                    "future": False,
                                    "option": False,
                                    "active": True,
                                    "contract": True,
                                    "linear": True,
                                    "inverse": False,
                                    "contractSize": 0.0001,
                                    "precision": {"price": 0.1, "amount": 1.0},
                                    "limits": {
                                        "amount": {"min": 1.0, "max": 1000000.0},
                                        "price": {"min": 0.1, "max": 1000000.0},
                                        "cost": {"min": 1.0},
                                    },
                                    "info": {
                                        "name": "BTC_USDT",
                                        "contract_size": "0.0001",
                                        "order_price_round": "0.1",
                                        "order_size_min": 1,
                                    },
                                }
                            }
                            self._exchange.markets = markets
                            self._exchange.symbols = list(markets.keys())
                        return self._exchange.markets

                    self._exchange.load_markets = mock_load_markets

        if self.exchange_id == "bitget" and "futures" in self.market_type:
            self._exchange.options["defaultType"] = "swap"
            if self._exchange_pro:
                self._exchange_pro.options["defaultType"] = "swap"

        if self.exchange_id == "gateio" and self.supports_positions:
            if uid:
                self._set_gateio_uid(str(uid).strip())
            self._patch_gateio_swap_market_loader(self._exchange)
            if self._exchange_pro:
                self._patch_gateio_swap_market_loader(self._exchange_pro)

        self._user_data_running = False
        self._user_data_task: Optional[asyncio.Task] = None

        logger.info(
            f"CcxtExecutor initialized for exchange: {self.exchange_id}, market: {self.market_type}, sandbox: {self.sandbox}"
        )

    async def close(self) -> None:
        logger.info(f"Closing CcxtExecutor for {self.exchange_id}...")
        await self.stop_user_data_stream()

        try:
            await self._exchange.close()
        except Exception as e:
            logger.error(f"Error closing CCXT REST client: {e}")

        try:
            if self._exchange_pro:
                await self._exchange_pro.close()
        except Exception as e:
            logger.error(f"Error closing CCXT Pro WebSocket client: {e}")

        logger.info(f"CcxtExecutor for {self.exchange_id} closed.")

    async def get_server_time(self) -> Optional[Dict[str, Any]]:
        try:
            # fetch_time() returns a timestamp in milliseconds
            server_time_ms = await self._exchange.fetch_time()
            return {"serverTime": server_time_ms}
        except Exception as e:
            logger.error(
                f"Error fetching server time on {self.exchange_id}: {e}", exc_info=True
            )
            # Return current time as fallback
            return {"serverTime": int(time.time() * 1000)}

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        """
        Backward compatibility layer to execute raw endpoints.
        Attempts to map Binance endpoints to CCXT methods or routes them directly if supported.
        """
        logger.debug(f"CCXT _request fallback: {method} {endpoint}")
        if "balance" in endpoint or "account" in endpoint:
            balances = await self.get_account_balance() or {}
            if self.market_type == "futures_usdtm":
                return [
                    {
                        "asset": asset,
                        "availableBalance": values.get("free", "0"),
                        "balance": str(
                            self._safe_float(values.get("free"))
                            + self._safe_float(values.get("locked"))
                        ),
                    }
                    for asset, values in balances.items()
                ]
            return {
                "balances": [
                    {
                        "asset": asset,
                        "free": values.get("free", "0"),
                        "locked": values.get("locked", "0"),
                    }
                    for asset, values in balances.items()
                ]
            }

        if "positionRisk" in endpoint:
            return await self.get_open_positions()

        return {}

    async def get_ticker_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        ccxt_symbol = self._normalize_symbol(symbol)

        if self.exchange_id == "gateio" and self.sandbox and self.supports_positions:
            import aiohttp

            try:
                contract_name = ccxt_symbol.split(":")[0].replace("/", "_")
                url = f"https://api-testnet.gateapi.io/api/v4/futures/usdt/tickers?contract={contract_name}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            ticker_data = (
                                data[0]
                                if isinstance(data, list) and len(data) > 0
                                else data
                            )
                            if isinstance(ticker_data, dict) and "last" in ticker_data:
                                return {
                                    "symbol": symbol.upper(),
                                    "price": str(ticker_data.get("last", "0")),
                                }
            except Exception as e:
                logger.warning(f"Direct fetch_ticker fallback failed for {symbol}: {e}")

        try:
            ticker = await self._exchange.fetch_ticker(ccxt_symbol)
            return {"symbol": symbol.upper(), "price": str(ticker.get("last", "0"))}
        except Exception as e:
            logger.error(
                f"Error fetching ticker price for {symbol}: {e}", exc_info=True
            )
            return None

    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        ccxt_symbol = self._normalize_symbol(symbol)
        try:
            if not self._exchange.markets:
                await self._exchange.load_markets()

            m_data = None
            if ccxt_symbol in self._exchange.markets:
                m_data = self._exchange.markets[ccxt_symbol]
            else:
                for m in self._exchange.markets.values():
                    if (
                        m.get("id", "").upper() == symbol.upper()
                        or self._to_legacy_symbol(m.get("symbol", "")).upper()
                        == symbol.upper()
                    ):
                        m_data = m
                        break

            if not m_data:
                return None

            raw_symbol = self._to_legacy_symbol(
                m_data.get("symbol") or m_data.get("id", "")
            )
            price_step = self._precision_to_step(
                m_data.get("precision", {}).get("price"), 0.01
            )
            amount_step = self._precision_to_step(
                m_data.get("precision", {}).get("amount"), 0.001
            )
            amount_limits = m_data.get("limits", {}).get("amount", {}) or {}
            cost_limits = m_data.get("limits", {}).get("cost", {}) or {}
            min_qty = self._safe_float(amount_limits.get("min"), amount_step)
            max_qty = self._safe_float(amount_limits.get("max"), 1000000.0)
            amount_step, min_qty, max_qty = self._normalize_amount_units_for_market(
                ccxt_symbol,
                m_data,
                amount_step,
                min_qty,
                max_qty,
            )
            min_notional = self._safe_float(cost_limits.get("min"), 5.0)

            filters = [
                {"filterType": "PRICE_FILTER", "tickSize": str(price_step)},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": str(amount_step),
                    "minQty": str(min_qty),
                    "maxQty": str(max_qty),
                },
                {"filterType": "MIN_NOTIONAL", "notional": str(min_notional)},
                {"filterType": "NOTIONAL", "minNotional": str(min_notional)},
            ]

            return {
                "symbol": raw_symbol,
                "pair": raw_symbol,
                "status": "TRADING" if m_data.get("active", True) else "BREAK",
                "contractType": "PERPETUAL" if m_data.get("swap", False) else None,
                "isSpotTradingAllowed": bool(m_data.get("spot", False)),
                "baseAsset": m_data.get("base", ""),
                "quoteAsset": m_data.get("quote", ""),
                "filters": filters,
                "tick_size": price_step,
                "lot_params": {
                    "stepSize": amount_step,
                    "minQty": min_qty,
                    "maxQty": max_qty,
                },
                "min_notional": min_notional,
            }
        except Exception as e:
            logger.error(
                f"Error fetching symbol info for {symbol} on {self.exchange_id}: {e}",
                exc_info=True,
            )
            return None

    async def get_tick_size(self, symbol: str) -> Optional[float]:
        info = await self.get_symbol_info(symbol)
        if info:
            return float(info["tick_size"])
        return None

    async def get_lot_size_params(self, symbol: str) -> Optional[Dict[str, float]]:
        info = await self.get_symbol_info(symbol)
        if info:
            return {
                "minQty": float(info["lot_params"]["minQty"]),
                "maxQty": float(info["lot_params"]["maxQty"]),
                "stepSize": float(info["lot_params"]["stepSize"]),
            }
        return None

    async def get_min_notional(self, symbol: str) -> Optional[float]:
        info = await self.get_symbol_info(symbol)
        if info:
            return float(info["min_notional"])
        return None

    async def fetch_exchange_info(
        self,
        force_update: bool = False,
        specific_market_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Loads and returns standardized exchange info from CCXT.
        Maps it to existing expectation schemas.
        """
        try:
            markets = await self._exchange.load_markets(reload=force_update)
            symbols_list = []

            for m_id, m_data in markets.items():
                # Filter symbols based on specific_market_type or current executor market_type
                target_m_type = specific_market_type or self.market_type

                is_match = False
                if "futures" in target_m_type and m_data.get("swap", False):
                    is_match = True
                elif "spot" in target_m_type and m_data.get("spot", False):
                    is_match = True

                if not is_match:
                    continue

                # Create Binance-like exchange info representation
                raw_symbol = self._to_legacy_symbol(
                    m_data.get("symbol") or m_data.get("id", "")
                )
                price_step = self._precision_to_step(
                    m_data.get("precision", {}).get("price"), 0.01
                )
                amount_step = self._precision_to_step(
                    m_data.get("precision", {}).get("amount"), 0.001
                )
                amount_limits = m_data.get("limits", {}).get("amount", {}) or {}
                cost_limits = m_data.get("limits", {}).get("cost", {}) or {}
                min_qty = self._safe_float(amount_limits.get("min"), amount_step)
                max_qty = self._safe_float(amount_limits.get("max"), 1000000.0)
                amount_step, min_qty, max_qty = self._normalize_amount_units_for_market(
                    m_data.get("symbol") or m_id,
                    m_data,
                    amount_step,
                    min_qty,
                    max_qty,
                )
                min_notional = self._safe_float(cost_limits.get("min"), 5.0)
                filters = [
                    {"filterType": "PRICE_FILTER", "tickSize": str(price_step)},
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": str(amount_step),
                        "minQty": str(min_qty),
                        "maxQty": str(max_qty),
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": str(min_notional)},
                ]

                symbol_info = {
                    "symbol": raw_symbol,
                    "pair": raw_symbol,
                    "status": "TRADING" if m_data.get("active", True) else "BREAK",
                    "contractType": "PERPETUAL" if m_data.get("swap", False) else None,
                    "isSpotTradingAllowed": bool(m_data.get("spot", False)),
                    "baseAsset": m_data.get("base", ""),
                    "quoteAsset": m_data.get("quote", ""),
                    "filters": filters,
                    "tick_size": price_step,
                    "lot_params": {
                        "stepSize": amount_step,
                        "minQty": min_qty,
                        "maxQty": max_qty,
                    },
                    "min_notional": min_notional,
                }
                symbols_list.append(symbol_info)

            return {"symbols": symbols_list}

        except Exception as e:
            logger.error(f"Error fetching exchange info: {e}", exc_info=True)
            return None

    async def place_order(
        self, symbol: str, side: str, order_type: str, **kwargs: Any
    ) -> Dict[str, Any]:
        ccxt_symbol = self._normalize_symbol(symbol)
        ccxt_side = side.lower()
        order_type_upper = str(order_type).upper()
        ccxt_type = self._map_order_type_to_ccxt(order_type_upper)

        quantity = kwargs.get("quantity")
        price = kwargs.get("price")

        params = {}
        stop_price = kwargs.get("stopPrice")
        if stop_price is not None:
            trigger_price = float(stop_price)
            if self.exchange_id == "bitget":
                try:
                    trigger_price = float(
                        self._exchange.price_to_precision(ccxt_symbol, trigger_price)
                    )
                except Exception:
                    pass
                if self.supports_positions:
                    if "TAKE_PROFIT" in order_type_upper:
                        params["takeProfitPrice"] = trigger_price
                    else:
                        params["stopLossPrice"] = trigger_price
                else:
                    params["triggerPrice"] = trigger_price
            elif self.exchange_id == "bybit":
                params["triggerPrice"] = trigger_price
                trigger_direction = self._bybit_trigger_direction(
                    order_type_upper, ccxt_side
                )
                if trigger_direction is not None and self.supports_positions:
                    params["triggerDirection"] = trigger_direction
                if not self.supports_positions and (
                    "STOP" in order_type_upper or "TAKE_PROFIT" in order_type_upper
                ):
                    params["orderFilter"] = "tpslOrder"
            elif self.exchange_id in {"gateio", "bingx"} and self.supports_positions:
                if "TAKE_PROFIT" in order_type_upper:
                    params["takeProfitPrice"] = trigger_price
                else:
                    params["stopLossPrice"] = trigger_price
            else:
                params["triggerPrice"] = trigger_price
                params["stopPrice"] = trigger_price
                if "TAKE_PROFIT" in order_type_upper:
                    params["takeProfitPrice"] = trigger_price
                else:
                    params["stopLossPrice"] = trigger_price

        if kwargs.get("reduceOnly") is not None and self.supports_positions:
            params["reduceOnly"] = kwargs.get("reduceOnly")

        if kwargs.get("newClientOrderId") is not None:
            cid = str(kwargs.get("newClientOrderId"))
            if self.exchange_id == "okx":
                cid = "".join(c for c in cid if c.isalnum())
            params["clientOrderId"] = cid

        if kwargs.get("timeInForce") is not None:
            params["timeInForce"] = kwargs.get("timeInForce")
        if kwargs.get("positionSide") is not None:
            if self.exchange_id == "okx":
                params["posSide"] = str(kwargs.get("positionSide")).lower()
            else:
                params["positionSide"] = kwargs.get("positionSide")
        elif self.exchange_id == "okx" and self.supports_positions:
            is_reduce = (
                kwargs.get("reduceOnly") is True
                or str(kwargs.get("reduceOnly")).lower() == "true"
                or kwargs.get("closePosition") is True
                or str(kwargs.get("closePosition")).lower() == "true"
            )
            if ccxt_side == "buy":
                params["posSide"] = "short" if is_reduce else "long"
            else:
                params["posSide"] = "long" if is_reduce else "short"

        if kwargs.get("closePosition") is not None:
            params["closePosition"] = kwargs.get("closePosition")

        if self.exchange_id == "gateio" and self.supports_positions:
            params.setdefault("type", "swap")
            params.setdefault("settle", "usdt")
            if "reduceOnly" in params:
                if isinstance(params["reduceOnly"], str):
                    params["reduceOnly"] = params["reduceOnly"].lower() == "true"
            if "closePosition" in params:
                if isinstance(params["closePosition"], str):
                    params["closePosition"] = params["closePosition"].lower() == "true"

        if self.exchange_id == "bingx" and self.supports_positions:
            params.setdefault("type", "swap")
            if self.sandbox:
                params.setdefault("hedged", True)

        ccxt_order_side = ccxt_side
        if self.exchange_id == "bitget" and self.supports_positions:
            if getattr(self, "_bitget_is_unilateral", False):
                params["hedged"] = False
            else:
                params["hedged"] = True
                params.pop("tradeSide", None)
                params.pop("positionSide", None)

            is_reduce_only = (
                kwargs.get("reduceOnly") is True
                or str(kwargs.get("reduceOnly")).lower() == "true"
            )
            is_tpsl_trigger = stop_price is not None and (
                "STOP" in order_type_upper or "TAKE_PROFIT" in order_type_upper
            )
            if is_reduce_only and is_tpsl_trigger:
                # CCXT Bitget maps TPSL holdSide from `side`, not from the close order side.
                ccxt_order_side = "buy" if ccxt_side == "sell" else "sell"

        try:
            # Check if this is Binance Futures Algo Order
            if (
                self.exchange_id == "binance"
                and self.market_type == "futures_usdtm"
                and order_type_upper
                in {
                    "STOP_MARKET",
                    "TAKE_PROFIT_MARKET",
                    "STOP",
                    "TAKE_PROFIT",
                    "TRAILING_STOP_MARKET",
                }
            ):
                algo_params = {
                    "symbol": symbol.upper(),
                    "side": side.upper(),
                    "type": order_type_upper,
                    "algoType": "CONDITIONAL",
                }

                if stop_price is not None:
                    try:
                        formatted_stop_price = self._exchange.price_to_precision(
                            ccxt_symbol, float(stop_price)
                        )
                        algo_params["triggerPrice"] = formatted_stop_price
                    except Exception:
                        algo_params["triggerPrice"] = str(stop_price)

                if quantity is not None:
                    try:
                        formatted_qty = self._exchange.amount_to_precision(
                            ccxt_symbol, float(quantity)
                        )
                        algo_params["quantity"] = formatted_qty
                    except Exception:
                        algo_params["quantity"] = str(quantity)

                if kwargs.get("reduceOnly") is not None:
                    algo_params["reduceOnly"] = str(kwargs.get("reduceOnly")).lower()

                if kwargs.get("closePosition") is not None:
                    algo_params["closePosition"] = str(
                        kwargs.get("closePosition")
                    ).lower()

                if kwargs.get("newClientOrderId") is not None:
                    # Binance Futures Algo API uses clientAlgoId, not the regular
                    # order endpoint's newClientOrderId.
                    algo_params["clientAlgoId"] = kwargs.get("newClientOrderId")

                for key in [
                    "workingType",
                    "priceProtect",
                    "activationPrice",
                    "callbackRate",
                ]:
                    if kwargs.get(key) is not None:
                        algo_params[key] = str(kwargs.get(key))

                logger.info(
                    f"CCXT: Placing Binance Futures Algo Order {symbol} {side} {order_type_upper} Params={algo_params}"
                )
                algo_resp = await self._call_exchange_method(
                    [
                        "fapiPrivatePostAlgoOrder",
                        "fapiprivatePostAlgoorder",
                        "fapiprivate_post_algoorder",
                    ],
                    algo_params,
                    fallback_path="algoOrder",
                    fallback_api="fapiPrivate",
                    fallback_http_method="POST",
                )

                return {
                    "symbol": symbol.upper(),
                    "algoId": algo_resp.get("algoId"),
                    "orderId": algo_resp.get("algoId"),
                    "clientAlgoId": algo_resp.get("clientAlgoId")
                    or algo_resp.get("clientOrderId")
                    or algo_params.get("clientAlgoId"),
                    "clientOrderId": algo_resp.get("clientAlgoId")
                    or algo_resp.get("clientOrderId")
                    or algo_params.get("clientAlgoId"),
                    "transactTime": algo_resp.get("timestamp"),
                    "price": str(algo_resp.get("price", "0")),
                    "stopPrice": str(stop_price or "0"),
                    "origQty": str(quantity or "0"),
                    "status": "NEW"
                    if algo_resp.get("status") in {"NEW", "open"}
                    else algo_resp.get("status", "NEW"),
                    "type": order_type_upper,
                    "side": side.upper(),
                }

            if (
                self.exchange_id in ["bybit", "bitget", "gateio"]
                and not self.supports_positions
                and ccxt_side == "buy"
                and ccxt_type == "market"
                and price is None
                and quantity is not None
            ):
                ticker = await self.get_ticker_price(symbol)
                if ticker and ticker.get("price"):
                    price = float(ticker["price"])

            request_amount = self._amount_for_exchange_request(ccxt_symbol, quantity)
            logger.info(
                f"CCXT: Placing order {symbol} {side} {order_type} Qty={quantity} Price={price} Params={params}"
            )
            try:
                order = await self._exchange.create_order(
                    symbol=ccxt_symbol,
                    type=ccxt_type,
                    side=ccxt_order_side,
                    amount=request_amount,
                    price=float(price) if price is not None else None,
                    params=params,
                )
            except Exception as order_exc:
                exc_str = str(order_exc)
                if self.exchange_id == "bitget" and "40774" in exc_str:
                    logger.warning(
                        "Bitget detected Unilateral (One-Way) Mode. Retrying without Hedge params..."
                    )
                    self._bitget_is_unilateral = True
                    params.pop("tradeSide", None)
                    params.pop("positionSide", None)
                    params["hedged"] = False
                    order = await self._exchange.create_order(
                        symbol=ccxt_symbol,
                        type=ccxt_type,
                        side=ccxt_order_side,
                        amount=request_amount,
                        price=float(price) if price is not None else None,
                        params=params,
                    )
                else:
                    raise order_exc

            # Bybit often returns only an acknowledgement in ``info`` for
            # create_order, leaving unified fields like side/symbol/amount as
            # None. Preserve the request context so controller code receives a
            # stable Binance-like response.
            if not order.get("symbol"):
                order["symbol"] = ccxt_symbol
            if not order.get("side"):
                order["side"] = ccxt_side
            if not order.get("type"):
                order["type"] = ccxt_type
            if not order.get("amount") and request_amount is not None:
                order["amount"] = request_amount
            if not order.get("clientOrderId") and params.get("clientOrderId"):
                order["clientOrderId"] = params.get("clientOrderId")

            # Map CCXT unified order to Binance-like response for Controller
            return self._map_ccxt_order_to_binance(order)

        except Exception as e:
            logger.error(
                f"Error placing order on {self.exchange_id}: {e}", exc_info=True
            )
            return {"error": True, "code": -999, "msg": str(e)}

    async def cancel_order(
        self,
        symbol: str,
        orderId: Optional[int] = None,
        origClientOrderId: Optional[str] = None,
        is_algo_order: bool = False,
    ) -> Dict[str, Any]:
        ccxt_symbol = self._normalize_symbol(symbol)

        try:
            if (
                self.exchange_id == "binance"
                and self.market_type == "futures_usdtm"
                and is_algo_order
            ):
                cancel_params = {"symbol": symbol.upper()}
                if orderId:
                    cancel_params["algoId"] = orderId

                logger.info(
                    f"CCXT: Cancelling Binance Futures Algo Order {symbol} Params={cancel_params}"
                )
                await self._call_exchange_method(
                    [
                        "fapiPrivateDeleteAlgoOrder",
                        "fapiprivateDeleteAlgoorder",
                        "fapiprivate_delete_algoorder",
                    ],
                    cancel_params,
                    fallback_path="algoOrder",
                    fallback_api="fapiPrivate",
                    fallback_http_method="DELETE",
                )

                return {
                    "symbol": symbol.upper(),
                    "orderId": orderId,
                    "origClientOrderId": origClientOrderId,
                    "clientOrderId": origClientOrderId,
                    "status": "CANCELED",
                }

            # We must pass either id or clientOrderId
            order_id_to_use = str(orderId) if orderId else None
            params = {}
            if (
                self.exchange_id == "bitget"
                and not self.supports_positions
                and is_algo_order
            ):
                params["stop"] = True
                params["trigger"] = True
            if (
                self.exchange_id == "gateio"
                and self.supports_positions
                and is_algo_order
            ):
                params["trigger"] = True
                params["type"] = "swap"
                params["settle"] = "usdt"
            if (
                self.exchange_id == "gateio"
                and not self.supports_positions
                and is_algo_order
            ):
                params["trigger"] = True
                params["type"] = "spot"

            if origClientOrderId:
                params["clientOrderId"] = origClientOrderId
                if not order_id_to_use:
                    order_id_to_use = origClientOrderId

            if not order_id_to_use:
                raise ValueError(
                    "Must provide either orderId or origClientOrderId to cancel order."
                )

            logger.info(
                f"CCXT: Cancelling order {symbol} ID={order_id_to_use} Params={params}"
            )
            await self._exchange.cancel_order(order_id_to_use, ccxt_symbol, params)

            return {
                "symbol": symbol.upper(),
                "orderId": orderId,
                "origClientOrderId": origClientOrderId,
                "clientOrderId": origClientOrderId,
                "status": "CANCELED",
            }

        except Exception as e:
            logger.error(
                f"Error cancelling order on {self.exchange_id}: {e}", exc_info=True
            )
            return {"error": True, "code": -999, "msg": str(e)}

    async def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ccxt_symbol = self._normalize_symbol(symbol) if symbol else None
        try:
            params = {}
            if self.exchange_id == "bitget" and self.supports_positions:
                params["productType"] = "usdt-futures"
            if self.exchange_id == "gateio" and self.supports_positions:
                params["type"] = "swap"
                params["settle"] = "usdt"
            if self.exchange_id == "bingx" and self.supports_positions:
                params["type"] = "swap"
            orders = await self._exchange.fetch_open_orders(ccxt_symbol, params=params)
            if self.exchange_id == "bitget" and not self.supports_positions:
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol, params={"stop": True}
                    )
                    if isinstance(trigger_orders, list):
                        orders.extend(trigger_orders)
                except Exception as te:
                    logger.warning(f"Could not fetch Bitget spot trigger orders: {te}")
            if self.exchange_id == "gateio" and not self.supports_positions:
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol,
                        params={"trigger": True, "type": "spot"},
                    )
                    if isinstance(trigger_orders, list):
                        orders.extend(trigger_orders)
                except Exception as te:
                    logger.warning(f"Could not fetch Gate.io spot trigger orders: {te}")
            return [self._map_ccxt_order_to_binance(o) for o in orders]
        except Exception as e:
            logger.error(
                f"Error getting open orders on {self.exchange_id}: {e}", exc_info=True
            )
            return []

    async def get_open_algo_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Best-effort unified view of open trigger/conditional orders."""
        if self.exchange_id == "binance" and self.market_type == "futures_usdtm":
            params = {}
            if symbol:
                params["symbol"] = symbol.upper()
            try:
                response = await self._call_exchange_method(
                    [
                        "fapiPrivateGetOpenAlgoOrders",
                        "fapiprivateGetOpenalgoorders",
                        "fapiprivate_get_openalgoorders",
                    ],
                    params,
                    fallback_path="openAlgoOrders",
                    fallback_api="fapiPrivate",
                    fallback_http_method="GET",
                )
                raw_orders = (
                    response.get("orders", response)
                    if isinstance(response, dict)
                    else response
                )
                if isinstance(raw_orders, list):
                    return [self._map_binance_algo_order(o, symbol) for o in raw_orders]
            except Exception as e:
                logger.warning(
                    f"Could not fetch Binance Futures open algo orders for {symbol or 'all symbols'}; "
                    f"falling back to unified open orders: {e}"
                )

        if self.exchange_id == "bitget" and self.supports_positions:
            ccxt_symbol = self._normalize_symbol(symbol) if symbol else None
            algo_orders_by_id: Dict[str, Dict[str, Any]] = {}
            for plan_type in ("profit_loss", "normal_plan", "track_plan"):
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol,
                        params={
                            "trigger": True,
                            "planType": plan_type,
                            "productType": "usdt-futures",
                        },
                    )
                    for raw_order in trigger_orders or []:
                        mapped_order = self._map_ccxt_order_to_binance(raw_order)
                        order_id = str(
                            mapped_order.get("orderId") or mapped_order.get("id") or ""
                        )
                        if order_id:
                            algo_orders_by_id[order_id] = mapped_order
                except Exception as e:
                    logger.warning(
                        f"Could not fetch Bitget {plan_type} open plan orders for {symbol or 'all symbols'}: {e}"
                    )
            return list(algo_orders_by_id.values())

        if self.exchange_id == "gateio" and self.supports_positions:
            ccxt_symbol = self._normalize_symbol(symbol) if symbol else None
            try:
                trigger_orders = await self._exchange.fetch_open_orders(
                    ccxt_symbol,
                    params={
                        "trigger": True,
                        "type": "swap",
                        "settle": "usdt",
                    },
                )
                return [
                    self._map_ccxt_order_to_binance(o) for o in trigger_orders or []
                ]
            except Exception as e:
                logger.warning(
                    f"Could not fetch Gate.io open trigger orders for {symbol or 'all symbols'}: {e}"
                )
                return []

        if self.exchange_id == "gateio" and not self.supports_positions:
            ccxt_symbol = self._normalize_symbol(symbol) if symbol else None
            try:
                trigger_orders = await self._exchange.fetch_open_orders(
                    ccxt_symbol,
                    params={"trigger": True, "type": "spot"},
                )
                return [
                    self._map_ccxt_order_to_binance(o) for o in trigger_orders or []
                ]
            except Exception as e:
                logger.warning(
                    f"Could not fetch Gate.io spot open trigger orders for {symbol or 'all symbols'}: {e}"
                )
                return []

        if self.exchange_id == "okx":
            ccxt_symbol = self._normalize_symbol(symbol) if symbol else None
            try:
                trigger_orders = await self._exchange.fetch_open_orders(
                    ccxt_symbol,
                    params={"stop": True},
                )
                return [
                    self._map_ccxt_order_to_binance(o) for o in trigger_orders or []
                ]
            except Exception as e:
                logger.warning(
                    f"Could not fetch OKX open trigger orders for {symbol or 'all symbols'}: {e}"
                )
                return []

        orders = await self.get_open_orders(symbol)
        algo_orders: List[Dict[str, Any]] = []
        for order in orders:
            order_type = str(order.get("type") or "").upper()
            stop_price = self._safe_float(order.get("stopPrice"))
            if (
                stop_price > 0
                or "STOP" in order_type
                or "TAKE_PROFIT" in order_type
                or "TRAILING" in order_type
            ):
                algo_orders.append(order)
        return algo_orders

    async def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        ccxt_symbol = self._normalize_symbol(symbol)
        try:
            cancel_all_orders = getattr(self._exchange, "cancel_all_orders", None)
            if callable(cancel_all_orders) and self.exchange_id != "gateio":
                try:
                    response = await cancel_all_orders(ccxt_symbol)
                    return {
                        "symbol": symbol.upper(),
                        "status": "OK",
                        "response": response,
                    }
                except Exception as bulk_cancel_error:
                    logger.warning(
                        f"Bulk cancel is unavailable on {self.exchange_id} for {symbol}; "
                        f"falling back to per-order cancellation: {bulk_cancel_error}"
                    )

            fetch_params = {}
            if self.exchange_id == "gateio" and self.supports_positions:
                fetch_params = {"type": "swap", "settle": "usdt"}
            if fetch_params:
                orders = await self._exchange.fetch_open_orders(
                    ccxt_symbol, params=fetch_params
                )
            else:
                orders = await self._exchange.fetch_open_orders(ccxt_symbol)
            if self.exchange_id == "bitget":
                if self.supports_positions:
                    for plan_type in ("profit_loss", "normal_plan", "track_plan"):
                        try:
                            trigger_orders = await self._exchange.fetch_open_orders(
                                ccxt_symbol,
                                params={
                                    "trigger": True,
                                    "planType": plan_type,
                                    "productType": "usdt-futures",
                                },
                            )
                            if isinstance(trigger_orders, list):
                                orders.extend(trigger_orders)
                        except Exception as te:
                            logger.warning(
                                f"Could not fetch Bitget futures {plan_type} orders for cancellation: {te}"
                            )
                else:
                    try:
                        trigger_orders = await self._exchange.fetch_open_orders(
                            ccxt_symbol, params={"stop": True}
                        )
                        if isinstance(trigger_orders, list):
                            orders.extend(trigger_orders)
                    except Exception as te:
                        logger.warning(
                            f"Could not fetch Bitget spot trigger orders for cancellation: {te}"
                        )
            if self.exchange_id == "gateio" and self.supports_positions:
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol,
                        params={"trigger": True, "type": "swap", "settle": "usdt"},
                    )
                    if isinstance(trigger_orders, list):
                        orders.extend(trigger_orders)
                except Exception as te:
                    logger.warning(
                        f"Could not fetch Gate.io trigger orders for cancellation: {te}"
                    )
            if self.exchange_id == "gateio" and not self.supports_positions:
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol,
                        params={"trigger": True, "type": "spot"},
                    )
                    if isinstance(trigger_orders, list):
                        orders.extend(trigger_orders)
                except Exception as te:
                    logger.warning(
                        f"Could not fetch Gate.io spot trigger orders for cancellation: {te}"
                    )
            if self.exchange_id == "okx":
                try:
                    trigger_orders = await self._exchange.fetch_open_orders(
                        ccxt_symbol,
                        params={"stop": True},
                    )
                    if isinstance(trigger_orders, list):
                        orders.extend(trigger_orders)
                except Exception as te:
                    logger.warning(
                        f"Could not fetch OKX trigger orders for cancellation: {te}"
                    )
            results = []
            for order in orders:
                order_id = order.get("id")
                if not order_id:
                    continue
                try:
                    cancel_params = {}
                    if self.exchange_id == "bitget":
                        info = order.get("info") or {}
                        if "planType" in info:
                            cancel_params["planType"] = info["planType"]
                        if self.supports_positions and (
                            "planType" in info
                            or "triggerPrice" in info
                            or order.get("stopPrice")
                        ):
                            cancel_params["stop"] = True
                            cancel_params["trigger"] = True
                            cancel_params.setdefault("planType", "profit_loss")
                            cancel_params.setdefault("productType", "usdt-futures")
                        elif not self.supports_positions and (
                            "planType" in info
                            or "triggerPrice" in info
                            or order.get("stopPrice")
                        ):
                            cancel_params["stop"] = True
                            cancel_params["trigger"] = True
                    if self.exchange_id == "gateio" and self.supports_positions:
                        cancel_params["type"] = "swap"
                        cancel_params["settle"] = "usdt"
                        if (
                            order.get("triggerPrice")
                            or order.get("stopPrice")
                            or (order.get("info") or {}).get("trigger")
                        ):
                            cancel_params["trigger"] = True
                    if self.exchange_id == "gateio" and not self.supports_positions:
                        cancel_params["type"] = "spot"
                        if (
                            order.get("triggerPrice")
                            or order.get("stopPrice")
                            or (order.get("info") or {}).get("trigger")
                        ):
                            cancel_params["trigger"] = True
                    if self.exchange_id == "okx":
                        if order.get("type") == "trigger" or order.get("stopPrice"):
                            cancel_params["stop"] = True
                    results.append(
                        await self._exchange.cancel_order(
                            order_id, ccxt_symbol, cancel_params
                        )
                    )
                except Exception as cancel_error:
                    logger.error(
                        f"Error cancelling order {order_id} on {self.exchange_id}: {cancel_error}",
                        exc_info=True,
                    )
            return {
                "symbol": symbol.upper(),
                "status": "OK",
                "cancelled": len(results),
                "results": results,
            }
        except Exception as e:
            logger.error(
                f"Error cancelling all open orders on {self.exchange_id} for {symbol}: {e}",
                exc_info=True,
            )
            return {
                "error": True,
                "code": -999,
                "msg": str(e),
                "symbol": symbol.upper(),
            }

    async def get_account_balance(self) -> Optional[Dict[str, Dict[str, str]]]:
        try:
            params = {}
            if self.exchange_id == "bitget":
                if self.supports_positions:
                    params["type"] = "swap"
                    params["productType"] = "usdt-futures"
                else:
                    params["type"] = "spot"
            if self.exchange_id == "gateio":
                if self.supports_positions:
                    params["type"] = "swap"
                    params["settle"] = "usdt"
                else:
                    params["type"] = "spot"
            if self.exchange_id == "bingx":
                params["type"] = "swap" if self.supports_positions else "spot"
            balance = await self._exchange.fetch_balance(params)
            mapped_balances = {}

            # balance contains total, free, used
            if "total" in balance:
                assets = (
                    set(balance.get("total", {}).keys())
                    | set(balance.get("free", {}).keys())
                    | set(balance.get("used", {}).keys())
                )
                for asset in assets:
                    mapped_asset = self._normalize_balance_asset(asset)
                    total_val = self._safe_float(balance.get("total", {}).get(asset))
                    free_val = self._safe_float(balance.get("free", {}).get(asset))
                    used_val = self._safe_float(balance.get("used", {}).get(asset))
                    if total_val > 1e-9 or free_val > 1e-9 or used_val > 1e-9:
                        locked_val = (
                            used_val if used_val > 0 else max(total_val - free_val, 0.0)
                        )
                        current = mapped_balances.get(mapped_asset)
                        if current:
                            free_val += self._safe_float(current.get("free"))
                            locked_val += self._safe_float(current.get("locked"))
                        mapped_balances[mapped_asset] = {
                            "free": str(free_val),
                            "locked": str(locked_val),
                            "unrealized_pnl": "0",  # CCXT doesn't standardize unrealized_pnl across spot/futures well in balance
                        }
            if self.exchange_id == "bingx" and self.supports_positions:
                raw_data = (balance.get("info") or {}).get("data")
                raw_balances = []
                if isinstance(raw_data, list):
                    raw_balances = raw_data
                elif isinstance(raw_data, dict):
                    raw_balance = raw_data.get("balance")
                    if isinstance(raw_balance, list):
                        raw_balances = raw_balance
                    elif isinstance(raw_balance, dict):
                        raw_balances = [raw_balance]
                    elif raw_data:
                        raw_balances = [raw_data]

                for raw_balance in raw_balances:
                    if not isinstance(raw_balance, dict):
                        continue
                    asset = self._normalize_balance_asset(
                        raw_balance.get("asset") or "USDT"
                    )
                    raw_free_val = self._first_positive_float(
                        raw_balance,
                        (
                            "availableMargin",
                            "availableBalance",
                            "maxWithdrawAmount",
                            "trialFundBalance",
                            "trialFund",
                            "virtualBalance",
                            "virtualUsdt",
                            "balance",
                            "equity",
                        ),
                    )
                    raw_total_val = self._first_positive_float(
                        raw_balance,
                        (
                            "equity",
                            "balance",
                            "maxWithdrawAmount",
                            "availableMargin",
                            "trialFundBalance",
                            "trialFund",
                            "virtualBalance",
                            "virtualUsdt",
                        ),
                    )
                    if raw_free_val > 1e-9 or raw_total_val > 1e-9:
                        current_free = self._safe_float(
                            (mapped_balances.get(asset) or {}).get("free")
                        )
                        if current_free <= 1e-9:
                            mapped_balances[asset] = {
                                "free": str(raw_free_val),
                                "locked": str(max(raw_total_val - raw_free_val, 0.0)),
                                "unrealized_pnl": str(
                                    self._safe_float(
                                        raw_balance.get("unrealizedProfit")
                                    )
                                ),
                            }
            return mapped_balances
        except Exception as e:
            logger.error(
                f"Error fetching account balance on {self.exchange_id}: {e}",
                exc_info=True,
            )
            return None

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        if not self.supports_positions:
            return []

        try:
            # fetch_positions generally returns all positions across markets
            params = {}
            if self.exchange_id == "bitget":
                params["productType"] = "usdt-futures"
            if self.exchange_id == "gateio":
                params["type"] = "swap"
                params["settle"] = "usdt"
            if self.exchange_id == "bingx":
                params["type"] = "swap"
            positions = await self._exchange.fetch_positions(params=params)
            mapped_positions = []

            for pos in positions:
                # CCXT unified position has amount, symbol, contracts, entryPrice, side
                # Filter only active open positions
                quantity = abs(
                    self._safe_float(pos.get("contracts", pos.get("amount", 0) or 0))
                )
                if self._uses_gateio_contract_units():
                    quantity = self._contracts_to_base_quantity(
                        pos.get("symbol", ""), quantity
                    )

                # In CCXT, quantity might be signed or absolute depending on exchange,
                # but 'contracts' is absolute and pos['side'] gives direction.
                if quantity != 0:
                    raw_symbol = self._to_legacy_symbol(pos.get("symbol", ""))
                    side_value = str(pos.get("side") or "").lower()
                    signed_quantity = -quantity if side_value == "short" else quantity

                    # Controller expects fields like positionAmt, entryPrice
                    mapped_positions.append(
                        {
                            "symbol": raw_symbol,
                            "positionAmt": str(signed_quantity),
                            "entryPrice": str(pos.get("entryPrice", "0")),
                            "unrealizedProfit": str(pos.get("unrealizedPnl", "0")),
                            "markPrice": str(pos.get("markPrice", "0")),
                            "liquidationPrice": str(pos.get("liquidationPrice", "0")),
                        }
                    )
            return mapped_positions
        except Exception as e:
            logger.error(
                f"Error fetching open positions on {self.exchange_id}: {e}",
                exc_info=True,
            )
            return []

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[List[Any]]:
        ccxt_symbol = self._normalize_symbol(symbol)
        try:
            return await self._exchange.fetch_ohlcv(
                ccxt_symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
                params=params or {},
            )
        except Exception as e:
            logger.error(
                f"Error fetching OHLCV on {self.exchange_id} for {symbol}: {e}",
                exc_info=True,
            )
            return []

    async def start_user_data_stream(
        self, callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]
    ) -> Any:
        if self._exchange_pro is None:
            logger.warning(
                f"CCXT Pro is not available or not instantiated for {self.exchange_id}. UserData Stream disabled."
            )
            return None

        if self.sandbox and self.exchange_id in {"gateio", "bingx"}:
            logger.warning(
                "CCXT Pro UserData Stream disabled for %s sandbox. "
                "Testnet private WebSocket is unreliable/unsupported in CCXT Pro; "
                "REST polling and reconciliation remain active.",
                self.exchange_id,
            )
            return None

        self._user_data_running = True

        # Gate.io requires UID for private websocket subscriptions
        if self.exchange_id == "gateio" and not getattr(
            self._exchange_pro, "uid", None
        ):
            try:
                # Try to fetch account info to get UID
                # We call fetch_balance directly on the REST client to get the raw 'info' field
                params = {}
                if self.supports_positions:
                    params["type"] = "swap"
                    params["settle"] = "usdt"
                else:
                    params["type"] = "spot"

                balance = await self._exchange.fetch_balance(params)
                if balance and "info" in balance:
                    # Depending on API version, UID might be in different places
                    uid = None
                    info = balance["info"]
                    if isinstance(info, dict):
                        uid = (
                            info.get("user", {}).get("id")
                            or info.get("userId")
                            or info.get("uid")
                            or info.get("id")
                            or info.get("user_id")
                        )
                    if uid:
                        logger.info(f"Automatically detected Gate.io UID: {uid}")
                        self._set_gateio_uid(str(uid))
            except Exception as e:
                logger.warning(f"Failed to auto-detect Gate.io UID: {e}")

        async def user_data_listener():
            while self._user_data_running:
                try:
                    # CCXT.pro unified stream for orders across most exchanges
                    # Note: Not all exchanges support all streams.
                    params = {}
                    if self.exchange_id == "gateio":
                        params["type"] = "swap" if self.supports_positions else "spot"

                    orders = await self._exchange_pro.watch_orders(params=params)
                    if orders:
                        for order in orders:
                            execution_report = self._to_execution_report(order)
                            await callback(execution_report)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(
                        f"Error in CCXT Pro UserData listener for {self.exchange_id}: {e}",
                        exc_info=True,
                    )
                    await asyncio.sleep(5)

        self._user_data_task = asyncio.create_task(
            user_data_listener(), name=f"CcxtProUserData_{self.exchange_id}"
        )
        logger.info(f"CCXT Pro UserData Stream started for {self.exchange_id}.")
        return self._user_data_task

    async def stop_user_data_stream(self) -> Any:
        self._user_data_running = False
        if self._user_data_task and not self._user_data_task.done():
            self._user_data_task.cancel()
            try:
                await self._user_data_task
            except asyncio.CancelledError:
                pass
        logger.info(f"CCXT Pro UserData Stream stopped for {self.exchange_id}.")

    # --- Internal Helpers ---

    def _patch_binance_demo_urls(self, exchange: Any) -> None:
        api_urls = exchange.urls.get("api")
        if not isinstance(api_urls, dict):
            return

        if "spot" in self.market_type:
            for key in ("public", "private", "v1"):
                value = api_urls.get(key)
                if isinstance(value, str):
                    api_urls[key] = value.replace(
                        "api.binance.com", "demo-api.binance.com"
                    )
        else:
            for key in (
                "fapiPublic",
                "fapiPublicV2",
                "fapiPublicV3",
                "fapiPrivate",
                "fapiPrivateV2",
                "fapiPrivateV3",
                "fapiData",
            ):
                value = api_urls.get(key)
                if isinstance(value, str):
                    api_urls[key] = value.replace(
                        "fapi.binance.com", "demo-fapi.binance.com"
                    )

        ws_urls = api_urls.get("ws")
        if isinstance(ws_urls, dict):
            if "spot" in self.market_type:
                ws_urls["spot"] = "wss://demo-stream.binance.com/ws"
                ws_urls["margin"] = "wss://demo-stream.binance.com/ws"
                ws_api = ws_urls.get("ws-api")
                if isinstance(ws_api, dict):
                    ws_api["spot"] = "wss://demo-ws-api.binance.com/ws-api/v3"
            else:
                ws_urls["future"] = "wss://demo-fstream.binance.com/ws"

        exchange.urls["ws"] = {
            "public": "wss://demo-stream.binance.com/ws"
            if "spot" in self.market_type
            else "wss://demo-fstream.binance.com/ws",
            "private": "wss://demo-stream.binance.com/ws"
            if "spot" in self.market_type
            else "wss://demo-fstream.binance.com/ws",
        }

        # Helper for private WS URL (used in tests and potential custom implementations)
        def get_private_ws_url(symbol_type: str, listen_key: str) -> str:
            base = (
                "wss://demo-fstream.binance.com"
                if symbol_type == "future"
                else "wss://demo-stream.binance.com"
            )
            return f"{base}/private/ws?listenKey={listen_key}"

        exchange.get_private_ws_url = get_private_ws_url

    def _set_gateio_uid(self, uid: str) -> None:
        uid = str(uid or "").strip()
        if not uid:
            return
        for exchange in (self._exchange, self._exchange_pro):
            if exchange is None:
                continue
            exchange.uid = uid
            exchange.options["uid"] = uid

    @staticmethod
    def _patch_gateio_swap_market_loader(exchange: Any) -> None:
        fetch_contract_markets = getattr(exchange, "fetch_contract_markets", None)
        if not callable(fetch_contract_markets):
            return

        async def fetch_swap_markets(params: Optional[Dict[str, Any]] = None):
            return await fetch_contract_markets(params or {})

        exchange.fetch_markets = fetch_swap_markets

    async def _call_exchange_method(
        self,
        method_names: List[str],
        params: Dict[str, Any],
        fallback_path: Optional[str] = None,
        fallback_api: str = "fapiPrivate",
        fallback_http_method: str = "GET",
    ) -> Any:
        for method_name in method_names:
            method = getattr(self._exchange, method_name, None)
            if callable(method):
                return await method(params)
        request = getattr(self._exchange, "request", None)
        if callable(request) and fallback_path:
            return await request(
                fallback_path, fallback_api, fallback_http_method, params
            )
        raise AttributeError(
            f"{self.exchange_id} CCXT client has none of these methods: {', '.join(method_names)}"
        )

    def _map_binance_algo_order(
        self, order: Dict[str, Any], fallback_symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        trigger_price = (
            order.get("triggerPrice")
            or order.get("stopPrice")
            or order.get("price")
            or "0"
        )
        quantity = (
            order.get("quantity")
            or order.get("origQty")
            or order.get("executedQty")
            or "0"
        )
        algo_id = order.get("algoId") or order.get("orderId")
        client_id = order.get("clientAlgoId") or order.get("clientOrderId")
        return {
            "symbol": str(order.get("symbol") or fallback_symbol or "").upper(),
            "algoId": algo_id,
            "orderId": algo_id,
            "clientAlgoId": client_id,
            "clientOrderId": client_id,
            "transactTime": order.get("timestamp")
            or order.get("updateTime")
            or order.get("createdTime"),
            "price": str(order.get("price", "0")),
            "stopPrice": str(trigger_price),
            "origQty": str(quantity),
            "executedQty": str(order.get("executedQty", "0")),
            "status": str(order.get("status") or "NEW").upper(),
            "type": str(order.get("type") or "").upper(),
            "side": str(order.get("side") or "").upper(),
        }

    def _normalize_symbol(self, symbol: str) -> str:
        """Converts Binance format (BTCUSDT) to CCXT format (BTC/USDT or BTC/USDT:USDT)."""
        symbol_upper = symbol.upper().replace(":", ":")
        if "/" in symbol_upper:
            if self.supports_positions and ":" not in symbol_upper:
                quote = symbol_upper.split("/", 1)[1].split(":", 1)[0]
                return f"{symbol_upper}:{quote}"
            return symbol_upper
        if symbol_upper.endswith("USDT"):
            base = symbol_upper[:-4]
            if self.supports_positions:
                return f"{base}/USDT:USDT"
            return f"{base}/USDT"
        return symbol_upper

    @staticmethod
    def _default_ccxt_market_type(exchange_id: str) -> str:
        if exchange_id == "binance":
            return "future"
        return "swap"

    @staticmethod
    def _to_legacy_symbol(symbol: Optional[str]) -> str:
        if not symbol:
            return ""
        return symbol.replace("/", "").replace(":USDT", "").replace(":USDC", "").upper()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _first_positive_float(
        self, values: Dict[str, Any], keys: tuple[str, ...]
    ) -> float:
        for key in keys:
            parsed = self._safe_float(values.get(key))
            if parsed > 1e-9:
                return parsed
        return 0.0

    def _normalize_balance_asset(self, asset: Any) -> str:
        normalized = str(asset or "").upper()
        if (
            self.exchange_id == "bingx"
            and getattr(self, "sandbox", False)
            and normalized == "VST"
        ):
            return "USDT"
        return normalized

    def _precision_to_step(self, precision: Any, default: float) -> float:
        if precision is None:
            return default
        try:
            if getattr(self._exchange, "precisionMode", None) == getattr(
                ccxt, "TICK_SIZE", 4
            ):
                return float(precision)
            precision_int = int(precision)
            return float(Decimal("1").scaleb(-precision_int))
        except Exception:
            return self._safe_float(precision, default)

    def _uses_gateio_contract_units(self) -> bool:
        return self.exchange_id == "gateio" and self.supports_positions

    def _market_contract_size(
        self, symbol: Optional[str], market: Optional[Dict[str, Any]] = None
    ) -> float:
        market_data = market
        if market_data is None and symbol:
            markets = getattr(self._exchange, "markets", None) or {}
            market_data = markets.get(symbol)
            if market_data is None:
                try:
                    market_method = getattr(self._exchange, "market", None)
                    if callable(market_method):
                        market_data = market_method(symbol)
                except Exception:
                    market_data = None
        contract_size = self._safe_float((market_data or {}).get("contractSize"), 1.0)
        return contract_size if contract_size > 0 else 1.0

    def _normalize_amount_units_for_market(
        self,
        symbol: Optional[str],
        market: Dict[str, Any],
        amount_step: float,
        min_qty: float,
        max_qty: float,
    ) -> tuple[float, float, float]:
        if not self._uses_gateio_contract_units() or not market.get("contract"):
            return amount_step, min_qty, max_qty
        contract_size = self._market_contract_size(symbol, market)
        return (
            amount_step * contract_size,
            min_qty * contract_size,
            max_qty * contract_size,
        )

    def _amount_for_exchange_request(
        self, symbol: str, quantity: Any
    ) -> Optional[float]:
        if quantity is None:
            return None
        amount = float(quantity)
        if not self._uses_gateio_contract_units():
            return amount
        contract_size = self._market_contract_size(symbol)
        contracts = amount / contract_size
        rounded_contracts = int(round(contracts))
        if rounded_contracts <= 0:
            rounded_contracts = 1
        return float(rounded_contracts)

    def _contracts_to_base_quantity(
        self, symbol: Optional[str], contracts: Any
    ) -> float:
        amount = self._safe_float(contracts)
        if not self._uses_gateio_contract_units():
            return amount
        return float(f"{amount * self._market_contract_size(symbol):.12g}")

    @staticmethod
    def _map_order_type_to_ccxt(order_type: str) -> str:
        if order_type in {"MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            return "market"
        if order_type in {"LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"}:
            return "limit"
        if order_type in {"STOP_LOSS", "STOP"}:
            return "market"
        return order_type.lower()

    @staticmethod
    def _bybit_trigger_direction(order_type: str, side: str) -> Optional[int]:
        if "TAKE_PROFIT" in order_type:
            return 1 if side == "sell" else 2
        if "STOP" in order_type:
            return 2 if side == "sell" else 1
        return None

    def _map_ccxt_order_to_binance(self, ccxt_order: Dict[str, Any]) -> Dict[str, Any]:
        """Maps CCXT unified order object into legacy Binance place_order response."""
        info = ccxt_order.get("info") or {}
        raw_type = str(
            ccxt_order.get("type") or info.get("orderType") or info.get("type") or ""
        ).upper()
        amount = self._safe_float(
            ccxt_order.get("amount")
            or info.get("qty")
            or info.get("quantity")
            or info.get("origQty")
        )
        filled = self._safe_float(
            ccxt_order.get("filled")
            or info.get("cumExecQty")
            or info.get("executedQty")
            or info.get("filled")
        )
        average = self._safe_float(
            ccxt_order.get("average")
            or ccxt_order.get("avgPrice")
            or info.get("avgPrice")
            or info.get("avgFillPrice")
        )
        price = self._safe_float(ccxt_order.get("price") or info.get("price"))
        effective_price = average or price
        status = self._map_status_to_binance(ccxt_order.get("status"))
        if status == "NEW" and amount > 0 and filled >= amount * (1 - 1e-9):
            status = "FILLED"
        trigger_price = (
            ccxt_order.get("triggerPrice")
            or ccxt_order.get("stopPrice")
            or info.get("stopPrice")
            or info.get("triggerPrice")
        )
        raw_side = ccxt_order.get("side") or info.get("side") or ""
        side_upper = str(raw_side).upper()
        raw_symbol = ccxt_order.get("symbol") or info.get("symbol") or ""
        if self._uses_gateio_contract_units():
            amount = self._contracts_to_base_quantity(raw_symbol, amount)
            filled = self._contracts_to_base_quantity(raw_symbol, filled)
        return {
            "symbol": self._to_legacy_symbol(raw_symbol),
            "orderId": ccxt_order.get("id") or info.get("orderId"),
            "clientOrderId": ccxt_order.get("clientOrderId")
            or info.get("orderLinkId")
            or info.get("clientOrderId"),
            "transactTime": ccxt_order.get("timestamp")
            or info.get("createdTime")
            or info.get("updatedTime"),
            "price": str(effective_price or 0),
            "avgPrice": str(effective_price or 0),
            "stopPrice": str(trigger_price or "0"),
            "origQty": str(amount or 0),
            "executedQty": str(filled or 0),
            "status": status,
            "type": raw_type,
            "side": side_upper,
        }

    def _map_status_to_binance(self, ccxt_status: Optional[str]) -> str:
        if not ccxt_status:
            return "NEW"
        status_map = {
            "open": "NEW",
            "closed": "FILLED",
            "canceled": "CANCELED",
            "expired": "EXPIRED",
            "rejected": "REJECTED",
        }
        return status_map.get(ccxt_status.lower(), "NEW")

    def _to_execution_report(self, ccxt_order: Dict[str, Any]) -> Dict[str, Any]:
        """Converts CCXT unified order to Binance executionReport format for TradingController."""
        now_ms = int(time.time() * 1000)
        raw_symbol = ccxt_order.get("symbol", "")
        amount = ccxt_order.get("amount", "0") or "0"
        filled_value = ccxt_order.get("filled", "0") or "0"
        last_value = (
            ccxt_order.get("lastTradeAmount")
            or ccxt_order.get("lastTradeQuantity")
            or filled_value
        )
        if self._uses_gateio_contract_units():
            amount = self._contracts_to_base_quantity(raw_symbol, amount)
            filled_value = self._contracts_to_base_quantity(raw_symbol, filled_value)
            last_value = self._contracts_to_base_quantity(raw_symbol, last_value)
        filled = str(filled_value)
        status = self._map_status_to_binance(ccxt_order.get("status"))
        if status == "NEW" and self._safe_float(filled) > 0:
            status = "PARTIALLY_FILLED"
        last = str(last_value)
        trigger_price = (
            ccxt_order.get("triggerPrice")
            or ccxt_order.get("stopPrice")
            or (ccxt_order.get("info") or {}).get("stopPrice")
            or (ccxt_order.get("info") or {}).get("triggerPrice")
            or "0"
        )
        fee = ccxt_order.get("fee") or {}
        return {
            "e": "executionReport",
            "E": now_ms,
            "s": self._to_legacy_symbol(raw_symbol),
            "c": ccxt_order.get("clientOrderId") or "",
            "S": ccxt_order.get("side", "").upper(),
            "o": ccxt_order.get("type", "").upper(),
            "f": "GTC",
            "q": str(amount),
            "p": str(ccxt_order.get("price", "0")),
            "P": str(trigger_price),
            "x": "TRADE" if status in {"FILLED", "PARTIALLY_FILLED"} else status,
            "X": status,
            "i": ccxt_order.get("id"),
            "z": filled,
            "l": last,
            "L": str(ccxt_order.get("average", "0") or "0"),
            "n": str(fee.get("cost") or "0"),
            "N": fee.get("currency"),
            "T": now_ms,
            "t": -1,
            "w": True,
            "m": False,
            "O": ccxt_order.get("timestamp", now_ms),
        }
