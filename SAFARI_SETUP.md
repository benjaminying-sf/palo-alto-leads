# Enable Safari Automation (One-time, ~2 minutes)

This unlocks automated scraping of:
- ✅ Probate cases — Santa Clara Superior Court portal
- ✅ Tax delinquent — DTAC auction page

Safari is already on your Mac. No downloads needed.

---

## Step 1 — Enable Develop Menu in Safari

1. Open **Safari**
2. In the top menu bar: **Safari → Settings** (or press ⌘,)
3. Click the **Advanced** tab
4. Tick the checkbox: **"Show Develop menu in menu bar"**
5. Close settings

---

## Step 2 — Allow Remote Automation

1. In the top menu bar, you'll now see a **Develop** menu
2. Click **Develop**
3. Click **"Allow Remote Automation"** (so it has a checkmark)

---

## Step 3 — Enable SafariDriver in Terminal

1. Open **Terminal** (press ⌘+Space, type Terminal, press Enter)
2. Copy and paste this line, then press Enter:

```
safaridriver --enable
```

You may see a prompt asking for your Mac password — type it and press Enter.

---

## Step 4 — Turn On Safari Automation in the App

1. Open Terminal and run:

```
open -a TextEdit "/Users/benjaminying/Documents/Claude Code/Palo Alto Real Esate/.env"
```

2. Find this line:
```
# USE_SAFARI_AUTOMATION=true
```

3. Remove the `#` at the start so it reads:
```
USE_SAFARI_AUTOMATION=true
```

4. Press **⌘S** to save.

---

## Step 5 — Test It

```
cd "/Users/benjaminying/Documents/Claude Code/Palo Alto Real Esate"
python3 main.py --test
```

Safari will briefly open, visit the county website, then close automatically.
You'll get a test email confirming it worked.

---

## What Happens Every Sunday

When the system runs at 6pm Sunday:
1. Safari opens automatically (you'll see it flash open for ~10 seconds)
2. It visits the court portal → searches for new probate cases
3. It visits DTAC → checks for tax-default auction properties
4. Safari closes automatically
5. Results are combined with bankruptcy leads → emailed to you

**Note:** Your Mac must be awake (not sleeping) at 6pm Sunday for this to work.
To wake it, go to: System Settings → Battery → Options → "Prevent automatic sleeping..."
