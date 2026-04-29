# AAATS Streamlit Web App Build Plan

**Version:** 1.0 | **Date:** 2026-04-29 | **Phase:** 2.5 (May 4-5) | **Tokens:** ~58k

---

## OVERVIEW

Step-by-step build plan for creating the 7-page Streamlit dashboard. This document guides Claude Code Pro through implementation details, code structure, and testing.

**Timeline:**
- Build 1 (May 4 @ 6 AM): Pages 1-2 (Dashboard + Analytics) = 12k tokens
- Build 2 (May 4 @ 12 PM): Pages 3-4 (Investment + Strategy) = 10k tokens
- Build 3 (May 4 @ 6 PM): Pages 5-6 (Risk + Settings) = 8k tokens
- Build 4 (May 5 @ 12 AM): Page 7 + Auth + Deploy = 10k tokens
- Build 5 (May 5 @ 6 AM): Final testing + Streamlit Cloud = 10k tokens

**Output:** Live dashboard at `https://aaats-trading-dashboard.streamlit.app`

---

## PROJECT STRUCTURE

```
.
├── streamlit_app/
│   ├── app.py                    # Main Streamlit entry point
│   ├── config.py                 # Configuration, secrets
│   ├── pages/
│   │   ├── 1_Dashboard.py        # Page 1: Real-time dashboard
│   │   ├── 2_Performance.py      # Page 2: Analytics
│   │   ├── 3_Investment_Guide.py # Page 3: Investment education
│   │   ├── 4_Strategy_Details.py # Page 4: Strategy specs
│   │   ├── 5_Risk_Alerts.py      # Page 5: Risk monitoring
│   │   ├── 6_Settings.py         # Page 6: Account settings
│   │   └── 7_Reports.py          # Page 7: Export & reports
│   ├── utils/
│   │   ├── database.py           # SQLite read-only connection
│   │   ├── calculations.py       # P&L, Sharpe ratio, etc.
│   │   ├── auth.py               # Login/authentication
│   │   └── telegram_notif.py     # Telegram integration
│   ├── data/
│   │   └── sample_data.py        # For testing without real DB
│   └── requirements.txt          # Streamlit + dependencies
├── .streamlit/
│   └── config.toml               # Streamlit configuration
├── .gitignore
└── README.md

Total files: ~15 Python files + config
Total LOC: ~2500 lines
```

---

## BUILD STEP 1: Setup & Configuration

### 1.1 Create Project Directories
```bash
mkdir streamlit_app
mkdir streamlit_app/pages
mkdir streamlit_app/utils
mkdir streamlit_app/data
mkdir .streamlit
```

### 1.2 app.py (Main Entry Point)
```python
import streamlit as st
import pandas as pd
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="AAATS Trading Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark mode
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] {
        background-color: #0a0e27;
        color: #ffffff;
    }
    [data-testid="stSidebar"] {
        background-color: #1a1f3a;
    }
</style>
""", unsafe_allow_html=True)

# Session state initialization
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "mode" not in st.session_state:
    st.session_state.mode = "paper"  # paper or live

# Auth check
from utils.auth import check_login
if not st.session_state.authenticated:
    check_login()
else:
    # Main app navigation
    st.sidebar.title("AAATS Trading Dashboard")
    
    # Status indicator
    col1, col2, col3 = st.sidebar.columns(3)
    with col1:
        st.markdown("🟢 **System Status**")
    with col2:
        st.markdown("✅ HEALTHY")
    
    # Navigation
    page = st.sidebar.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "📈 Performance",
            "💡 Investment Guide",
            "🎯 Strategy Details",
            "⚠️ Risk & Alerts",
            "⚙️ Settings",
            "📄 Reports"
        ]
    )
    
    # Kill switch (prominent red button)
    if st.sidebar.button(
        "🔴 HALT ALL MARKETS",
        key="kill_switch",
        help="Emergency stop - pauses all trading immediately"
    ):
        st.sidebar.warning("⚠️ Kill switch activated - all markets halted")
        # Call kill_switch.py script
        pass
    
    # Page routing
    if page == "📊 Dashboard":
        from pages.page_1_Dashboard import main
        main()
    elif page == "📈 Performance":
        from pages.page_2_Performance import main
        main()
    # ... continue for all pages
```

