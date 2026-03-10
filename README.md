# Auri — Personal Financial Intelligence

A local-first, AI-assisted financial planning app for Canadian investors.
Upload your broker CSV exports, run retirement projections, build wealth plans,
and get AI commentary — all from a desktop app with no cloud dependency by default.

> **Disclaimer:** Auri is a personal financial planning tool, not professional
> financial advice. Always consult a qualified financial advisor before making
> investment decisions.

---

## Features

- **Portfolio Dashboard** — Aggregates holdings across TFSA, RRSP, RRIF, CASH, and more
- **Retirement Planner** — CPP/OAS/pension income, Monte Carlo projections, RRIF drawdown, tax estimates
- **Wealth Builder** — Savings optimizer, portfolio projector, rebalancer, net worth tracker
- **AI Commentary** — Profile-aware analysis via Groq (free), OpenAI, Anthropic, or xAI
- **Snapshots** — Point-in-time portfolio captures for tracking progress over time
- **Fully local** — your financial data never leaves your machine

Tested with TD WebBroker CSV exports. Designed for Ontario-based investors (Canadian tax rules, RRIF minimums, 2026 brackets).

---

## Getting started

### Option A — Windows single-file app (easiest)

Download `auri.exe` from the [Releases](https://github.com/Auri-Builder/Auri/releases) page, double-click, and follow the setup wizard.

See [INSTALL.md](INSTALL.md) for first-run instructions and troubleshooting.

### Option B — Run from source (Python 3.12+)

```bash
git clone https://github.com/Auri-Builder/Auri.git
cd Auri
python3 -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -r requirements.txt
streamlit run Home.py
```

Opens at `http://localhost:8501`.

---

## AI provider setup

Auri works without an AI key (portfolio data and projections run fully offline).
AI commentary requires one free API key:

**Groq (recommended — free tier)**
1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Enter it in the Wizard → AI Provider tab inside the app

Other supported providers: OpenAI, Anthropic (Claude), xAI (Grok).

---

## First-time setup

1. Launch the app and complete the **Setup Wizard** (sidebar → Wizard)
2. Export your holdings CSV from your broker and upload it in the wizard
3. Fill in your investor profile and retirement details
4. Return to the **Hub** to access Portfolio, Wealth Builder, and Retirement Planner

See [docs/profile_data_guide.md](docs/profile_data_guide.md) for a data collection checklist
(useful to fill out before your first session, or to share with your financial advisor).

---

## Data & privacy

- All personal data (CSV files, profiles, answers) is stored locally and gitignored
- The AI layer receives only whitelisted aggregate fields — no account numbers,
  institution names, or raw transaction data
- See [SECURITY_NOTES.md](SECURITY_NOTES.md) for full details

---

## Project structure

```
agents/ori_ia/      Portfolio analytics, market data, LLM commentary
agents/ori_rp/      Retirement planner (CPP/OAS, cashflow, Monte Carlo, tax)
agents/ori_wb/      Wealth Builder (optimizer, projector, rebalancer, net worth)
core/               Job runner, caching, shared utilities
pages/              Streamlit pages (hub, portfolio, retirement, wealth builder, wizard, ...)
refs/               Tax tables, RRIF minimums, symbol reference data
docs/               Architecture notes, advisor data guide
tests/              Pytest test suite
Home.py             App entry point
run.py              PyInstaller entry point (exe builds)
```

---

## Building the Windows exe

Requires Windows + Python 3.12 + `pip install pyinstaller==6.13.0`.

```bat
build.bat
```

Output: `dist\auri.exe` (~150–200 MB single file).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing / feedback

This project is in active personal use. Issues and PRs welcome.
If you find it useful, a GitHub star is appreciated.
