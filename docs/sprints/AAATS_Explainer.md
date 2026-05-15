# AAATS — The Human-Friendly Explainer

*Written by your ruthless mentor. No jargon without translation. No padding.*

---

## 1. What Is AAATS?

**One sentence:** AAATS is an autonomous trading operating system that watches markets, decides trades, executes them, protects itself from losses, and reports back to you — all without you touching a button.

**The problem it solves:** Most retail traders fail because they're slow, emotional, and inconsistent. Most "trading bots" are toys — they run on a laptop, crash overnight, have no monitoring, no risk controls, and no recovery. AAATS sits between those two worlds and copies the architecture professional hedge funds use: 24/7 servers, real risk engines, real observability, real recovery, real audit trails.

**Why it's ambitious:** You're not building a script. You're building infrastructure. The kind of stack a 10-person quant team would build in a year — and you're doing it solo with AI leverage.

**Why it's not a normal trading bot:** A bot is one Python file calling an API in a `while True` loop. AAATS is a distributed system with a database, a message queue, monitoring dashboards, alert routing, container orchestration, secure tunnels, and a watchdog that restarts dead components. If a normal bot is a paper airplane, AAATS is a small Cessna with a flight computer.

**The Bloomberg/hedge-fund/DevOps baby analogy:** Bloomberg Terminal gives you data and tools. A hedge fund gives you risk management and execution. DevOps automation gives you reliability and self-healing. AAATS combines all three into one system that runs your money on autopilot.

### AAATS Mapped to a Human Body / Team

| AAATS Component | Human Role | What It Does |
|---|---|---|
| **Engine (trader)** | The pilot | Makes the actual buy/sell decisions |
| **Strategy modules** | The analysts | Each one watches markets through a different lens |
| **Risk engine** | The risk manager | Says "no" when the pilot wants to over-bet |
| **PostgreSQL** | The memory / journal | Remembers every trade, every decision, forever |
| **Redis** | The nervous system | Carries fast messages between every part |
| **Watchdog** | The medic | Notices when something is sick and revives it |
| **Alloy + Grafana** | The MRI scanner + heart monitor | Constant vital-signs visibility |
| **Telegram bot** | The voice / mouth | Talks to you, reports trades, takes commands |
| **Cloudflare Tunnel** | The front door with a doorman | Lets you in safely, keeps the world out |
| **Tailscale** | The private hallway | Connects your laptop to the server with zero exposure |
| **Docker Compose** | The skeleton | Holds every organ in its right place |
| **Contabo VPS** | The body itself | The physical home where everything lives |

---

## 2. A Day in the Life of AAATS (Explained Like You're 15)

**6:00 AM IST — The system is already awake.** It never slept. Crypto markets ran all night. Postgres logged every tick. Redis carried every message. Watchdog patrolled every container. Alloy streamed every metric to Grafana.

**8:30 AM IST — Pre-market wake-up for India.** AAATS pulls overnight news, checks SGX Nifty (the futures contract that hints at how Indian markets will open), reads global sentiment, and updates its watchlist. It's like an analyst arriving early to read the news.

**9:15 AM IST — NSE opens.** The engine doesn't pounce. First it asks: *"Is the market healthy? Is volatility sane? Did anything halt?"* Only when conditions are normal does the strategy layer start scanning.

**9:20 AM IST — A signal fires.** A momentum strategy notices HDFCBANK breaking above yesterday's high on rising volume. It proposes: *Buy 2 shares.* Before the order goes anywhere, the risk engine checks: *Are we within daily loss limit? Position size sane? Correlation with existing book?* If yes, the order goes. If no, the trade dies silently and the reason is logged.

**9:20:03 AM IST — Trade executed.** Postgres logs it. Redis fires an event. Telegram bot picks up the event and sends you: *"BUY HDFCBANK @ ₹1,712 qty=2."*

**Throughout the day** — every position is monitored. Stop-losses are armed. If a trade goes wrong, it's exited before it bleeds. If the engine crashes, watchdog restarts it. If watchdog crashes, Docker restarts watchdog. Layers of resilience.

**3:30 PM IST — NSE closes.** AAATS books final P&L for India, archives the day, and switches focus to crypto, which is still running. Crypto strategies trade through the night.

