# bot_module/executor.py
import asyncio
import aiohttp
import json
import hashlib
import hmac
import time
import logging
from typing import Dict, Any, Optional, Callable, Coroutine, List
from decimal import ROUND_DOWN, Decimal, InvalidOperation
import backoff
import pandas as pd

try:
    import websockets
    from websockets.protocol import State
    from websockets.exceptions import (
        ConnectionClosedOK,
        ConnectionClosedError,
        ConnectionClosed,
        InvalidStatus,
    )
except ImportError:
    websockets = None
    ConnectionClosedOK = ConnectionClosedError = ConnectionClosed = InvalidStatus = (
        Exception  # type: ignore
    )
    State = None  # type: ignore
    logging.critical(
        "`websockets` library not installed. UserData stream functionality will be disabled. Run: pip install websockets"
    )

from bot_module import config

logger = logging.getLogger("bot_module.executor")
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    logger.warning(
        "Root logger 'bot_module' has no handlers. Basic config applied to root logger."
    )


def _generate_signature(query_string: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _get_timestamp() -> int:
    return int(time.time() * 1000)


class BinanceExecutor:
    """
    Responsible for interaction with the Binance API: placing/canceling orders,
    retrieving account information, and managing User Data Stream.
    """

    # Updating the constructor
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        session: aiohttp.ClientSession,
        market_type: str = "futures_usdtm",
    ):
        self.api_key = api_key if api_key is not None else config.BINANCE_ACTIVE_API_KEY
        self.api_secret = (
            api_secret if api_secret is not None else config.BINANCE_ACTIVE_API_SECRET
        )
        self.market_type = market_type or config.TRADING_MARKET_TYPE

        self._session = session
        self._session_owner = False

        if config.ACTIVE_TRADING_ENVIRONMENT == "testnet":
            if self.market_type == "spot":
                self.base_url = config.BINANCE_SPOT_TESTNET_API_URL
                self.ws_base_url = config.BINANCE_SPOT_TESTNET_USER_DATA_WS_URL
            elif self.market_type == "futures_usdtm":
                self.base_url = config.BINANCE_FUTURES_TESTNET_API_URL
                self.ws_base_url = config.BINANCE_FUTURES_TESTNET_USER_DATA_WS_URL
            else:
                raise ValueError(
                    f"Unsupported self.market_type '{self.market_type}' for 'testnet' in Executor __init__."
                )
        elif config.ACTIVE_TRADING_ENVIRONMENT == "mainnet":
            if self.market_type == "spot":
                self.base_url = config.BINANCE_SPOT_MAINNET_API_URL
                self.ws_base_url = config.BINANCE_SPOT_MAINNET_USER_DATA_WS_URL
            elif self.market_type == "futures_usdtm":
                self.base_url = config.BINANCE_FUTURES_USDTM_MAINNET_API_URL
                self.ws_base_url = config.BINANCE_FUTURES_USDTM_MAINNET_USER_DATA_WS_URL
            else:
                raise ValueError(
                    f"Unsupported self.market_type '{self.market_type}' for 'mainnet' in Executor __init__."
                )
        else:
            raise ValueError(
                f"Unsupported config.ACTIVE_TRADING_ENVIRONMENT: {config.ACTIVE_TRADING_ENVIRONMENT} in Executor __init__."
            )

        if self._session is None:
            logger.warning(
                "No shared aiohttp session provided to BinanceExecutor. Creating a new one."
            )
            timeout = aiohttp.ClientTimeout(total=config.API_REQUEST_TIMEOUT_SECONDS)
            try:
                current_loop = asyncio.get_running_loop()
                self._session = aiohttp.ClientSession(
                    loop=current_loop, timeout=timeout
                )
            except RuntimeError:
                self._session = aiohttp.ClientSession(timeout=timeout)
            self._session_owner = True
        elif self._session.closed:
            raise ConnectionError("Provided aiohttp session is closed.")

        self._exchange_info_cache: Optional[Dict[str, Any]] = None
        self._exchange_info_lock = asyncio.Lock()
        self._last_exchange_info_update: float = 0.0

        self._user_data_listen_key: Optional[str] = None
        self._user_data_ws: Optional[websockets.WebSocketClientProtocol] = None
        self._user_data_listener_task: Optional[asyncio.Task] = None
        self._user_data_keepalive_task: Optional[asyncio.Task] = None
        self._user_data_callback: Optional[Callable[[Dict[str, Any]], Coroutine]] = None
        self._user_data_running = False
        self._ws_connect_lock = asyncio.Lock()
        self._ws_reconnect_attempts = 0

        if not websockets:
            logger.critical(
                "`websockets` library is not available. UserData stream will not work."
            )

        logger.info(
            f"BinanceExecutor initialized for market: {self.market_type}. Using API Key ending: ...{self.api_key[-4:] if self.api_key else 'N/A'}"
        )

    async def close(self):
        logger.info("Closing BinanceExecutor...")
        await self.stop_user_data_stream()
        if self._session and self._session_owner and not self._session.closed:
            await self._session.close()
            logger.info("Internal aiohttp session closed by BinanceExecutor.")
        elif self._session and not self._session_owner:
            logger.debug("Shared aiohttp session not closed by BinanceExecutor.")
        self._session = None
        logger.info("BinanceExecutor closed.")

    def _get_number_of_decimal_places(self, number_str: str) -> int:
        try:
            # Using Decimal to handle scientific notation (e.g., '1e-05')
            return abs(Decimal(str(number_str)).as_tuple().exponent)
        except Exception:
            # Fallback to basic string parsing if Decimal fails
            if "." in number_str:
                return len(number_str.split(".")[1])
            return 0

    def _round_quantity(self, quantity: float, step_size: float) -> Optional[float]:
        if quantity <= 0 or step_size <= 0:
            logger.error(
                f"[_round_quantity] Invalid input: quantity={quantity}, step_size={step_size}"
            )
            return None
        try:
            quantity_dec = Decimal(str(quantity))
            step_size_dec = Decimal(str(step_size))
            rounded_qty = float((quantity_dec // step_size_dec) * step_size_dec)
            precision = self._get_number_of_decimal_places(str(step_size))
            return round(rounded_qty, precision)
        except (InvalidOperation, TypeError, Exception) as e:
            logger.error(
                f"[_round_quantity] Error rounding quantity {quantity} with step_size {step_size}: {e}",
                exc_info=True,
            )
            return None

    def _round_price(
        self, price: float, tick_size: float, rounding_mode: str = ROUND_DOWN
    ) -> Optional[float]:
        if price <= 0 or tick_size <= 0:
            logger.error(
                f"[_round_price] Invalid input: price={price}, tick_size={tick_size}"
            )
            return None
        try:
            price_dec = Decimal(str(price))
            tick_dec = Decimal(str(tick_size))
            rounded_price_dec = (price_dec / tick_dec).quantize(
                Decimal("0"), rounding=rounding_mode
            ) * tick_dec
            precision = self._get_number_of_decimal_places(str(tick_size))
            return float(f"{rounded_price_dec:.{precision}f}")
        except (InvalidOperation, TypeError, Exception) as e:
            logger.error(
                f"[_round_price] Error rounding price {price} with tick_size {tick_size}: {e}",
                exc_info=True,
            )
            return None

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=5,
        max_time=60,
        jitter=backoff.full_jitter,
        logger=logger,
        on_giveup=lambda details: logger.error(
            f"Giving up API request to {details['args'][1] if len(details['args']) > 1 else 'unknown endpoint'} after {details['tries']} tries. Error: {details.get('exception')}"
        ),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        if not self._session or self._session.closed:
            if self._session_owner:
                logger.warning(
                    "aiohttp session was closed or None. Recreating for owned session."
                )
                timeout = aiohttp.ClientTimeout(
                    total=config.API_REQUEST_TIMEOUT_SECONDS
                )
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None
                self._session = aiohttp.ClientSession(
                    loop=current_loop, timeout=timeout
                )
            else:
                logger.error(
                    "Shared aiohttp session is closed or None. Cannot make request."
                )
                return {
                    "error": True,
                    "code": -1000,
                    "msg": "Aiohttp session is not available.",
                }

        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        full_url = f"{self.base_url.removesuffix('/')}{endpoint}"

        headers = {"X-MBX-APIKEY": self.api_key}
        params_for_signing_and_request = params.copy() if params else {}

        if signed:
            params_for_signing_and_request["timestamp"] = _get_timestamp()
            params_for_signing_and_request["recvWindow"] = getattr(
                config, "API_RECV_WINDOW", 10000
            )

        payload_parts = []
        for key, value in sorted(params_for_signing_and_request.items()):
            if value is None:
                continue
            value_str = ""
            if isinstance(value, bool):
                value_str = str(value).lower()
            elif isinstance(value, list):
                try:
                    import requests.utils

                    value_str = requests.utils.quote(
                        json.dumps(value, separators=(",", ":"))
                    )
                except ImportError:
                    import urllib.parse

                    value_str = urllib.parse.quote(
                        json.dumps(value, separators=(",", ":"))
                    )
            else:
                value_str = str(value)
            payload_parts.append(f"{key}={value_str}")

        payload_string_to_sign = "&".join(payload_parts)

        request_kwargs: Dict[str, Any] = {"headers": headers}
        log_params_str_display = payload_string_to_sign

        url_for_request_with_params_in_query = full_url

        if signed:
            signature = _generate_signature(payload_string_to_sign, self.api_secret)
            if method.upper() == "GET" or method.upper() == "DELETE":
                query_with_sig = (
                    f"{payload_string_to_sign}&signature={signature}"
                    if payload_string_to_sign
                    else f"signature={signature}"
                )
                url_for_request_with_params_in_query = f"{full_url}?{query_with_sig}"
            else:
                request_kwargs["data"] = (
                    f"{payload_string_to_sign}&signature={signature}"
                )
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif payload_string_to_sign:
            if method.upper() == "GET" or method.upper() == "DELETE":
                url_for_request_with_params_in_query = (
                    f"{full_url}?{payload_string_to_sign}"
                )
            else:
                request_kwargs["data"] = payload_string_to_sign
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        url_to_use_in_request = (
            url_for_request_with_params_in_query
            if method.upper() in ["GET", "DELETE"]
            else full_url
        )

        logger.debug(
            f"Sending {method} request to {url_to_use_in_request}. Loggable Params (used for sig if any): '{log_params_str_display}'"
        )
        if method.upper() not in ["GET", "DELETE"] and "data" in request_kwargs:
            logger.debug(
                f"  Actual HTTP Body (string with sig if any): '{request_kwargs.get('data')}'"
            )

        try:
            async with self._session.request(
                method.upper(), url_to_use_in_request, **request_kwargs
            ) as response:
                response_text = await response.text()
                try:
                    data = await response.json(content_type=None)
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to decode JSON response. Status: {response.status} for {url_to_use_in_request}. Response: {response_text[:500]}"
                    )
                    if response.status >= 400:
                        response.raise_for_status()
                    return {
                        "error": True,
                        "code": -1003,
                        "msg": f"Non-JSON response: {response_text[:200]}",
                    }

                if isinstance(data, dict) and "code" in data:
                    error_code_val_int: Optional[int] = None
                    try:
                        error_code_val_int = int(data["code"])
                    except (ValueError, TypeError):
                        pass

                    if error_code_val_int is not None and error_code_val_int < 0:
                        error_msg_binance = data.get("msg", "Unknown Binance API Error")
                        logger.error(
                            f"Binance API Error: Code={error_code_val_int}, Msg='{error_msg_binance}' for {method} {url_to_use_in_request} (Loggable Params: {log_params_str_display})"
                        )
                        return {
                            "error": True,
                            "code": error_code_val_int,
                            "msg": error_msg_binance,
                        }

                if response.status >= 400:
                    logger.error(
                        f"HTTP Error {response.status} for {method} {url_to_use_in_request}. Response data: {str(data)[:500]}"
                    )
                    response.raise_for_status()

                return data

        except aiohttp.ClientConnectorError as e:
            logger.warning(
                f"Connection Error for {method} {url_to_use_in_request}: {e}. Retrying..."
            )
            raise
        except asyncio.TimeoutError:
            logger.warning(
                f"Request Timeout for {method} {url_to_use_in_request}. Retrying..."
            )
            raise
        except aiohttp.ClientResponseError as e:
            logger.warning(
                f"HTTP ClientResponseError: Status={e.status}, Msg='{e.message}' for {method} {url_to_use_in_request}. Retrying..."
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during API request {method} {url_to_use_in_request}: {e}",
                exc_info=True,
            )
            return {
                "error": True,
                "code": -1002,
                "msg": f"Unexpected error in _request: {str(e)}",
            }

    async def get_ticker_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves the latest price for the specified symbol."""
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/fapi/v1/ticker/price" if is_futures else "/api/v3/ticker/price"

        params = {"symbol": symbol.upper()}
        log_prefix = f"[GetTickerPrice:{symbol}]"
        logger.debug(f"{log_prefix} Fetching price from {endpoint}...")

        try:
            response = await self._request("GET", endpoint, params=params, signed=False)

            if isinstance(response, dict) and not response.get("error"):
                if "price" in response:
                    logger.debug(f"{log_prefix} Success. Response: {response}")
                    return response
                else:
                    logger.error(
                        f"{log_prefix} Unexpected response format, 'price' key missing: {response}"
                    )
                    return None
            else:
                logger.error(
                    f"{log_prefix} API error or invalid response format: {response}"
                )
                return None
        except Exception as e:
            logger.error(f"{log_prefix} Exception occurred: {e}", exc_info=True)
            return None

    async def get_listen_key(self) -> Optional[str]:
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/fapi/v1/listenKey" if is_futures else "/api/v3/userDataStream"
        try:
            response = await self._request("POST", endpoint, signed=is_futures)
            if isinstance(response, dict) and not response.get("error"):
                key = response.get("listenKey")
                if key:
                    logger.info(
                        f"Successfully obtained listenKey (type: {'futures' if is_futures else 'spot'}): ...{key[-6:]}"
                    )
                    return key
                else:
                    logger.error(
                        f"Failed to get listenKey from response (type: {'futures' if is_futures else 'spot'}). Response: {response}"
                    )
            else:
                logger.error(
                    f"Failed to get listenKey (type: {'futures' if is_futures else 'spot'}). Response: {response}"
                )
            return None
        except Exception as e:
            logger.error(
                f"Error getting listenKey (type: {'futures' if is_futures else 'spot'}): {e}",
                exc_info=True,
            )
            return None

    async def keep_alive_listen_key(self, listen_key: str) -> bool:
        if not listen_key:
            return False
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/fapi/v1/listenKey" if is_futures else "/api/v3/userDataStream"
        try:
            response = await self._request(
                "PUT", endpoint, params={"listenKey": listen_key}, signed=is_futures
            )
            if isinstance(response, dict) and not response.get("error"):
                logger.info(
                    f"Successfully kept alive listenKey (type: {'futures' if is_futures else 'spot'}): ...{listen_key[-6:]}"
                )
                return True
            else:
                logger.error(
                    f"Failed to keep alive listenKey (type: {'futures' if is_futures else 'spot'}) ...{listen_key[-6:]}. Response: {response}"
                )
                if isinstance(response, dict) and response.get("code") == -1105:
                    if self._user_data_listen_key == listen_key:
                        logger.warning(
                            "Listen key became invalid, resetting local key."
                        )
                        self._user_data_listen_key = None
                return False
        except Exception as e:
            logger.error(
                f"Error keeping alive listenKey (type: {'futures' if is_futures else 'spot'}) ...{listen_key[-6:]}: {e}",
                exc_info=True,
            )
            return False

    async def close_listen_key(self, listen_key: str) -> bool:
        if not listen_key:
            return False
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/fapi/v1/listenKey" if is_futures else "/api/v3/userDataStream"
        try:
            response = await self._request(
                "DELETE", endpoint, params={"listenKey": listen_key}, signed=is_futures
            )
            if isinstance(response, dict) and not response.get("error"):
                logger.info(
                    f"Successfully closed listenKey (type: {'futures' if is_futures else 'spot'}): ...{listen_key[-6:]}"
                )
                return True
            else:
                logger.error(
                    f"Failed to close listenKey (type: {'futures' if is_futures else 'spot'}) ...{listen_key[-6:]}. Response: {response}"
                )
                return False
        except Exception as e:
            logger.error(
                f"Error closing listenKey (type: {'futures' if is_futures else 'spot'}) ...{listen_key[-6:]}: {e}",
                exc_info=True,
            )
            return False

    async def fetch_exchange_info(
        self, force_update: bool = False, specific_market_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        now = time.time()
        cache_duration = 3600

        market_type_to_fetch = (
            specific_market_type
            if specific_market_type is not None
            else self.market_type
        )
        log_prefix_fetch_info = f"[FetchExchangeInfo:{market_type_to_fetch}]"

        async with self._exchange_info_lock:
            if (
                not force_update
                and self._exchange_info_cache
                and self._exchange_info_cache.get("_market_type")
                == market_type_to_fetch
                and (now - self._last_exchange_info_update < cache_duration)
            ):
                logger.debug(f"{log_prefix_fetch_info} Returning cached data.")
                return self._exchange_info_cache

            logger.info(
                f"{log_prefix_fetch_info} Fetching/Updating exchange information from Binance API..."
            )

            current_base_url_for_request = self.base_url
            endpoint_for_request = ""

            if market_type_to_fetch == "spot":
                if self.market_type != "spot" and specific_market_type == "spot":
                    if config.ACTIVE_TRADING_ENVIRONMENT == "testnet":
                        current_base_url_for_request = (
                            config.BINANCE_SPOT_TESTNET_API_URL
                        )
                    else:
                        current_base_url_for_request = (
                            config.BINANCE_SPOT_MAINNET_API_URL
                        )
                endpoint_for_request = "/api/v3/exchangeInfo"

            elif market_type_to_fetch == "futures_usdtm":
                if (
                    self.market_type != "futures_usdtm"
                    and specific_market_type == "futures_usdtm"
                ):
                    if config.ACTIVE_TRADING_ENVIRONMENT == "testnet":
                        current_base_url_for_request = (
                            config.BINANCE_FUTURES_TESTNET_API_URL
                        )
                    else:
                        current_base_url_for_request = (
                            config.BINANCE_FUTURES_USDTM_MAINNET_API_URL
                        )
                endpoint_for_request = "/fapi/v1/exchangeInfo"
            else:
                logger.error(
                    f"{log_prefix_fetch_info} Unsupported market_type_to_fetch: {market_type_to_fetch}"
                )
                return None

            logger.debug(
                f"{log_prefix_fetch_info} Using BaseURL: {current_base_url_for_request}, Endpoint: {endpoint_for_request}"
            )

            try:
                original_base_url_of_executor = self.base_url
                request_needed_different_base_url = (
                    current_base_url_for_request != original_base_url_of_executor
                )

                if request_needed_different_base_url:
                    logger.warning(
                        f"{log_prefix_fetch_info} Temporarily changing executor's base_url from {original_base_url_of_executor} to {current_base_url_for_request} for this request."
                    )
                    self.base_url = current_base_url_for_request

                response = await self._request(
                    "GET", endpoint_for_request, signed=False
                )

                if request_needed_different_base_url:
                    self.base_url = original_base_url_of_executor
                    logger.debug(
                        f"{log_prefix_fetch_info} Restored executor's base_url to {self.base_url}."
                    )

                if (
                    isinstance(response, dict)
                    and "symbols" in response
                    and not response.get("error")
                ):
                    response["_market_type"] = market_type_to_fetch
                    self._exchange_info_cache = response
                    self._last_exchange_info_update = now
                    logger.info(
                        f"{log_prefix_fetch_info} Exchange information for {market_type_to_fetch} updated. Found {len(response.get('symbols', []))} symbols."
                    )
                    return self._exchange_info_cache
                else:
                    logger.error(
                        f"{log_prefix_fetch_info} Unexpected response format or error: {str(response)[:500]}"
                    )
                    if (
                        self._exchange_info_cache
                        and self._exchange_info_cache.get("_market_type")
                        == market_type_to_fetch
                    ):
                        return self._exchange_info_cache
                    return None
            except Exception as e:
                logger.error(
                    f"{log_prefix_fetch_info} Error fetching exchange information: {e}",
                    exc_info=True,
                )
                if request_needed_different_base_url:
                    self.base_url = original_base_url_of_executor
                if (
                    self._exchange_info_cache
                    and self._exchange_info_cache.get("_market_type")
                    == market_type_to_fetch
                ):
                    return self._exchange_info_cache
                return None

    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        exchange_info = await self.fetch_exchange_info()
        if not exchange_info or not exchange_info.get("symbols"):
            return None
        if not hasattr(self, "_symbol_info_dict") or not self._symbol_info_dict:
            self._symbol_info_dict = {
                s["symbol"]: s for s in exchange_info["symbols"] if "symbol" in s
            }
        symbol_data = self._symbol_info_dict.get(symbol.upper())
        if not symbol_data:
            logger.warning(
                f"Symbol information not found for {symbol} in exchange info."
            )
        return symbol_data

    async def get_filter(
        self, symbol: str, filter_type: str
    ) -> Optional[Dict[str, Any]]:
        symbol_info = await self.get_symbol_info(symbol)
        if not symbol_info or not isinstance(symbol_info.get("filters"), list):
            return None
        return next(
            (
                f
                for f in symbol_info["filters"]
                if isinstance(f, dict) and f.get("filterType") == filter_type
            ),
            None,
        )

    async def get_tick_size(self, symbol: str) -> Optional[float]:
        price_filter = await self.get_filter(symbol, "PRICE_FILTER")
        if price_filter and "tickSize" in price_filter:
            try:
                return float(price_filter["tickSize"])
            except (ValueError, TypeError):
                logger.error(
                    f"Invalid tickSize format for {symbol}: {price_filter['tickSize']}"
                )
        return None

    async def get_lot_size_params(self, symbol: str) -> Optional[Dict[str, float]]:
        lot_filter = await self.get_filter(symbol, "LOT_SIZE")
        if lot_filter:
            try:
                return {
                    "minQty": float(lot_filter.get("minQty", 0)),
                    "maxQty": float(lot_filter.get("maxQty", float("inf"))),
                    "stepSize": float(lot_filter.get("stepSize", 0)),
                }
            except (ValueError, TypeError):
                logger.error(
                    f"Invalid LOT_SIZE filter format for {symbol}: {lot_filter}"
                )
        return None

    async def get_min_notional(self, symbol: str) -> Optional[float]:
        notional_filter = await self.get_filter(
            symbol, "NOTIONAL"
        ) or await self.get_filter(symbol, "MIN_NOTIONAL")
        if notional_filter:
            min_notional_key = (
                "minNotional"
                if "minNotional" in notional_filter
                else ("notional" if "notional" in notional_filter else None)
            )
            if min_notional_key and min_notional_key in notional_filter:
                try:
                    return float(notional_filter[min_notional_key])
                except (ValueError, TypeError):
                    logger.error(
                        f"Invalid minNotional format for {symbol}: {notional_filter[min_notional_key]}"
                    )
        return None

    async def get_server_time(self) -> Optional[Dict[str, Any]]:
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/fapi/v1/time" if is_futures else "/api/v3/time"
        log_prefix = f"[GetServerTime:{self.market_type}]"
        logger.debug(f"{log_prefix} Fetching server time from {endpoint}...")

        try:
            response = await self._request("GET", endpoint, signed=False)

            if isinstance(response, dict) and "serverTime" in response:
                logger.debug(
                    f"{log_prefix} Success. Server time: {response['serverTime']}"
                )
                return response
            else:
                logger.error(
                    f"{log_prefix} API error or invalid response format: {response}"
                )
                return response
        except Exception as e:
            logger.error(f"{log_prefix} Exception occurred: {e}", exc_info=True)
            return {"error": True, "code": -999, "msg": str(e)}

    # Methods for working with orders
    # ORDER TYPES REQUIRING ALGO ORDER API
    ALGO_ORDER_TYPES = {
        "STOP_MARKET",
        "TAKE_PROFIT_MARKET",
        "STOP",
        "TAKE_PROFIT",
        "TRAILING_STOP_MARKET",
    }

    async def place_order(
        self, symbol: str, side: str, order_type: str, **kwargs
    ) -> Dict[str, Any]:
        is_futures = self.market_type == "futures_usdtm"
        actual_order_type_for_api = order_type.upper()

        # ENDPOINT DEFINITION: Algo Order API for conditional orders on futures
        use_algo_api = is_futures and actual_order_type_for_api in self.ALGO_ORDER_TYPES

        if use_algo_api:
            endpoint = "/fapi/v1/algoOrder"
            logger.info(
                f"[ExecutorPlaceOrder] Using Algo Order API for {actual_order_type_for_api}"
            )
        else:
            endpoint = "/api/v3/order" if not is_futures else "/fapi/v1/order"

        params = {"symbol": symbol.upper(), "side": side.upper()}
        params["type"] = actual_order_type_for_api

        # For Algo Order API, algoType=CONDITIONAL is required
        if use_algo_api:
            params["algoType"] = "CONDITIONAL"

        # Rounding and formatting parameters

        lot_size_params = await self.get_lot_size_params(symbol)
        tick_size = await self.get_tick_size(symbol)

        quantity = kwargs.get("quantity")
        if quantity is not None:
            if lot_size_params and lot_size_params.get("stepSize"):
                rounded_qty = self._round_quantity(
                    float(quantity), lot_size_params["stepSize"]
                )
                if rounded_qty is None:
                    return {
                        "error": True,
                        "code": -1111,
                        "msg": f"Failed to round quantity {quantity}.",
                    }
                # Format the string to remove insignificant zeros that might cause an API error
                params["quantity"] = (
                    f"{rounded_qty:.8f}".rstrip("0").rstrip(".")
                    if "." in f"{rounded_qty:.8f}"
                    else str(rounded_qty)
                )
            else:
                params["quantity"] = str(quantity)

        price = kwargs.get("price")
        if price is not None:
            if tick_size:
                # Use safe rounding down. Logic can be added for more precise execution
                # based on `side`, but for universality this is more reliable.
                rounded_price = self._round_price(float(price), tick_size, ROUND_DOWN)
                if rounded_price is None:
                    return {
                        "error": True,
                        "code": -1111,
                        "msg": f"Failed to round price {price}.",
                    }
                params["price"] = (
                    f"{rounded_price:.8f}".rstrip("0").rstrip(".")
                    if "." in f"{rounded_price:.8f}"
                    else str(rounded_price)
                )
            else:
                params["price"] = str(price)

        stopPrice = kwargs.get("stopPrice")
        if stopPrice is not None:
            if tick_size:
                # For stopPrice, we also use safe rounding
                rounded_stop_price = self._round_price(
                    float(stopPrice), tick_size, ROUND_DOWN
                )
                if rounded_stop_price is None:
                    return {
                        "error": True,
                        "code": -1111,
                        "msg": f"Failed to round stopPrice {stopPrice}.",
                    }
                formatted_stop_price = (
                    f"{rounded_stop_price:.8f}".rstrip("0").rstrip(".")
                    if "." in f"{rounded_stop_price:.8f}"
                    else str(rounded_stop_price)
                )
            else:
                formatted_stop_price = str(stopPrice)

            # For Algo Order API, triggerPrice is used instead of stopPrice
            if use_algo_api:
                params["triggerPrice"] = formatted_stop_price
            else:
                params["stopPrice"] = formatted_stop_price

        quoteOrderQty = kwargs.get("quoteOrderQty")
        if (
            quoteOrderQty is not None
            and not is_futures
            and actual_order_type_for_api == "MARKET"
        ):
            params["quoteOrderQty"] = str(quoteOrderQty)

        timeInForce = kwargs.get("timeInForce")
        if timeInForce is not None:
            params["timeInForce"] = timeInForce.upper()

        newClientOrderId = kwargs.get("newClientOrderId")
        if newClientOrderId is not None:
            params["newClientOrderId"] = newClientOrderId

        reduceOnly = kwargs.get("reduceOnly")
        if reduceOnly is not None and is_futures:
            params["reduceOnly"] = str(reduceOnly).lower()

        # Additional parameters for Algo Order API
        if use_algo_api:
            # workingType: 'MARK_PRICE' or 'CONTRACT_PRICE' (default is CONTRACT_PRICE)
            workingType = kwargs.get("workingType")
            if workingType is not None:
                params["workingType"] = workingType.upper()

            # priceProtect for STOP_MARKET and TAKE_PROFIT_MARKET
            priceProtect = kwargs.get("priceProtect")
            if priceProtect is not None:
                params["priceProtect"] = str(priceProtect).upper()

            # closePosition to close the entire position
            closePosition = kwargs.get("closePosition")
            if closePosition is not None:
                params["closePosition"] = str(closePosition).lower()

            # activationPrice and callbackRate for TRAILING_STOP_MARKET
            activationPrice = kwargs.get("activationPrice")
            if activationPrice is not None:
                params["activationPrice"] = str(activationPrice)

            callbackRate = kwargs.get("callbackRate")
            if callbackRate is not None:
                params["callbackRate"] = str(callbackRate)

        log_params_short = {
            k: v
            for k, v in params.items()
            if k not in ["newClientOrderId", "timestamp", "recvWindow", "signature"]
        }
        logger.info(
            f"Placing order ({self.market_type}): {symbol} {side} {actual_order_type_for_api} Params: {log_params_short}"
        )

        logger.info(
            f"[ExecutorPlaceOrder] FINAL PARAMS for API ({self.market_type}): Symbol={symbol}, Side={side}, TypeForAPI={actual_order_type_for_api}, Endpoint={endpoint}, FullParamsDict={params}"
        )

        try:
            result = await self._request("POST", endpoint, params=params, signed=True)
            log_result = result.copy() if isinstance(result, dict) else result
            if (
                isinstance(log_result, dict)
                and "fills" in log_result
                and isinstance(log_result["fills"], list)
            ):
                log_result["fills"] = f"[{len(log_result['fills'])} fills]"
            logger.info(f"Place order response ({self.market_type}): {log_result}")
            return result
        except Exception as e:
            logger.error(
                f"Error placing order ({self.market_type}: {symbol}, {side}, {actual_order_type_for_api}, {kwargs}): {e}",
                exc_info=True,
            )
            return {"error": True, "code": -999, "msg": str(e)}

    async def cancel_order(
        self,
        symbol: str,
        orderId: Optional[int] = None,
        origClientOrderId: Optional[str] = None,
        is_algo_order: bool = False,
    ) -> Dict[str, Any]:
        """
        Cancels an order on the exchange.

        Args:
            symbol: Trading pair symbol
            orderId: Order ID (for regular orders)
            origClientOrderId: Client order ID
            is_algo_order: If True, uses Algo Order API for cancellation
        """
        # Determining the endpoint
        if self.market_type == "futures_usdtm":
            if is_algo_order:
                endpoint = "/fapi/v1/algoOrder"  # Algo Order API
            else:
                endpoint = "/fapi/v1/order"  # Regular endpoint
        else:
            endpoint = "/api/v3/order"  # Spot API

        if not orderId and not origClientOrderId:
            return {
                "error": True,
                "code": -1,
                "msg": "Missing order identifier (orderId or origClientOrderId required).",
            }

        params = {"symbol": symbol.upper()}
        id_str = ""

        # For Algo Order API, algoId is used instead of orderId
        if is_algo_order and orderId:
            params["algoId"] = orderId
            id_str = f"AlgoID {orderId}"
        else:
            if orderId:
                params["orderId"] = orderId
                id_str = f"ID {orderId}"
            if origClientOrderId:
                params["origClientOrderId"] = origClientOrderId
                id_str = f"ClientID {origClientOrderId}"

        logger.info(
            f"Cancelling order ({self.market_type}): {symbol} {id_str} using endpoint {endpoint}"
        )
        try:
            result = await self._request("DELETE", endpoint, params=params, signed=True)
            logger.info(f"Cancel order response ({self.market_type}): {result}")

            # Check if error -4120 was returned (Algo Order API required)
            if (
                isinstance(result, dict)
                and result.get("error")
                and result.get("code") == -4120
                and not is_algo_order
            ):
                logger.warning(
                    f"Order ({symbol}, {id_str}) requires Algo Order API for cancellation. Retrying with Algo endpoint..."
                )
                return await self.cancel_order(
                    symbol=symbol,
                    orderId=orderId,
                    origClientOrderId=origClientOrderId,
                    is_algo_order=True,
                )

            return result
        except aiohttp.client_exceptions.ClientResponseError as e:
            error_payload = {}
            try:
                if e.message:
                    error_payload = (
                        json.loads(e.message)
                        if isinstance(e.message, str) and e.message.startswith("{")
                        else {}
                    )
            except json.JSONDecodeError:
                pass

            api_code = (
                error_payload.get("code") if isinstance(error_payload, dict) else None
            )

            # If error -4120 and we haven't tried the Algo API yet, let's try it
            if api_code == -4120 and not is_algo_order:
                logger.warning(
                    f"Order ({symbol}, {id_str}) requires Algo Order API for cancellation (from exception). Retrying with Algo endpoint..."
                )
                return await self.cancel_order(
                    symbol=symbol,
                    orderId=orderId,
                    origClientOrderId=origClientOrderId,
                    is_algo_order=True,
                )

            non_critical_cancel_errors = [-2011, -2013]

            if e.status == 404 or (
                api_code is not None and api_code in non_critical_cancel_errors
            ):
                logger.warning(
                    f"Order ({symbol}, {id_str}) likely already closed/cancelled. API Status: {e.status}, API Code: {api_code}, Msg: {error_payload.get('msg', e.message)}. Treating as non-critical for cancellation."
                )
                return {
                    "symbol": symbol,
                    "orderId": orderId,
                    "origClientOrderId": origClientOrderId,
                    "status": "ALREADY_CANCELLED_OR_FILLED",
                    "msg": f"Order not found (API Status: {e.status}, Code: {api_code})",
                }
            else:
                logger.error(
                    f"Error cancelling order ({self.market_type}, {symbol}, {id_str}): Status={e.status}, API Code={api_code}, Msg='{error_payload.get('msg', e.message)}'",
                    exc_info=not bool(api_code),
                )
                return {
                    "error": True,
                    "code": api_code or e.status,
                    "msg": error_payload.get("msg", str(e)),
                }

        except Exception as e:
            logger.error(
                f"Unexpected error cancelling order ({self.market_type}, {symbol}, {id_str}): {e}",
                exc_info=True,
            )
            return {"error": True, "code": -999, "msg": str(e)}

    async def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Gets a list of open orders."""
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/api/v3/openOrders"  # Spot
        if is_futures:
            endpoint = "/fapi/v1/openOrders"  # USDT-M Futures
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        logger.debug(
            f"Getting open orders for {self.market_type}, symbol '{symbol or 'ALL'}'..."
        )
        try:
            response = await self._request(
                "GET", endpoint, params=params, signed=True
            )  # Always signed
            if isinstance(response, list):
                logger.debug(
                    f"Found {len(response)} open orders for {self.market_type}, '{symbol or 'ALL'}'."
                )
                return response
            elif isinstance(response, dict) and response.get("error"):
                logger.error(
                    f"API error getting open orders ({self.market_type}): {response}"
                )
                return []
            else:
                logger.error(
                    f"Unexpected response format for get_open_orders ({self.market_type}): {response}"
                )
                return []
        except Exception as e:
            logger.error(
                f"Error getting open orders for {self.market_type}, symbol '{symbol}': {e}",
                exc_info=True,
            )
            return []

    async def get_open_algo_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves open Algo Orders (TRAILING_STOP_MARKET, STOP_MARKET, etc.)
        via the /fapi/v1/algoOrders endpoint.
        """
        if self.market_type != "futures_usdtm":
            logger.warning(
                f"[GetOpenAlgoOrders:{self.market_type}] Only supported for futures_usdtm."
            )
            return []

        endpoint = "/fapi/v1/algoOrders"
        params = {}
        if symbol:
            params["symbol"] = symbol

        log_prefix = f"[GetOpenAlgoOrders:{self.market_type}]"
        logger.debug(f"{log_prefix} Fetching algo orders for symbol={symbol}...")

        try:
            response = await self._request("GET", endpoint, params=params, signed=True)

            if isinstance(response, dict) and "orders" in response:
                orders = response.get("orders", [])
                logger.info(f"{log_prefix} Found {len(orders)} open algo orders.")
                return orders
            elif isinstance(response, list):
                logger.info(f"{log_prefix} Found {len(response)} open algo orders.")
                return response
            elif isinstance(response, dict) and response.get("error"):
                logger.error(f"{log_prefix} API error: {response}")
                return []
            else:
                logger.warning(f"{log_prefix} Unexpected response format: {response}")
                return []
        except Exception as e:
            logger.error(f"{log_prefix} Error getting algo orders: {e}", exc_info=True)
            return []

    async def get_account_balance(self) -> Optional[Dict[str, Dict[str, str]]]:
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/api/v3/account"  # Spot
        if is_futures:
            endpoint = "/fapi/v2/balance"  # USDT-M Futures

        logger.debug(
            f"Getting account balance for {self.market_type} from {endpoint}..."
        )
        try:
            response = await self._request("GET", endpoint, signed=True)

            if response is None:
                logger.error(
                    f"Failed to get account balance for {self.market_type}, _request returned None."
                )
                return None

            if is_futures:  # Parsing response for futures (/fapi/v2/balance)
                if isinstance(response, list):
                    balances = {}
                    for item in response:
                        try:
                            free_balance = Decimal(item.get("availableBalance", "0"))
                            total_balance = Decimal(item.get("balance", "0"))

                            if total_balance <= Decimal("0"):
                                continue

                            locked_balance = total_balance - free_balance

                            balances[item["asset"]] = {
                                "free": str(free_balance),
                                "locked": str(locked_balance),
                                "unrealized_pnl": item.get("unrealizedProfit", "0"),
                            }
                        except (InvalidOperation, TypeError):
                            logger.warning(
                                f"Could not parse balance for asset {item.get('asset')} in futures balance response."
                            )
                            continue

                    logger.debug(
                        f"Futures account balance retrieved. Found {len(balances)} non-zero assets."
                    )
                    return balances
                elif isinstance(response, dict) and response.get("error"):
                    logger.error(
                        f"API error getting futures account balance: {response}"
                    )
                    return {}
                else:
                    logger.error(
                        f"Unexpected response format for futures get_account_balance: {response}"
                    )
                    return {}
            else:  # Parsing for spot (/api/v3/account)
                if (
                    isinstance(response, dict)
                    and "balances" in response
                    and isinstance(response["balances"], list)
                ):
                    balances = {
                        item["asset"]: {"free": item["free"], "locked": item["locked"]}
                        for item in response["balances"]
                        if float(item.get("free", 0)) > 1e-9
                        or float(item.get("locked", 0)) > 1e-9
                    }
                    logger.debug(
                        f"Spot account balance retrieved. Found {len(balances)} assets."
                    )
                    return balances
                elif isinstance(response, dict) and response.get("error"):
                    logger.error(f"API error getting spot account balance: {response}")
                    return {}
                else:
                    logger.error(
                        f"Unexpected response format for spot get_account_balance: {response}"
                    )
                    return {}
        except Exception as e:
            logger.error(
                f"Error getting account balance for {self.market_type}: {e}",
                exc_info=True,
            )
            return None

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        log_prefix = f"[GetOpenPositions:{self.market_type}]"

        if self.market_type != "futures_usdtm":
            logger.warning(
                f"{log_prefix} Method is only applicable for 'futures_usdtm' market type. Returning empty list."
            )
            return []

        endpoint = "/fapi/v2/positionRisk"
        logger.debug(f"{log_prefix} Fetching open positions from {endpoint}...")

        try:
            response = await self._request("GET", endpoint, signed=True)

            if isinstance(response, list):
                open_positions = [
                    pos for pos in response if float(pos.get("positionAmt", "0")) != 0
                ]
                logger.info(
                    f"{log_prefix} Found {len(open_positions)} open positions out of {len(response)} total symbols."
                )
                return open_positions

            elif isinstance(response, dict) and response.get("error"):
                logger.error(
                    f"{log_prefix} API error while fetching positions: {response}"
                )
                return []

            else:
                logger.error(f"{log_prefix} Unexpected response format: {response}")
                return []

        except Exception as e:
            logger.error(f"{log_prefix} Exception occurred: {e}", exc_info=True)
            return []

    async def _user_data_keepalive_loop(self, listen_key: str):
        log_prefix = f"[UserDataKeepalive:{listen_key[-6:]}]"
        logger.info(f"{log_prefix} Keep-alive loop started.")
        while self._user_data_running and self._user_data_listen_key == listen_key:
            next_ping_time = time.time() + config.USER_DATA_PING_INTERVAL
            while (
                time.time() < next_ping_time
                and self._user_data_running
                and self._user_data_listen_key == listen_key
            ):
                await asyncio.sleep(1)

            if not self._user_data_running or self._user_data_listen_key != listen_key:
                break

            if not self._user_data_ws or self._user_data_ws.state != State.OPEN:
                logger.warning(
                    f"{log_prefix} User data WebSocket is not open or not available. Cannot keep listen key alive. Breaking keep-alive loop."
                )
                break

            logger.info(f"{log_prefix} Attempting to keep-alive listenKey...")
            success = await self.keep_alive_listen_key(listen_key)
            if not success:
                logger.warning(
                    f"{log_prefix} Keep-alive failed. WS might disconnect or key expired."
                )
                break
            else:
                logger.info(f"{log_prefix} Keep-alive successful.")

        logger.info(f"{log_prefix} Keep-alive loop finished.")
        if (
            self._user_data_keepalive_task
            and self._user_data_keepalive_task is asyncio.current_task()
        ):
            self._user_data_keepalive_task = None

    async def _user_data_ws_listener(
        self, listen_key: str, callback: Callable[[Dict[str, Any]], Coroutine]
    ):
        if not websockets:
            logger.critical("Websockets library not loaded!")
            return
        ws_url = f"{self.ws_base_url}/{listen_key}"
        log_prefix = f"[UserDataListener:{listen_key[-6:]}]"
        logger.info(f"{log_prefix} Starting listener loop for URL: {ws_url}")

        websocket = None

        while self._user_data_running and self._user_data_listen_key == listen_key:
            try:
                websocket = await websockets.connect(
                    ws_url, ping_interval=20, ping_timeout=10, open_timeout=15
                )

                self._user_data_ws = websocket
                self._ws_reconnect_attempts = 0
                logger.info(f"{log_prefix} WebSocket CONNECTED.")
                if (
                    self._user_data_keepalive_task is None
                    or self._user_data_keepalive_task.done()
                ):
                    self._user_data_keepalive_task = asyncio.create_task(
                        self._user_data_keepalive_loop(listen_key),
                        name=f"UserDataKeepalive_{listen_key[-6:]}",
                    )
                    logger.info(f"{log_prefix} Keep-alive task started/restarted.")

                async for message in websocket:
                    if (
                        not self._user_data_running
                        or self._user_data_listen_key != listen_key
                    ):
                        logger.info(
                            f"{log_prefix} Stopping message processing loop (running={self._user_data_running}, key_match={self._user_data_listen_key == listen_key})."
                        )
                        break
                    try:
                        data = json.loads(message)
                        logger.debug(
                            f"{log_prefix} Received data: {data.get('e', 'NO_EVENT')}"
                        )
                        asyncio.create_task(callback(data))
                    except json.JSONDecodeError:
                        logger.warning(
                            f"{log_prefix} Received non-JSON message: {message[:200]}"
                        )
                    except Exception as e_callback:
                        logger.error(
                            f"{log_prefix} Error in user data callback task creation or execution: {e_callback}",
                            exc_info=True,
                        )
            except ConnectionClosedOK:
                logger.info(f"{log_prefix} WebSocket connection closed normally.")
                break
            except (
                ConnectionClosedError,
                ConnectionClosed,
                asyncio.TimeoutError,
                OSError,
                InvalidStatus,
                websockets.exceptions.ConnectionClosedError,
            ) as e:
                logger.warning(
                    f"{log_prefix} WS connection error/closed unexpectedly: {type(e).__name__} - {e}"
                )
                self._user_data_ws = None
                if self._user_data_running:
                    self._ws_reconnect_attempts += 1
                    delay = min(
                        config.WS_RECONNECT_DELAY
                        * (1.5 ** min(self._ws_reconnect_attempts - 1, 5)),
                        60,
                    )
                    logger.info(
                        f"{log_prefix} Attempting to reconnect user data WS (attempt {self._ws_reconnect_attempts}) in {delay:.1f} seconds..."
                    )
                    await asyncio.sleep(delay)

                    logger.info(
                        f"{log_prefix} Refreshing listen key before reconnection attempt..."
                    )
                    old_key_to_close = self._user_data_listen_key
                    if old_key_to_close:
                        await self.close_listen_key(old_key_to_close)

                    new_key = await self.get_listen_key()
                    if new_key:
                        self._user_data_listen_key = new_key
                        listen_key = new_key
                        logger.info(
                            f"{log_prefix} Using new listenKey for reconnect: ...{listen_key[-6:]}"
                        )
                        ws_url = f"{self.ws_base_url}/{listen_key}"
                        if (
                            self._user_data_keepalive_task
                            and not self._user_data_keepalive_task.done()
                        ):
                            logger.info(
                                f"{log_prefix} Canceling previous keep-alive task."
                            )
                            self._user_data_keepalive_task.cancel()
                            self._user_data_keepalive_task = None
                    else:
                        logger.error(
                            f"{log_prefix} Failed to refresh listen key after connection error. Stopping user data stream."
                        )
                        self._user_data_running = False
                        break
                    continue
                else:
                    logger.info(
                        f"{log_prefix} WS connection error, but stream is stopping."
                    )
                    break
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Listener task cancelled.")
                break
            except Exception as e:
                logger.error(
                    f"{log_prefix} Unexpected error in listener loop: {e}",
                    exc_info=True,
                )
                if self._user_data_running:
                    await asyncio.sleep(config.WS_RECONNECT_DELAY)
                else:
                    break
            finally:
                logger.debug(
                    f"{log_prefix} Listener loop finally block. WebSocket state: {websocket.state if websocket else 'None'}"
                )
                if websocket and websocket.state != State.CLOSED:
                    try:
                        await asyncio.wait_for(
                            websocket.close(
                                code=1000, reason="Listener loop finishing"
                            ),
                            timeout=2.0,
                        )
                        logger.debug(
                            f"{log_prefix} WebSocket closed in listener finally block."
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"{log_prefix} Timeout closing websocket in listener finally block."
                        )
                    except Exception as e_close_final:
                        logger.error(
                            f"{log_prefix} Error during final websocket close in listener: {e_close_final}"
                        )

                if self._user_data_ws is websocket:
                    self._user_data_ws = None
                    logger.debug(
                        f"{log_prefix} Cleared self._user_data_ws as it matched the finishing websocket."
                    )

        logger.info(f"{log_prefix} Listener loop finished.")
        if self._user_data_keepalive_task and not self._user_data_keepalive_task.done():
            logger.info(
                f"{log_prefix} Canceling keep-alive task as listener loop finished."
            )
            self._user_data_keepalive_task.cancel()
            self._user_data_keepalive_task = None

    async def start_user_data_stream(
        self, callback: Callable[[Dict[str, Any]], Coroutine]
    ):
        if not websockets:
            logger.error(
                "Cannot start userData stream: websockets library not available."
            )
            return
        if not callable(callback):
            logger.error("User data stream callback is not callable.")
            return

        async with self._ws_connect_lock:
            if self._user_data_running:
                logger.warning("User data stream is already running.")
                return

            self._user_data_running = True
            self._user_data_callback = callback
            self._ws_reconnect_attempts = 0
            logger.info("Attempting to start user data stream...")

            self._user_data_listen_key = await self.get_listen_key()
            if not self._user_data_listen_key:
                logger.error(
                    "Failed to get initial listenKey. Cannot start user data stream."
                )
                self._user_data_running = False
                return

            self._user_data_listener_task = asyncio.create_task(
                self._user_data_ws_listener(self._user_data_listen_key, callback),
                name=f"UserDataListener_{self._user_data_listen_key[-6:]}",
            )
            logger.info(
                f"User data listener task created (Key: ...{self._user_data_listen_key[-6:]})."
            )

    async def stop_user_data_stream(self):
        log_prefix = "[UserDataStop]"
        key_to_close = None

        async with self._ws_connect_lock:
            if not self._user_data_running:
                logger.info(f"{log_prefix} User data stream is not running.")
                return

            logger.info(f"{log_prefix} Attempting to stop user data stream...")
            self._user_data_running = False

            tasks_to_cancel: List[Optional[asyncio.Task]] = []
            if (
                self._user_data_keepalive_task
                and not self._user_data_keepalive_task.done()
            ):
                tasks_to_cancel.append(self._user_data_keepalive_task)
            if (
                self._user_data_listener_task
                and not self._user_data_listener_task.done()
            ):
                tasks_to_cancel.append(self._user_data_listener_task)

            ws_to_close = self._user_data_ws
            key_to_close = self._user_data_listen_key

            self._user_data_keepalive_task = None
            self._user_data_listener_task = None
            self._user_data_ws = None
            self._user_data_listen_key = None
            self._user_data_callback = None
            logger.debug(f"{log_prefix} State cleared inside lock.")

        if tasks_to_cancel:
            logger.info(
                f"{log_prefix} Canceling {len(tasks_to_cancel)} background tasks..."
            )
            for task in tasks_to_cancel:
                if task:
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except asyncio.CancelledError:
                        logger.debug(
                            f"{log_prefix} Task {task.get_name()} cancelled successfully."
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"{log_prefix} Timeout waiting for task {task.get_name()} to cancel."
                        )
                    except Exception as e:
                        logger.error(
                            f"{log_prefix} Error cancelling task {task.get_name()}: {e}"
                        )
            logger.info(f"{log_prefix} Background tasks cancelled.")

        if ws_to_close and ws_to_close.state == State.OPEN:
            logger.info(f"{log_prefix} Closing WebSocket connection...")
            try:
                await ws_to_close.close(code=1000, reason="Client stopping")
                logger.info(f"{log_prefix} WebSocket connection closed gracefully.")
            except Exception as e:
                logger.error(f"{log_prefix} Error closing user data WebSocket: {e}")
        else:
            logger.debug(
                f"{log_prefix} WebSocket connection was not open or ws_to_close is None. No explicit close needed."
            )

        if key_to_close:
            logger.info(
                f"{log_prefix} Closing listenKey ...{key_to_close[-6:]} on server..."
            )
            await self.close_listen_key(key_to_close)

        logger.info(f"{log_prefix} User data stream stopped.")

    async def fetch_open_interest_history(
        self, symbol: str, period: str = "5m", limit: int = 500
    ) -> Optional[pd.DataFrame]:
        log_prefix = f"[FetchOIHistory:{symbol}]"

        if self.market_type != "futures_usdtm":
            logger.warning(
                f"{log_prefix} Open Interest history is only available for futures market."
            )
            return None

        data_base_url = "https://fapi.binance.com"
        if config.ACTIVE_TRADING_ENVIRONMENT == "testnet":
            data_base_url = "https://testnet.binancefuture.com"

        endpoint = "/futures/data/openInterestHist"
        full_url = f"{data_base_url}{endpoint}"

        params = {"symbol": symbol.upper(), "period": period, "limit": min(limit, 500)}

        logger.info(
            f"{log_prefix} Fetching OI history from {full_url} with params {params}"
        )

        try:
            if not self._session or self._session.closed:
                logger.error(f"{log_prefix} Aiohttp session is not available.")
                return None

            async with self._session.get(full_url, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                if not isinstance(data, list):
                    logger.error(
                        f"{log_prefix} Unexpected response format, expected a list. Got: {type(data)}"
                    )
                    return None

                if not data:
                    logger.warning(f"{log_prefix} Received empty list for OI history.")
                    return pd.DataFrame()

                df = pd.DataFrame(data)
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.set_index("timestamp")
                df["sumOpenInterest"] = pd.to_numeric(df["sumOpenInterest"])

                logger.info(
                    f"{log_prefix} Successfully fetched and parsed {len(df)} OI records."
                )
                return df

        except aiohttp.ClientResponseError as e:
            logger.error(
                f"{log_prefix} HTTP Error fetching OI history: {e.status} - {e.message}"
            )
            return None
        except Exception as e:
            logger.error(
                f"{log_prefix} Unexpected error fetching OI history: {e}", exc_info=True
            )
            return None

    async def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancels all open orders for the specified symbol."""
        is_futures = self.market_type == "futures_usdtm"
        endpoint = "/api/v3/openOrders" if not is_futures else "/fapi/v1/allOpenOrders"

        params = {"symbol": symbol.upper()}
        log_prefix = f"[CancelAllOrders:{symbol}]"
        logger.info(f"{log_prefix} Cancelling all open orders...")

        try:
            result = await self._request("DELETE", endpoint, params=params, signed=True)
            logger.info(f"{log_prefix} Response: {result}")
            return result
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)
            return {"error": True, "code": -999, "msg": str(e)}