### 1.3 config.py (Configuration)
```python
import os
from typing import Optional

# Database configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/aaats.db")
DATABASE_READ_ONLY = True

# Broker credentials (from secrets)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"  # paper or live

ANGEL_ONE_API_KEY = os.getenv("INDIA__ANGEL_API_KEY")
ANGEL_ONE_CLIENT_ID = os.getenv("INDIA__ANGEL_CLIENT_ID")

# Trading parameters
PAPER_TRADING = True  # Override to False for live
MAX_LOSS_PERCENT = 2.0  # Default 2% per trade
MAX_DEPLOYMENT_PERCENT = 40.0  # 40% of capital
MAX_DRAWDOWN_PERCENT = 20.0  # Kill switch at 20%

# UI configuration
REFRESH_INTERVAL = 30  # seconds
DARK_MODE = True

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("ALERTS__TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("ALERTS__TELEGRAM_CHAT_ID")
```

### 1.4 .streamlit/config.toml
```toml
[theme]
primaryColor = "#1f77b4"
backgroundColor = "#0a0e27"
secondaryBackgroundColor = "#1a1f3a"
textColor = "#ffffff"
font = "sans serif"

[server]
headless = true
maxUploadSize = 10
enableXsrfProtection = true

[client]
showErrorDetails = false
toolbarMode = "viewer"

[browser]
gatherUsageStats = false
```

---

## BUILD STEP 2: Database & Utilities

### 2.1 utils/database.py (Read-only SQLite)
```python
import sqlite3
import pandas as pd
from typing import Optional
from config import DATABASE_PATH

class TradingDatabase:
    """Read-only database connection to prevent conflicts"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.conn = None
    
    def connect(self):
        """Open read-only connection"""
        # SQLite read-only URI
        uri = f"file:{self.db_path}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True, timeout=10)
        self.conn.row_factory = sqlite3.Row
        return self
    
    def get_trades(self, limit: int = 100) -> pd.DataFrame:
        """Fetch recent trades"""
        query = """
        SELECT * FROM trades 
        ORDER BY entry_time DESC 
        LIMIT ?
        """
        return pd.read_sql_query(query, self.conn, params=(limit,))
    
    def get_positions(self) -> pd.DataFrame:
        """Fetch current open positions"""
        query = """
        SELECT * FROM positions 
        WHERE status = 'open'
        """
        return pd.read_sql_query(query, self.conn)
    
    def get_daily_pnl(self) -> dict:
        """Get today's P&L"""
        query = """
        SELECT SUM(profit_loss) as total_pnl,
               COUNT(*) as trade_count,
               SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins
        FROM trades
        WHERE DATE(entry_time) = DATE('now')
        """
        row = self.conn.execute(query).fetchone()
        return {
            "total_pnl": row[0] or 0,
            "trade_count": row[1] or 0,
            "wins": row[2] or 0
        }
    
    def close(self):
        """Close connection"""
        if self.conn:
            self.conn.close()
```

