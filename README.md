# Solana Trading Bot

A production-ready Solana trading bot with paper trading capabilities, built with Python 3.13.

## Features

- Paper trading mode for safe testing
- Real-time data feeds from Helius, Birdeye, and DexScreener
- Configurable risk management
- Telegram alerts
- Prometheus metrics
- Modular architecture with type safety

## Quickstart

### Prerequisites

- Python 3.13
- pip

### Setup

1. **Clone and navigate to the project:**
   ```bash
   cd trading-bot
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp configs/paper.yaml configs/local.yaml
   # Edit configs/local.yaml with your settings
   ```

5. **Run in paper trading mode:**
   ```bash
   make run-paper
   ```

## Development

### Code Quality

```bash
make lint      # Run ruff linter
make format    # Format with black
make typecheck # Run mypy type checker
make test      # Run tests
```

### Project Structure

```
bot/
├── config/          # Configuration management
├── core/            # Core types and interfaces
├── data/            # Data providers (Helius, Birdeye, DexScreener)
├── filters/         # Trading filters and heuristics
├── risk/            # Risk management
├── exec/            # Execution engines (paper, Jupiter)
├── alerts/          # Alert systems (Telegram)
├── persist/         # Data persistence
└── runner/          # Main pipeline runner
```

## Configuration

The bot uses YAML configuration files:

- `configs/paper.yaml` - Paper trading configuration
- `configs/dev.yaml` - Development settings
- `configs/prod.yaml` - Production settings

## Docker

Build and run with Docker:

```bash
docker build -t trading-bot .
docker run trading-bot
```

## License

MIT License
