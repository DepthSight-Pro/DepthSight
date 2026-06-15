<p align="center">
  <img src="docs/logo.svg" alt="DepthSight Logo" width="320">
</p>

<h1 align="center">DepthSight</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white" alt="Docker Ready"></a>
  <a href="#-one-click-deploy"><img src="https://img.shields.io/badge/deploy-one--click-00C853.svg?logo=gnubash&logoColor=white" alt="One-Click Deploy"></a>
  <a href="https://depthsight.pro"><img src="https://img.shields.io/badge/website-depthsight.pro-lightgrey.svg" alt="Website"></a>
  <a href="https://zread.ai/DepthSight-Pro/DepthSight" target="_blank"><img src="https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff" alt="zread"/></a>
</p>

<p align="center">
  <strong>Enterprise-Grade, Multi-Tenant SaaS-in-a-Box for Algorithmic Trading.</strong>
</p>

Built to democratize the fin-tech industry, it provides a complete infrastructure to launch your own crypto trading platform (like 3Commas or Veles) out of the box. It features a drag-and-drop strategy builder, an AI-powered assistant, a federated community hub for sharing strategies, isolated multi-user environments, and native Bitcart crypto billing.

<p align="center">
  <em>You bring the traffic. DepthSight handles the execution.</em>
</p>

> ⭐ **If you find this project useful, please consider giving it a star! It helps the community grow and reach more developers.**

> **⚠️ DISCLAIMER: HIGH FINANCIAL RISK**
>
> **DepthSight is currently in Open Beta.** The software is provided "as is", without warranty of any kind. 
> Algorithmic and live trading involves real financial risk and can result in the total loss of your funds. The authors, contributors, and licensors of this project are **not responsible for any financial losses**, damages, or issues arising from the use of this software. 
> 
> Always use testnet or paper trading first. Do not connect real funds unless you fully understand the code and have verified the entire workflow in a controlled environment. You are solely responsible for your trading decisions and capital.

<p align="center">
  <img src="docs/strategy-editor.gif" alt="Visual Strategy Builder Demo" width="800">
  <br>
  <em>Describe your idea in plain language → AI builds a complete multi-stage strategy.</em>
</p>

## Core Features

- **Visual Strategy Builder:** A drag-and-drop interface with 40+ logic blocks. Build complex strategies with cross-referencing nodes (e.g., dynamically place a stop loss behind order book density, a breakout candle, or a key level).
- **AI-Powered Assistant:** Generate complete strategy logic from text prompts or **even screenshots of chart setups**. The AI also analyzes your live trades and backtest results to provide actionable trading recommendations.
- **Weighted Foundations System:** Assign weights to different market conditions. A trade executes only if a target confidence threshold is met, allowing for flexible, probability-based entries rather than strict "all-or-nothing" boolean logic.
- **Dynamic Risk Management:** An intelligent RM engine that automatically adapts position sizing and risk parameters based on the historical and real-time performance of each specific trading pair.
- **Advanced Market Data:** Native support for order book snapshots, trade streams, open interest, BTC correlation, and multi-timeframe analysis.
- **Rich Visualization:** Complete transparency into bot logic. Every trade includes a detailed decision tree explaining *why* it was taken, visualized directly on trading charts.
- **Dual Backtesting Engines:** Lightning-fast vector backtester for rapid prototyping and genetic optimization, plus a detailed candle/tick-level engine for precise execution simulation.
- **Discovery Hub & Community Network:** A centralized sharing repository where users import verified strategy templates, inspect community trading ideas (complete with win rate, drawdown, mini-charts, and comments), and join discussions. Includes a live global node network topology map (with complete IP privacy) showing real-time heartbeat synchronization log feeds, and a dialogue-enabled support ticket system supporting chat messages and image uploads.
- **Enterprise-Grade Infrastructure:** FastAPI backend, real-time WebSocket events, background Celery workers, and multi-exchange execution.
## Enterprise-Grade Scalability

DepthSight is built for heavy-duty algorithmic trading, requiring a minimum of 6 modern CPU cores and 16GB RAM for a stable solo instance. Its stateless architecture naturally supports advanced horizontal scaling patterns for Cloud SaaS deployments handling thousands of users:

1. **Distributed Market Data (Sharding):** The centralized market data service reduces the number of exchange WebSocket connections, allowing for shard-based division of trading pairs.
2. **Redis Splitting:** Separate instances for system state (JWT, rate limits, Celery) and high-throughput HFT market data via Pub/Sub.
3. **Horizontal Worker Scaling:** Trading bot processes run in a sharded, stateless pool, evenly dividing computation and risk management processing across CPU cores or physical nodes.
4. **PgBouncer-Ready:** Designed to pool PostgreSQL connections, seamlessly handling thousands of concurrent connections from stateless FastAPI or bot worker nodes.