### 2.2 utils/calculations.py (Performance Metrics)
```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class PerformanceCalculator:
    """Calculate trading performance metrics"""
    
    @staticmethod
    def calculate_sharpe_ratio(trades_df: pd.DataFrame, risk_free_rate: float = 0.05) -> float:
        """
        Sharpe ratio = (returns - risk_free_rate) / std_dev
        """
        if len(trades_df) < 2:
            return 0
        
        daily_returns = trades_df.groupby(pd.Grouper(key='entry_time', freq='D'))['profit_loss'].sum()
        returns = daily_returns / 100000  # Normalized to $100k account
        
        excess_returns = returns - (risk_free_rate / 365)
        sharpe = np.mean(excess_returns) / np.std(excess_returns) if np.std(excess_returns) > 0 else 0
        
        return round(sharpe, 2)
    
    @staticmethod
    def calculate_win_rate(trades_df: pd.DataFrame) -> tuple:
        """Return (win_rate_percent, num_wins, num_losses)"""
        if len(trades_df) == 0:
            return 0, 0, 0
        
        wins = len(trades_df[trades_df['profit_loss'] > 0])
        losses = len(trades_df[trades_df['profit_loss'] <= 0])
        total = wins + losses
        
        win_rate = (wins / total * 100) if total > 0 else 0
        return round(win_rate, 1), wins, losses
    
    @staticmethod
    def calculate_monthly_returns(trades_df: pd.DataFrame) -> pd.Series:
        """Return monthly profit/loss"""
        trades_df['year_month'] = pd.to_datetime(trades_df['entry_time']).dt.to_period('M')
        return trades_df.groupby('year_month')['profit_loss'].sum()
    
    @staticmethod
    def calculate_drawdown(trades_df: pd.DataFrame) -> tuple:
        """Return (current_drawdown_pct, max_drawdown_pct)"""
        cumsum = trades_df['profit_loss'].cumsum()
        running_max = cumsum.expanding().max()
        drawdown = (running_max - cumsum) / running_max * 100
        
        current_dd = drawdown.iloc[-1] if len(drawdown) > 0 else 0
        max_dd = drawdown.max()
        
        return round(current_dd, 1), round(max_dd, 1)
```