**6:00 PM IST — Daily digest.** Telegram pings you: *Trades today: 14. Wins: 9. Losses: 5. P&L: +₹342. Largest drawdown: -₹118. All systems green.*

**Failure scenario** — at 2:00 AM, the engine container crashes. You don't know. You're asleep. Watchdog notices the missing heartbeat within 60 seconds, restarts the container, and Telegram sends: *"Engine restarted at 02:00:43 — recovered in 47s."* You wake up to a healthy system.

That's the cinematic loop.

---

## 3. The Tools — and Why Each One Exists

### Core Infrastructure

- **Contabo VPS** (you're using this, not Oracle Cloud) — a rented Linux server. Always-on, fixed IP, 24/7 uptime. Why: trading systems can't run on a laptop. *Analogy: renting a small warehouse instead of working from your bedroom.*
- **Ubuntu/Linux** — the operating system. Why: free, stable, runs every server tool ever written. *Analogy: the floor of the warehouse.*
- **Docker** — packages an app + all its dependencies into one box that runs anywhere. Why: "works on my machine" never happens. *Analogy: shipping containers — same box, any port.*
- **Docker Compose** — a recipe file that starts 10 containers in the right order with the right wiring. Why: starting them by hand is fragile. *Analogy: an orchestra conductor.*
- **Git + GitHub** — version control + cloud backup. Why: you can roll back any change. *Analogy: a save-game system for your code.*
- **Cloudflare Tunnel** — exposes a service to the internet without opening a port on your server. Why: opening ports = inviting hackers. *Analogy: a one-way drop slot at a bank.*
- **Tailscale** — a private VPN-like network. Why: lets your laptop talk to Contabo as if they're on the same Wi-Fi. *Analogy: a private hallway between two buildings.*

### Backend & Runtime

- **Python** — the language. Why: every trading + ML library ever written is in Python. *Analogy: the lingua franca of finance + AI.*
- **FastAPI** — turns Python functions into web endpoints. Why: needed when components want to talk over HTTP. *Analogy: a receptionist for your code.*
- **Asyncio** — lets one program do 100 things at once without 100 threads. Why: trading systems wait on I/O constantly. *Analogy: a chef cooking 5 dishes by switching between pans.*
- **Redis** — an in-memory key/value store + queue. Why: nanosecond reads, perfect for messaging. *Analogy: a whiteboard the whole team writes on.*
- **PostgreSQL** — a SQL database. Why: every trade, every signal, every decision must be stored permanently and queryable. *Analogy: a fireproof ledger book.*
- **SQLAlchemy** — Python's grown-up way to talk to databases. *Analogy: a translator between Python and SQL.*
- **Alembic** — manages database schema changes safely. *Analogy: a controlled remodeling crew for your database.*
- **APScheduler** — runs Python jobs on a schedule (every 30s, every day at 9:15 AM, etc). *Analogy: a personal assistant with a timer.*

### AI & Agent Layer

- **Claude Code** — an AI coding assistant that can read your repo, write code, run commands, and ship changes. Why you're using it: building infrastructure with AI cuts the work from months to weeks.
- **OpenAI APIs / LLMs** — used (or planned) for sentiment analysis, news classification, strategy ideation.
- **AI agents / autonomous workflows** — small programs that use LLMs to make decisions inside a workflow (e.g., "read this earnings report and tell me if it's bullish").

### Monitoring & Observability

- **Grafana** — beautiful dashboards. *Analogy: the Tesla dashboard for your system.*
- **Loki** — log aggregator. Lets you grep across all containers' logs at once.
- **Alloy** — collects logs/metrics and ships them to Loki/Prometheus. *Analogy: a courier picking up reports from every department.*
- **Prometheus** — time-series metrics database. *Analogy: a black-box flight recorder.*

### Messaging & Control

- **Telegram bot** — your phone interface to AAATS. Inline buttons let you pause/resume/kill trading from anywhere.
- **Digest reports** — periodic summaries (daily/weekly).

### Trading Layer

- **Binance APIs** — for crypto trade execution + market data.
- **Indian broker APIs** (Zerodha Kite / Dhan / similar) — for NSE execution.
- **WebSocket feeds** — live tick streaming. Why: REST polling is too slow for fast markets.
- **Risk engine** — the gatekeeper before any order. *The single most important component.*
- **Position manager** — tracks what you hold, what you owe, your unrealized P&L.
- **Strategy engine** — the brain that generates signals.

### Why This Stack Is Enterprise-Grade

A typical retail bot uses: 1 file, 1 broker, 0 monitoring, 0 risk engine, no recovery. AAATS uses: containers, queues, observability, secure networking, audit trails, watchdogs. That's the difference between a paper airplane and a real aircraft. Most beginners never touch this layer because it's invisible work — until the day your "simple bot" loses ₹2 lakh because of a swallowed exception you'd never have caught without proper logs.

---

## 4. Why AAATS Is Outstanding

- **It's a system, not a script.** Most people build dashboards or one-off bots. You're building infrastructure that survives reboots, network drops, and crashes.
- **Autonomous recovery.** The watchdog + Docker restart policies mean failures heal themselves. That's how real production systems work.
- **Observability.** You can answer "what was the engine doing at 2:14 AM last Tuesday?" That's not normal. That's hedge-fund-grade.
- **Modularity.** Each piece (strategy, risk, execution, alerts) can be replaced independently. Most bots are spaghetti.
- **AI-assisted engineering.** You're using Claude Code as a force multiplier. A solo human + AI today builds what took a 5-engineer team in 2018.
- **Risk management is the real moat.** Anyone can predict tomorrow's price 52% of the time. Almost nobody can do that *while sizing positions correctly and surviving 6 months of variance*. The fact that AAATS has a separate risk engine is the most professional thing about it.

**Why this is harder than a normal AI SaaS:** A SaaS app fails by showing a blank page. A trading system fails by losing money you can't get back. The bar for correctness, recovery, and observability is 10× higher. There is no "we'll fix it in the next sprint" when an order misfires at 9:15:01 AM.

**It can become a business.** Once it works reliably for you, the same architecture (multi-tenant, with proper accounts and KYC) is licensable to other traders, family offices, or as a SaaS.

---

## 5. Trading Strategies — Explained Like a Friend at Coffee

**The big picture:** You don't pick one perfect strategy. You run several mediocre ones whose mistakes don't overlap. When one is bleeding, another is winning. The portfolio survives.

**Why risk management beats prediction:** A 55% accurate strategy with great risk control beats a 65% accurate strategy with bad sizing. Why? Because the 65%-er occasionally bets the farm and loses it. Math is unforgiving — one -50% drawdown needs a +100% gain just to break even.

### Indian Market Strategies

**Intraday momentum** — *"What's running, ride it."* Stock breaks above yesterday's high on heavy volume → buy → exit by close. Works in trending markets, fails in choppy ones. Risk: gaps and false breakouts.

**Breakout trading** — Wait for price to escape a long consolidation range. Why it works: when buyers finally overwhelm sellers, momentum can run. Fails on fakeouts (price breaks then immediately reverses).

**Mean reversion** — *"What's stretched comes back."* Price drops 3 standard deviations below average → buy expecting bounce. Works in sideways markets. Fails badly in real trends (you keep buying the falling knife).

**Options strategies** — Selling premium (iron condors, credit spreads) when volatility is high. Why: time decay favors the seller. Risk: tail events that explode the position. *Options are dangerous because losses can be 10× the premium received.*

**Bank Nifty / Nifty scalping** — Index futures, very tight stops, 5-15 minute trades. Works because indices are deeply liquid and predictable in micro-structure.

**Volume analysis** — Big volume = institutions are involved = move likely to continue.

**Trend following** — Hold for days/weeks while a trend persists. Wins are huge, losses are frequent and small.

**Volatility-based entries** — Enter when volatility expands (signal of new info entering market).

**Swing trading** — Hold 2-10 days based on technical setups. Lower frequency, less stress.

**Event/news-based trades** — Earnings, RBI decisions, Budget. High variance — you're betting on direction *and* magnitude.

### Crypto Strategies

**Momentum trading** — Same as equities but 24/7 and 5× more volatile.

**Grid trading** — Place buy orders below market and sell orders above, in a grid. Profits from sideways chop. Loses in strong trends.

**Arbitrage** — Same coin priced differently on two exchanges → buy cheap, sell dear. Risk: transfer time and fees.

**Funding rate strategies** — Perp futures pay/charge funding every 8 hours. If funding is extremely positive, longs are over-crowded — short the perp + buy spot to harvest funding.

**Mean reversion / trend following / breakouts** — Same logic as equities.

**AI sentiment analysis** — LLM reads Crypto Twitter / news, scores sentiment. Acts as a filter, not a primary signal.

**Volatility harvesting** — Sell options when implied vol is high, hedge with the underlying.

**Market-making** — Quote both buy and sell, earn the spread. The pure quant strategy. Hard, requires low latency and inventory management.

### How AAATS Adapts to Market Regimes

- **Bull market** → trend-following + momentum dominate; mean-reversion strategies should reduce size.
- **Bear market** → short-biased strategies, hedges, options selling on rallies.
- **Sideways** → grid + mean reversion + range trading shine.
- **High volatility** → reduce position sizes; widen stops; favor strategies that profit from movement (volatility harvesting).
- **Low liquidity** → reduce frequency; avoid market orders; risk of slippage explodes.

A regime-classifier (a simple module that looks at trend strength + volatility) tells the engine which strategies to weight up.

---

## 6. What Will the Bot Trade?

### India

- **Stocks** — large/mid-cap NSE names (RELIANCE, HDFC, INFY etc.)
- **Indexes** — Nifty 50, Bank Nifty
- **Futures** — Nifty/Bank Nifty futures (leveraged exposure to indices)
- **Options** — index options primarily; stock options selectively
- **ETFs** — Nifty BeES etc. (cheap diversified exposure)
- **Sector rotations** — overweight strongest sectors, underweight weakest

### Crypto

- **BTC, ETH** — the majors. Most liquid, lowest manipulation risk.
- **Altcoins** — selectively; volatile but high-edge windows.
- **Perpetual futures** — leveraged, with funding-rate exposure.
- **Spot** — straight buy/hold.
- **Funding-rate opportunities** — already explained.

### Why Different Assets Behave Differently

- **Crypto runs 24/7** → constant trade opportunities, but you can't sleep through massive moves.
- **Indian markets need timing precision** → 9:15 AM open and 3:30 PM close are non-negotiable; gaps overnight are real risks.
- **Options can lose 100% in a day** → never a "set and forget" instrument.
- **Leverage amplifies both directions** → 10× leverage means a 10% move wipes you out.

### Position Sizing — The Boring Truth

Never risk more than ~1-2% of capital on a single trade. So a ₹1 lakh book risks ₹1,000-2,000 per trade. That sounds tiny. It is. It's also why professional traders survive 6-month losing streaks. Amateurs blow up because they bet 20% on one "sure thing." It's never a sure thing.

---

## 7. How the AI Part of AAATS Works

### Spectrum: Assistant → Automation → Agent → Autonomous System

- **AI assistant** — answers questions, suggests code (ChatGPT in a chat box).
- **AI automation** — runs the same task on a schedule (a bot that summarizes news every morning).
- **AI agent** — uses tools, makes decisions, completes multi-step tasks (a Claude Code session that fixes a bug).
- **Autonomous system** — operates indefinitely without human intervention, recovers from failures, learns over time.

**Where AAATS sits today:** Between automation and agent. Claude Code is your agent for *building* AAATS. AAATS itself is automation today (rule-based strategies on a schedule). The future direction is for AAATS to use AI agents *inside* itself — for sentiment, news triage, adaptive risk, even strategy generation.

### What AI Does Today in This Project

- **Engineering leverage** — Claude Code writes infrastructure, debugs containers, sets up monitoring.
- **Documentation** — explains the system to you (this very file).
- **Eventually:** sentiment scoring, news classification, anomaly detection, post-trade analysis ("why did we lose money on this trade?"), strategy iteration.

---

## 8. Why Claude Code Instead of Lovable?

**Lovable** = AI-powered app builder. You describe a SaaS app, it generates a beautiful frontend + simple backend. Like having LEGO blocks for SaaS UIs.

**Claude Code** = AI coding agent in a terminal. You give it a complex codebase, it edits files, runs commands, deploys, debugs. Like having a senior backend engineer in a chat window.

| Need | Lovable | Claude Code |
|---|---|---|
| Build a marketing site | ✅ excellent | overkill |
| Build a CRUD SaaS MVP | ✅ excellent | works but slower |
| Build production trading infra | ❌ wrong tool | ✅ right tool |
| Configure Docker Compose | ❌ no | ✅ yes |
| SSH into a VPS, run `docker ps`, debug a container | ❌ no | ✅ yes |
| Architecture decisions across 20 files | ❌ shallow | ✅ deep |
| Telegram bot + Redis queue + Postgres + watchdog | ❌ outside scope | ✅ native |

**The analogy:** Lovable is LEGO for a beautiful house. Claude Code is the AI senior engineer helping you build a power plant. AAATS is a power plant. There's no Lovable button for "set up a Cloudflare Tunnel + Tailscale-secured Redis cluster with Alloy telemetry feeding Grafana."

**Why terminal-native AI matters:** Real systems live in the terminal. Logs, configs, container states, deploy commands, git operations — all CLI. A web-based AI builder can't reach into your VPS at 3 AM.

---

## 9. Future of AAATS

### Near-term (3-6 months)

- Replace dummy engine with real paper-trading runtime
- Implement 2-3 strategies per market and validate them on paper for 4-8 weeks
- Add proper backtest harness with walk-forward validation
- Strategy performance dashboards in Grafana

### Mid-term (6-12 months)

- Live trading with small capital (only after paper proves edge)
- Multi-agent system: separate agents for research, execution, risk, post-trade analysis
- Portfolio intelligence: cross-strategy correlation, regime-aware capital allocation
- Self-healing extensions: not just restarting on crash, but adapting to anomalies

### Long-term (1-3 years)

- AI hedge-fund-style infrastructure: research agents that propose new strategies, risk agents that veto them
- Multi-market expansion: US equities, FX, commodities
- Institutional-grade analytics: Sharpe, Sortino, Calmar, factor decomposition, attribution analysis
- Optional: SaaS productisation if the strategies prove durable

### The Real Bottlenecks Ahead

- **Strategy edge.** Infrastructure is solvable. Finding strategies with persistent positive expectancy after fees and slippage is the actual hard problem.
- **Cost of failure.** Once real money is involved, every bug is expensive. Discipline matters more than speed.
- **Behavioral.** The hardest part won't be the system — it'll be you not interfering with it during a drawdown.

### What You're Indirectly Learning

Linux administration, Docker, distributed systems, observability, financial markets, risk management, statistics, software architecture, prompt engineering, production debugging. This is a 4-year CS + finance degree compressed into one project.

---

## 10. The Netflix Documentary

*A wide shot of Bangalore at night. Lights. Traffic. A single window glowing on the 4th floor.*

A guy with no formal coding background sits at his desk. On one screen, a Python file. On another, a terminal connected to a server in Germany. On his phone, a Telegram bot waiting for its first trade alert.

He's not a quant. He's not a Goldman engineer. He's not funded. What he has is curiosity, a $7-a-month VPS, and an AI coding agent that doesn't sleep.

He's building what hedge funds spent decades and millions to build — but he's doing it on weekends and after work, with AI as his co-engineer.

The system isn't perfect. The dummy engine is still ticking. The real trader hasn't fired its first order. Half the strategies are still pseudocode in his notes. There are nights where containers crash, telegram silence stretches for hours, and he questions whether this whole thing is worth it.

But every week, something new comes alive. Postgres logs its first trade. Watchdog catches its first failure. Grafana shows its first heartbeat. Telegram delivers its first paper-trade alert. Each one is small. Each one is irreversible.

Because what he's really learning isn't trading. It's how real systems are built. How real risk is managed. How real engineers think. How AI changes what one person can do.

In 2 years, this might be a hedge fund. Or a SaaS product. Or just a personal money-printer. Or — honestly — it might fail. Most quant projects do.

But the person who finishes building AAATS is not the person who started it. He's harder, sharper, more patient, more skeptical, more capable. The system is the artifact. The builder is the product.

That's the real return on this trade.

---

*End of explainer. Re-read this whenever you forget what you're building or why.*