- **Supported Exchanges:** Native integration with **Binance** and **Bybit** (Fully tested and stable). Support for **Bitget**, **OKX**, **Gate.io**, and **BingX** is currently in development and will be enabled in future updates. 
  *Note: We recommend using Binance or Bybit for live trading at this stage.*
- **Multi-Tenant SaaS Ready:** Built-in JWT authentication, Redis-based quota management, and fully isolated execution environments designed for multi-user, commercial deployments.
- **Crypto Billing & Payments:** Native integration with Bitcart for processing cryptocurrency subscriptions and payments.
- **Modern Clients:** Full-featured React web dashboard and a mobile-optimized PWA.

## 💖 Support the Project

DepthSight is completely free and open-source. Maintaining a professional-grade trading infrastructure requires significant resources. To keep the project alive and free for everyone, we use exchange broker programs as our primary support mechanism.

**How it works:** By default, the software includes our Broker/Referral IDs for supported exchanges. When you trade using DepthSight, the exchange shares a small portion of their trading fee with us to fund further development. **This costs you absolutely nothing**—your trading fees remain exactly the same as they would be otherwise.

If you find this project valuable, please consider keeping the default Broker IDs active. 

Alternatively, if DepthSight has helped you automate your trading or build your business, you can support us directly via donations:
- **USDT (TRC-20):** `TJXbcdPuay8o1VKX2PGHzQ6kVtWjd7aDUi`
- **BTC:** `34GLMAKyzwuXZW9t6gUZhzF3x2gwBmh9uU`
- **ETH (ERC-20):** `0x83af3385655a3991d01fb9bf831bea4d75d99409`

*Thank you for your support!*

## License & Commercial Use

DepthSight is released under the **GNU AGPLv3** open-source license. You are free to download, modify, and run this platform for your personal trading. Furthermore, anyone who modifies and runs this software as a service over a network is required to release their modifications under the same AGPLv3 license.

**Dual Licensing for SaaS / Commercial Use:**
If you want to build a closed-source fin-tech business or a commercial SaaS offering on top of our infrastructure without open-sourcing your modifications under AGPLv3, you must purchase a commercial license. Please contact `admin@depthsight.pro` for White-Label licensing.

## 🚀 One-Click Deploy

DepthSight requires a minimum of 6 modern CPU cores and 16GB RAM. If you need a server, you can support this open-source project by using our referral links below:

- **[DigitalOcean](https://www.digitalocean.com/?refcode=681ba89f8858&utm_campaign=Referral_Invite&utm_medium=Referral_Program&utm_source=badge)** — Get **$200 in free credit** for 60 days. Excellent for stable API performance.
- **[Vultr](https://www.vultr.com/?ref=9905236-9J)** — Get **$300 in free credit** to test the platform. Great high-frequency compute nodes.
- **[LuxVPS](https://billing.luxvps.net/aff.php?aff=249)** — Best price-to-performance ratio (~€20/mo). Excellent choice for a budget-friendly but powerful trading node (Crypto accepted).
- **[is*hosting](https://ishosting.com/affiliate/NzU2OCM2)** — Premium hosting with a massive selection of global locations (from $50+/mo). Perfect if you need a server physically close to a specific exchange for lower latency (Crypto accepted).

Deploy a fully configured instance on any Ubuntu 22.04+ server with a single command. The script auto-installs Docker, generates all secrets, configures networking, sets up a firewall, and starts every service.

```bash
curl -sL "https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh" | sudo bash
```

The interactive installer will ask for your domain (or default to `<IP>.sslip.io` with auto-SSL via Caddy), and optionally enable Bitcart crypto billing.

### Updating

Pull the latest release and rebuild without downtime:

```bash
sudo bash /opt/depthsight/update.sh
```

### Manual / Local Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Before using this outside a local throwaway setup, replace all `change_me_*` secrets in `.env`, especially the Redis ACL passwords and API/JWT/encryption keys.

After startup:

- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:5173`
- PWA: `http://localhost:5174`

## Repository layout

```text
/
|-- api/            FastAPI app, auth, models, websocket server
|-- bot_module/     Trading engine, strategies, execution, backtesting
|-- frontend/       Web dashboard
|-- pwa/            Mobile PWA
|-- tests/          Automated test suite
|-- docs/           Public documentation

|-- docker-compose.yml
|-- requirements.txt
|-- market_data_service.py
`-- bot_runner.py
```

## Services and ports

| Service | Default port | Purpose |
| --- | ---: | --- |
| PostgreSQL | 5432 | Persistent storage |
| Redis | internal only | Cache, state, pub/sub, task broker |
| API | 8000 | REST API |
| WebSocket | 8765 | Real-time events |
| Frontend | 5173 | Web dashboard |
| PWA | 5174 | Mobile client |
| Bot | n/a | Trading runtime |
| Market data | n/a | Central exchange stream fan-out for bot workers |
| Celery worker | n/a | Background jobs |

Redis is not exposed on the host by default. Compose creates service-level Redis ACL users for `api`, `websocket`, `bot`, `celery`, and `market_data`; each application container connects with its own `REDIS_USERNAME` and password.


### Local development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn api.depthsight_api:app --host 0.0.0.0 --port 8000 --reload
uvicorn api.websocket_server:app --host 0.0.0.0 --port 8765 --reload
python bot_runner.py
celery -A tasks.celery_app worker --loglevel=info --pool=prefork -c 2
```

On Unix-like shells, replace `.venv\Scripts\activate` with `source .venv/bin/activate`.

For local development, `MARKET_DATA_FANOUT_MODE=direct` keeps market data inside the bot process and does not require the market-data service. To test the production fan-out path locally, set `MARKET_DATA_FANOUT_MODE=redis`, run Redis, and start the service in a separate terminal:

```bash
python market_data_service.py
python bot_runner.py
```

Run the clients separately when needed:

```bash
cd frontend
npm install
npm run dev

cd ..\pwa
npm install
npm run dev
```

## Payments & Billing (Bitcart)

DepthSight is built to be a fully monetizable SaaS out of the box. It includes a pre-configured `docker-compose.bitcart.yml` file to spin up a self-hosted [Bitcart](https://bitcart.ai/) instance for accepting cryptocurrency payments (BTC, LTC, TRX, BNB, MATIC) without third-party fees.

To start the billing infrastructure alongside the main app:

```bash
docker compose -f docker-compose.bitcart.yml up -d
```

The Bitcart services will automatically inherit URLs from your `.env` configuration (e.g., `BITCART_ADMIN_URL`, `BITCART_STORE_URL`, `BITCART_API_URL`). To link the DepthSight backend to your Bitcart store, configure the `BITCART_*` variables in your `.env` file.

## Environment

Create `.env` from `.env.example` and set the values for your target environment.

Minimum required values for a local run:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_USERNAME`
- `REDIS_PASSWORD`
- `REDIS_API_PASSWORD`
- `REDIS_WEBSOCKET_PASSWORD`
- `REDIS_BOT_PASSWORD`
- `REDIS_CELERY_PASSWORD`
- `REDIS_MARKET_DATA_PASSWORD`
- `JWT_SECRET_KEY`
- `CONFIRMATION_SECRET_KEY`
- `API_KEY_SECRET`
- `API_ENCRYPTION_KEY`

In Docker, the Redis container builds ACL users from the service-specific password variables. The `REDIS_PASSWORD` value is only a fallback used when a service-specific password is not set. For a single-process local Redis without ACLs, leave `REDIS_USERNAME` empty and use `REDIS_PASSWORD` only.

Market-data mode:

- `MARKET_DATA_FANOUT_MODE=direct`: legacy/simple mode. Bot workers open exchange market-data streams directly.
- `MARKET_DATA_FANOUT_MODE=redis`: production mode. Bot workers request subscriptions through Redis, while `market_data_service.py` owns exchange WebSocket connections and publishes shared snapshots/events back through Redis.

For live trading, also set the Binance credentials for the selected environment:

- `ACTIVE_TRADING_ENVIRONMENT`
- `TRADING_MARKET_TYPE`
- `TESTNET_BINANCE_*`

Use testnet credentials first.

### Frontend Customization

For the frontend and PWA, you can customize the application's branding (URLs, support email, etc.) by copying `.env.example` to `.env` in the respective `frontend/` and `pwa/` directories:

- `VITE_APP_URL`
- `VITE_SUPPORT_EMAIL`
- `VITE_TELEGRAM_URL`

## Testing

Backend test suite:

```bash
pytest
```

> **Note on E2E Tests:** Several end-to-end tests interact with live exchange testnets (Binance, Bybit, Bitget, Gate.io, BingX). If you do not provide the respective `TESTNET_*` API keys in your `.env` file (see `.env.example`), these specific tests will gracefully skip. To run the full suite, add your testnet keys.

Frontend checks:

```bash
cd frontend
npm run build
npm run lint
```

PWA build:

```bash
cd pwa
npm run build
```

## Documentation

- Public setup and contribution guide: [docs/open-source-guide.md](docs/open-source-guide.md)
- Architectural and API documentation: [Docs pending](https://zread.ai/DepthSight-Pro/DepthSight/)

## Contributing

- Keep changes focused.
- Add or update tests when behavior changes.
- Do not commit secrets or generated artifacts.
- Prefer testnet and paper-trading paths when verifying trading changes.