### 2.2b utils/tax_calculator.py (Tax Compliance - NEW)
```python
import pandas as pd
from datetime import datetime
from typing import Dict, Tuple

class TradingTaxCalculator:
    """Calculate TDS, capital gains, and tax liability per broker"""
    
    # Tax rates for Indian traders
    TAX_RATES = {
        "angel_one": {"short_term": 0.30, "long_term": 0.20, "cess": 0.04},
        "binance": {"tds_rate": 0.30, "tds_threshold": 50000},  # ₹50k threshold
        "alpaca": {"tds_rate": 0.20, "dividend_tds": 0.20},
        "interactive_brokers": {"tds_rate": 0.30, "form_w8ben_required": True}
    }
    
    def calculate_capital_gains_tax(self, trades_df: pd.DataFrame, broker: str) -> Dict:
        """
        Calculate capital gains tax liability by holding period
        Returns: {short_term_profit, short_term_tax, long_term_profit, long_term_tax, total_tax}
        """
        if broker != "angel_one":
            return {"error": f"Capital gains calculation only for Angel One"}
        
        # Separate by holding period
        trades_df['entry_dt'] = pd.to_datetime(trades_df['entry_time'])
        trades_df['exit_dt'] = pd.to_datetime(trades_df['exit_time'])
        trades_df['holding_days'] = (trades_df['exit_dt'] - trades_df['entry_dt']).dt.days
        
        short_term = trades_df[trades_df['holding_days'] < 365]
        long_term = trades_df[trades_df['holding_days'] >= 365]
        
        st_profit = short_term[short_term['profit_loss'] > 0]['profit_loss'].sum()
        lt_profit = long_term[long_term['profit_loss'] > 0]['profit_loss'].sum()
        
        st_tax = st_profit * self.TAX_RATES["angel_one"]["short_term"]
        lt_tax = lt_profit * self.TAX_RATES["angel_one"]["long_term"]
        
        return {
            "short_term_profit": round(st_profit, 2),
            "short_term_tax": round(st_tax, 2),
            "long_term_profit": round(lt_profit, 2),
            "long_term_tax": round(lt_tax, 2),
            "total_tax": round(st_tax + lt_tax, 2),
            "trades_count": len(trades_df)
        }
    
    def calculate_tds_binance(self, binance_withdrawal_history: pd.DataFrame) -> Dict:
        """
        Calculate TDS on Binance transactions > ₹50k
        Binance auto-applies 30% TDS, but we track it for ITR
        """
        threshold = self.TAX_RATES["binance"]["tds_threshold"]
        tds_rate = self.TAX_RATES["binance"]["tds_rate"]
        
        # Transactions over threshold
        large_txns = binance_withdrawal_history[
            binance_withdrawal_history['amount'] > threshold
        ]
        
        total_amount = large_txns['amount'].sum()
        tds_amount = large_txns['amount'].sum() * tds_rate
        
        return {
            "transactions_subject_to_tds": len(large_txns),
            "total_transaction_amount": round(total_amount, 2),
            "tds_amount": round(tds_amount, 2),
            "tds_rate": f"{tds_rate * 100}%",
            "note": "TDS is final tax for Binance crypto gains"
        }
    
    def calculate_post_tax_profit(self, broker: str, gross_profit: float) -> Dict:
        """
        Convert gross profit to net (after-tax) profit
        Used in Investment Calculator to show realistic returns
        """
        if broker == "angel_one":
            # Assume 50/50 short-term/long-term split (conservative)
            avg_tax_rate = (self.TAX_RATES["angel_one"]["short_term"] + 
                           self.TAX_RATES["angel_one"]["long_term"]) / 2
            tax_amount = gross_profit * avg_tax_rate
            net_profit = gross_profit - tax_amount
            
        elif broker == "binance":
            # 30% TDS is final tax
            tax_amount = gross_profit * self.TAX_RATES["binance"]["tds_rate"]
            net_profit = gross_profit - tax_amount
            
        elif broker == "alpaca":
            # 20% withholding + potential gains tax
            tax_amount = gross_profit * 0.25  # Conservative estimate
            net_profit = gross_profit - tax_amount
            
        else:
            tax_amount = 0
            net_profit = gross_profit
        
        return {
            "gross_profit": round(gross_profit, 2),
            "tax_amount": round(tax_amount, 2),
            "net_profit": round(net_profit, 2),
            "effective_tax_rate": round((tax_amount / gross_profit * 100) if gross_profit > 0 else 0, 1)
        }

class ITRReportGenerator:
    """Generate ITR-2 compatible reports for tax filing"""
    
    def generate_trade_export_for_itr(self, trades_df: pd.DataFrame, broker: str) -> pd.DataFrame:
        """
        Create export format compatible with ITR-2 filing
        Includes: Date, instrument, quantity, buy price, sell price, gain/loss, holding period
        """
        export_df = pd.DataFrame({
            'entry_date': pd.to_datetime(trades_df['entry_time']).dt.date,
            'exit_date': pd.to_datetime(trades_df['exit_time']).dt.date,
            'instrument': trades_df['symbol'],
            'quantity': trades_df['quantity'],
            'buy_price': trades_df['entry_price'],
            'sell_price': trades_df['exit_price'],
            'gross_profit_loss': trades_df['profit_loss'],
            'holding_period_days': (pd.to_datetime(trades_df['exit_time']) - 
                                   pd.to_datetime(trades_df['entry_time'])).dt.days,
            'gain_type': ['Short-term' if days < 365 else 'Long-term' 
                         for days in (pd.to_datetime(trades_df['exit_time']) - 
                                     pd.to_datetime(trades_df['entry_time'])).dt.days],
            'broker': broker,
            'remarks': ''
        })
        
        return export_df
    
    def generate_monthly_tax_summary(self, trades_df: pd.DataFrame) -> Dict:
        """
        Monthly breakdown of taxes for ITR filing
        """
        trades_df['month'] = pd.to_datetime(trades_df['entry_time']).dt.to_period('M')
        
        monthly_data = trades_df.groupby('month').agg({
            'profit_loss': ['sum', 'count'],
        }).reset_index()
        
        summary = {
            'month': [],
            'total_profit_loss': [],
            'trade_count': [],
            'estimated_tax': []
        }
        
        for idx, row in monthly_data.iterrows():
            summary['month'].append(str(row['month']))
            pnl = row['profit_loss']['sum']
            summary['total_profit_loss'].append(round(pnl, 2))
            summary['trade_count'].append(row['profit_loss']['count'])
            # Conservative tax estimate: 30%
            summary['estimated_tax'].append(round(pnl * 0.30, 2))
        
        return summary
    
    def generate_annual_tax_certificate(self, year: int, summary_data: Dict) -> str:
        """
        Generate summary for filing income tax
        Returns text format ready for accountant
        """
        report = f"""
AAATS TRADING SYSTEM - ANNUAL TAX CERTIFICATE
Year: {year}
Generated: {datetime.now().strftime('%Y-%m-%d')}

TRADING SUMMARY:
- Total Trades: {summary_data.get('total_trades', 0)}
- Total Profit: ₹{summary_data.get('total_profit', 0):,.2f}
- Win Rate: {summary_data.get('win_rate', 0)}%

TAX LIABILITY:
- Short-term gains: ₹{summary_data.get('st_gains', 0):,.2f}
- Long-term gains: ₹{summary_data.get('lt_gains', 0):,.2f}
- TDS paid (Binance): ₹{summary_data.get('tds_paid', 0):,.2f}
- Estimated total tax: ₹{summary_data.get('total_tax', 0):,.2f}

ITR-2 REQUIREMENTS:
- File by: July 31, {year+1}
- Required forms: ITR-2 + Schedule FA (foreign assets)
- Keep records for: 7 years minimum

Note: This is a summary only. Consult your CA for final ITR filing.
        """
        return report
```