# Usage example (no changes)
async def example_usage_testnet():
    logger.info("--- Starting Testnet Example ---")
    api_key = config.BINANCE_API_KEY
    api_secret = config.BINANCE_API_SECRET

    if not config.USE_TESTNET:
        logger.error(
            "USE_TESTNET is False in config.py. Example requires Testnet to be enabled."
        )
        return
    if "YOUR_API_KEY_HERE" in api_key or "YOUR_API_SECRET_HERE" in api_secret:
        logger.error(
            "Testnet API keys not configured. Please set environment variables BOT_BINANCE_API_KEY and BOT_BINANCE_API_SECRET."
        )
        return
    if not websockets:
        logger.error(
            "Websockets library not installed. Cannot run userData stream example."
        )
        return

    executor = None  # Initializing None
    session = None
    try:
        # Creating a session ONLY for this example
        session = aiohttp.ClientSession()
        executor = BinanceExecutor(api_key, api_secret, session)  # Pass session here

        async def handle_user_data(data: Dict[str, Any]):
            event_type = data.get("e")
            if (
                event_type == "outboundAccountPosition"
            ):  # Balances (received at start and on changes)
                balances = data.get("B", [])
                usdt_balance = next(
                    (item for item in balances if item.get("a") == "USDT"), None
                )
                if usdt_balance:
                    logger.info(
                        f"=== Account Balance Update (USDT): Free={usdt_balance.get('f')}, Locked={usdt_balance.get('l')} ==="
                    )
            elif (
                event_type == "balanceUpdate"
            ):  # Balance change without an order (deposit, commission, etc.)
                logger.info(
                    f"=== Balance Update: Asset={data.get('a')}, Delta={data.get('d')}, Time={data.get('T')} ==="
                )
            elif event_type == "executionReport":  # Order report
                order_status = data.get("X")  # Order status
                symbol = data.get("s")
                order_id = data.get("i")
                client_order_id = data.get("c")
                side = data.get("S")
                order_type = data.get("o")
                price = data.get("p")
                qty = data.get("q")  # Total quantity in the order
                filled_qty = data.get("z")  # Executed quantity
                last_filled_qty = data.get("l")  # Quantity in the last trade
                last_filled_price = data.get("L")  # Last trade price
                commission = data.get("n")  # Commission
                commission_asset = data.get("N")  # Commission asset
                logger.info(
                    f"=== Order Update ({symbol}): ID={order_id}, CliID={client_order_id}, Side={side}, Type={order_type}, Price={price}, Qty={qty}, FilledQty={filled_qty}, LastFillQty={last_filled_qty}@{last_filled_price}, Status={order_status}, Comm={commission}{commission_asset} ==="
                )
            else:
                logger.debug(f"Other user data event: {event_type}")

        await executor.start_user_data_stream(handle_user_data)
        logger.info("User data stream started. Waiting for updates...")

        # Test requests
        logger.info("Getting account balance...")
        balance = await executor.get_account_balance()
        logger.info(f"Testnet Balances (Non-zero): {balance}")

        logger.info("Getting open orders (if any)...")
        open_orders = await executor.get_open_orders()
        logger.info(f"Testnet Open Orders: {open_orders}")

        # Test order (MARKET BUY for $10 USDT)
        test_symbol = "BTCUSDT"  # Make sure the pair is traded on the testnet
        logger.info(
            f"Attempting to place a test MARKET BUY order for {test_symbol} ($10)..."
        )
        order_resp = await executor.place_order(
            test_symbol, "BUY", "MARKET", quoteOrderQty=10.0
        )
        logger.info(f"Test Order Response: {order_resp}")

        logger.info("Waiting for 60 seconds to observe userData stream...")
        await asyncio.sleep(60)

        logger.info("Getting open orders again...")
        open_orders_after = await executor.get_open_orders()
        logger.info(f"Testnet Open Orders after test: {open_orders_after}")

    except ValueError as ve:
        logger.error(f"Initialization error: {ve}")
    except Exception as e:
        logger.error(f"Error during Testnet example usage: {e}", exc_info=True)
    finally:
        if executor:
            logger.info("Stopping user data stream in finally block...")
            await executor.stop_user_data_stream()
        if session and not session.closed:
            await session.close()  # Closing the session created for the example
            logger.info("Example aiohttp session closed.")
        logger.info("--- Testnet Example Finished ---")


if __name__ == "__main__":
    if not logging.getLogger("bot_module").hasHandlers():
        logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    logger.info("Running executor.py standalone for testing...")
    try:
        asyncio.run(example_usage_testnet())
    except KeyboardInterrupt:
        logger.info("Standalone execution interrupted.")
    except Exception as e:
        logger.critical(
            f"Unhandled exception during standalone run: {e}", exc_info=True
        )
