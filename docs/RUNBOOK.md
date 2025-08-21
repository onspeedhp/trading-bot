# Live Trading Runbook

> ⚠️ **CRITICAL: This runbook is for live trading operations only. Follow all safety procedures.**

## 1. Dry-Run Validation

### Pre-Flight Checklist
- [ ] All API keys configured (Helius, Birdeye, Telegram)
- [ ] RPC endpoint tested and responsive
- [ ] Encrypted keypair file ready
- [ ] Telegram bot token and admin IDs set
- [ ] Risk management settings reviewed

### Validation Steps

**1.1 Paper Mode with Live Endpoints**
```bash
# Use production config but force dry-run
cp configs/prod.yaml configs/validation.yaml
# Edit: set dry_run: true and position_size_usd: 1

# Run validation
solbot --config configs/validation.yaml --profile validation
```

**Expected Output:**
- ✅ Jupiter quote requests successful
- ✅ Swap transaction builds complete
- ✅ RPC simulation passes
- ✅ No actual trades executed
- ✅ Telegram alerts for simulated trades

**1.2 Verify Data Sources**
```bash
# Check logs for:
# - Helius data polling
# - Birdeye price feeds
# - DexScreener lookups
# - All sources returning valid data
```

**1.3 Test Risk Management**
- Confirm position sizing calculations
- Verify daily loss limits enforced
- Check cooldown periods working
- Validate slippage controls

## 2. Minimal Live Test

### Safety Configuration
```yaml
# configs/minimal-test.yaml
dry_run: false
position_size_usd: 1.0  # Minimal amount
daily_max_loss_usd: 5.0  # Very conservative
max_slippage_bps: 50  # 0.5% max slippage
preflight_simulate: true
allow_devnet: false
unsafe_allow_high_slippage: false
```

### Test Execution

**2.1 Start Minimal Test**
```bash
# Run with minimal configuration
solbot --config configs/minimal-test.yaml --profile minimal-test
```

**2.2 Monitor First Trade**
- Watch for buy execution
- Verify transaction signature
- Check Telegram alert received
- Confirm position recorded

**2.3 Manual Sell Test**
```bash
# Stop bot after successful buy
# Manually sell position via Jupiter/Solana wallet
# Verify position closed correctly
```

**2.4 Validation Criteria**
- ✅ Buy transaction successful
- ✅ Transaction signature valid
- ✅ Telegram alert received
- ✅ Position recorded in database
- ✅ Manual sell works correctly

## 3. Monitoring

### Real-Time Monitoring

**3.1 Log Analysis**
```bash
# Monitor key metrics in logs:
# - Quote latency: < 2 seconds
# - Swap build time: < 1 second  
# - Simulation time: < 3 seconds
# - Send time: < 5 seconds
# - Total round-trip: < 10 seconds
```

**3.2 Telegram Alerts**
- **Trade Executions**: Buy/sell confirmations with details
- **Risk Events**: Daily loss limits, cooldown triggers
- **Errors**: Failed quotes, RPC errors, simulation failures
- **Status**: `/status` command for current state

**3.3 Key Metrics to Track**
```bash
# Check these regularly:
# - PnL per trade
# - Success rate (fills vs fails)
# - Average execution time
# - Slippage vs expected
# - Daily loss vs limit
```

### Alert Thresholds
- **High Latency**: > 15 seconds total execution
- **High Slippage**: > 2% actual vs expected
- **Failed Trades**: > 10% failure rate
- **Daily Loss**: > 80% of daily limit

## 4. Incident Procedures

### Emergency Stop Procedures

**4.1 Immediate Stop (Kill Switch)**
```bash
# Option 1: Environment variable
export EMERGENCY_STOP=true
# Bot checks this and stops trading

# Option 2: Send Telegram command
/emergency_stop  # If implemented

# Option 3: Kill process
pkill -f "solbot.*prod"
```

**4.2 Safe Mode Re-enable**
```bash
# 1. Stop bot immediately
pkill -f "solbot.*prod"

# 2. Switch to dry-run mode
sed -i 's/dry_run: false/dry_run: true/' configs/prod.yaml

# 3. Verify no live trading
grep "dry_run:" configs/prod.yaml

# 4. Restart in safe mode
solbot --config configs/prod.yaml --profile prod
```

### Key Rotation (If Compromised)

**4.3 Emergency Key Rotation**
```bash
# 1. Stop all trading immediately
pkill -f "solbot.*prod"

# 2. Move current keypair to backup
mv ./secrets/solana-main.enc ./secrets/solana-main.enc.backup

# 3. Generate new keypair
# (Use your preferred method: Phantom, CLI, etc.)

# 4. Encrypt new keypair
python scripts/secret_vault.py encrypt \
  --in new-keypair.json \
  --out ./secrets/solana-main.enc \
  --key-from-env VAULT_KEY

# 5. Verify new keypair
python scripts/secret_vault.py show \
  --in ./secrets/solana-main.enc \
  --key-from-env VAULT_KEY

# 6. Test with dry-run before live
solbot --config configs/prod.yaml --profile prod
```

### Incident Response Checklist

**4.4 When Incident Occurs**
- [ ] **IMMEDIATE**: Stop trading (kill switch or process kill)
- [ ] **ASSESS**: Check logs for root cause
- [ ] **CONTAIN**: Switch to dry-run mode
- [ ] **ANALYZE**: Review what went wrong
- [ ] **FIX**: Address underlying issue
- [ ] **TEST**: Validate fix in dry-run
- [ ] **RESUME**: Gradual return to live trading

**4.5 Common Issues & Solutions**

| Issue | Immediate Action | Root Cause | Fix |
|-------|------------------|------------|-----|
| High slippage | Stop trading | Market volatility | Reduce position size |
| RPC errors | Check RPC health | Network issues | Switch RPC endpoint |
| Failed simulations | Review transaction | Invalid parameters | Check token decimals |
| No quotes | Verify Jupiter API | API rate limits | Add delays/retries |

## 5. Operational Commands

### Daily Operations
```bash
# Start trading
solbot --config configs/prod.yaml --profile prod

# Check status
curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
  -d "chat_id=<ADMIN_ID>&text=/status"

# View recent logs
tail -f bot.log | grep -E "(ERROR|WARN|CRITICAL)"

# Check database
sqlite3 prod_bot.sqlite "SELECT * FROM trades ORDER BY ts DESC LIMIT 10;"
```

### Health Checks
```bash
# Verify all components
python -c "
from bot.config.settings import load_settings
from bot.runner.pipeline import TradingPipeline
settings = load_settings('prod', 'configs/prod.yaml')
pipeline = TradingPipeline(settings)
print('✅ All components loaded successfully')
"
```

## 6. Recovery Procedures

### After Emergency Stop
1. **Analyze logs** for incident cause
2. **Fix configuration** if needed
3. **Test in dry-run** mode
4. **Gradual restart** with minimal position size
5. **Monitor closely** for first few trades
6. **Scale up** only after stability confirmed

### Performance Optimization
- Monitor execution times
- Adjust priority fees based on network conditions
- Optimize RPC endpoint selection
- Review and adjust risk parameters

---

**Remember**: When in doubt, stop trading and investigate. It's better to miss a trade than to lose money due to a preventable error.