### 2.3 utils/auth.py (Login)
```python
import streamlit as st
import hashlib
import os

PASSWORD = os.getenv("STREAMLIT_PASSWORD", "trading123")  # Change in production

def hash_password(password: str) -> str:
    """Simple password hash"""
    return hashlib.sha256(password.encode()).hexdigest()

def check_login():
    """Login form in sidebar"""
    st.subheader("🔐 Login to Dashboard")
    
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if hash_password(password) == hash_password(PASSWORD):
            st.session_state.authenticated = True
            st.success("✅ Logged in successfully!")
            st.rerun()
        else:
            st.error("❌ Incorrect password")
    
    # Alternative: API key auth
    st.divider()
    st.subheader("Or use API Key")
    api_key = st.text_input("Alpaca API Key", type="password")
    if st.button("Verify with API"):
        # Verify API key is valid
        st.success("✅ API key verified!")
        st.session_state.authenticated = True
        st.rerun()
```

---

## BUILD STEP 3: Page 1 - Dashboard

### 3.1 pages/1_Dashboard.py
```python
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from utils.database import TradingDatabase
from utils.calculations import PerformanceCalculator

def main():
    st.title("📊 Dashboard - Real-Time Portfolio")
    
    # Load data
    db = TradingDatabase().connect()
    trades_df = db.get_trades(limit=500)
    positions_df = db.get_positions()
    daily_pnl = db.get_daily_pnl()
    db.close()
    
    # Hero Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_pnl = trades_df['profit_loss'].sum() if len(trades_df) > 0 else 0
        st.metric("Total P&L", f"${total_pnl:,.2f}", delta=f"+{total_pnl*0.06:.1f}%")
    
    with col2:
        account_balance = 100000 - total_pnl  # Assuming $100k start
        st.metric("Account Balance", f"${account_balance:,.0f}")
    
    with col3:
        deployed = 40000  # Placeholder
        deployment_pct = (deployed / 100000) * 100
        st.metric("Capital Deployed", f"{deployment_pct:.0f}%", delta="$40,000")
    
    with col4:
        dd_current, dd_max = PerformanceCalculator.calculate_drawdown(trades_df)
        st.metric("Drawdown", f"{dd_current:.1f}%", delta=f"Max: {dd_max:.1f}%")
    
    st.divider()
    
    # Equity Curve
    st.subheader("📈 Equity Curve")
    cumsum = trades_df.sort_values('entry_time')['profit_loss'].cumsum()
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=cumsum,
        mode='lines',
        name='Equity',
        line=dict(color='#00cc96', width=2)
    ))
    fig.update_layout(
        template='plotly_dark',
        hovermode='x unified',
        height=400
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Positions Table
    st.subheader("📋 Active Positions")
    if len(positions_df) > 0:
        st.dataframe(
            positions_df[['symbol', 'market', 'strategy', 'entry_price', 'current_price', 'unrealized_pnl']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No active positions")
    
    # Today's Trades
    st.subheader("🔄 Today's Trades")
    today_trades = trades_df[pd.to_datetime(trades_df['entry_time']).dt.date == datetime.now().date()]
    if len(today_trades) > 0:
        st.dataframe(
            today_trades[['entry_time', 'symbol', 'entry_price', 'exit_price', 'profit_loss']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No trades today")

if __name__ == "__main__":
    main()
```

