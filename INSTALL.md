# Auri — Installation Guide

## Quick Start (Windows)

1. Download **Auri.exe** from the [Releases page](https://github.com/Auri-Builder/Auri/releases)
2. Move it anywhere you like — e.g. `C:\Users\You\Documents\Auri\`
3. Double-click **Auri.exe**

Your browser opens automatically to the Auri dashboard.

> **First launch takes 15-20 seconds** — the app is unpacking in the background.
> Subsequent launches are faster (5-10 seconds).

---
## TD webbbroker portfolio downloads
To download CSV files from your TD webbroker account, follow these steps:
1. Log in to your TD webbroker account and navigate to the "Statements and Documents" section.
2. Select the account and the specific statement period you want to download. (ensure you get all your accounts needed for your portfolio)
3. Look for an option to download or export the statement and choose the CSV format. Usually in the upper right corner 
4. Complete the download process to save the file on your computer. 

For more detailed instructions, you can refer to the video linked in the first result. (pending)
## First-Time Setup

The Hub will guide you through 5 steps:

| Step | What you need |
|------|--------------|
| 1. Upload CSV | TD WebBroker Holdings export (any recent date) |
| 2. Personal Profile | Your name, age, province, income |
| 3. Wealth Builder | RRSP/TFSA contribution room (from CRA My Account) |
| 4. Retirement | CPP estimate, account balances, spending target |
| 5. AI Provider | Free Groq API key (optional, for commentary) |

**Getting a free Groq API key** (optional as you can use most AI providers you just need an API key):
1. Go to [console.groq.com](https://console.groq.com)
2. Sign up → API Keys → Create API Key
3. Paste it in Setup Wizard → AI Provider

---

## Your Data

Everything stays on your computer. Auri never transmits personal or financial data.

Your data is saved at:
```
C:\Users\YourName\AppData\Local\Auri\
```
To back up or transfer your setup, copy that folder.

---

## "Windows protected your PC" Warning

Click **More info → Run anyway**.

Auri isn't signed with a commercial code certificate — that costs $300+/year
and isn't practical for a free personal tool. The source code is fully open at
[github.com/Auri-Builder/Auri](https://github.com/Auri-Builder/Auri).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Browser doesn't open | Open [http://localhost:8501](http://localhost:8501) manually |
| Blank page / spinning | Wait 30 seconds, then refresh |
| Crashes on startup | Delete `%APPDATA%\.streamlit\` and relaunch |
| "DLL load failed" | Install [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) |

---

## Updating

Replace **Auri.exe** with the new version. Your data in `AppData\Local\Auri\` is kept.