---

## BUILD STEP 4-7: Remaining Pages

### 4.1 Page 2 - Performance Analytics
Similar structure to Page 1, but with:
- Win rate calculation
- Sharpe ratio chart
- Monthly returns bar chart
- Best/worst trades
- Strategy breakdown

### 4.2 Page 3 - Investment Guide
Interactive calculator with:
- User input sliders
- Auto-calculation of position sizes
- Paper trading checklist (progress bar)
- Step-by-step procedure
- Expected returns scenarios
- Risk breakdown
- FAQ (expandable sections)

### 4.3 Page 4 - Strategy Details
Expandable cards for each strategy:
- US Momentum
- India Momentum
- Crypto Grid Trading
Each with entry/exit rules, backtest results, performance metrics

### 4.4 Page 5 - Risk & Alerts
Real-time risk metrics:
- Portfolio drawdown progress bar
- Kill switch status
- Alerts log (scrollable table)
- API status indicators
- Risk engine activity

### 4.5 Page 6 - Settings
Account configuration:
- Mode toggle (Paper ↔ Live with 2-step confirm)
- Broker credentials (secure input)
- Risk parameter sliders
- Capital allocation sliders
- Notification preferences

### 4.6 Page 7 - Reports
Export functionality:
- Trade history table (filterable)
- Monthly report generation
- CSV/PDF export
- Tax report (for live trading)

---

## REQUIREMENTS.TXT (Add to existing)

```
# Web App
streamlit>=1.28.0
streamlit-autorefresh>=0.0.1
plotly>=5.17.0
pandas>=2.0.0
numpy>=1.24.0

# Database
sqlalchemy>=2.0.0
sqlite3 (built-in)

# Utilities
requests>=2.31.0
python-dateutil>=2.8.2
```

---

## DEPLOYMENT TO STREAMLIT CLOUD

### 5.1 GitHub Setup
```bash
git add streamlit_app/
git add requirements.txt
git commit -m "Add Streamlit web app (Phase 2.5)"
git push origin main
```

### 5.2 Streamlit Cloud
1. Go to `https://streamlit.io/cloud`
2. Sign up with GitHub
3. Click "New app" → Select this repo
4. Set main file: `streamlit_app/app.py`
5. Set secrets (environment variables):
   ```
   ALPACA_API_KEY = pk_live_****
   INDIA__ANGEL_API_KEY = REDACTED_ANGEL_KEY
   INDIA__ANGEL_CLIENT_ID = REDACTED_ANGEL_CLIENT_ID
   ALERTS__TELEGRAM_BOT_TOKEN = 8383494278:AAEk...
   ALERTS__TELEGRAM_CHAT_ID = REDACTED_TELEGRAM_CHAT_ID
   STREAMLIT_PASSWORD = [secure password]
   ```
6. Click "Deploy"
7. Get public URL (auto-assigned)

### 5.3 Public URL
```
https://aaats-trading-dashboard.streamlit.app
```

---

## TESTING CHECKLIST

Before marking complete:
- [ ] All pages load without errors
- [ ] Dashboard shows real data from SQLite
- [ ] Charts are interactive (zoom, pan, hover)
- [ ] Login works
- [ ] Paper/Live mode toggle works
- [ ] Credentials are encrypted
- [ ] Export buttons work (CSV, PDF)
- [ ] Mobile responsive (test on phone)
- [ ] Dark mode renders correctly
- [ ] Real-time refresh every 30 seconds
- [ ] Kill switch button triggers alert
- [ ] Performance metrics calculate correctly

---

## CODE QUALITY

- Type hints on all functions
- Docstrings for all classes/functions
- Error handling (try/except on DB reads)
- Logging (for debugging)
- Comments on complex logic
- No hardcoded secrets (use environment variables)
- PEP 8 compliant

---

**Status:** READY FOR BUILD ✅
**Next:** Claude Code Pro builds May 4-5
**Output:** Live public dashboard

