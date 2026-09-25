# Running and hosting the app

The product has two parts that work together:

| Part | Folder | What it is | Runs on |
|---|---|---|---|
| **Web app** | `app/`, `components/`, `lib/` | The website people use (Next.js) | Port 3000 |
| **API** | `backend/` | Reads bills, does the tax maths, stores data, runs the assistant (FastAPI, Python) | Port 8000 |
| **Database** | — | Stores accounts, bills, invoices, chats | SQLite file locally; PostgreSQL online |

The web app forwards every `/api/...` request to the API, so the browser only ever talks to one address.

---

## 1. Run it on your own computer

Install once: **Python 3.11 or newer** (python.org) and **Node.js 20 or newer** (nodejs.org).

### Terminal 1 — the API
```bash
cd gst-invoice-assistant
python -m venv .venv
# Mac/Linux:   source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env

# Mac/Linux:
export DATABASE_URL="sqlite:///./gst.db" PYTHONPATH=.
# Windows PowerShell:
#   $env:DATABASE_URL="sqlite:///./gst.db"; $env:PYTHONPATH="."

python scripts/init_db.py
python scripts/seed_personal_demo.py      # 3 demo accounts (optional)
uvicorn backend.api.main:app --reload     # API at http://localhost:8000/docs
```

### Terminal 2 — the website
```bash
cd gst-invoice-assistant
npm install
npm run dev                               # open http://localhost:3000
```

**Demo logins** (password `demo12345`): `me@demo.in` (salaried), `freelancer@demo.in`, `shop@demo.in`.

Every day after the first time: activate the venv, set the two variables, run `uvicorn …` in one
terminal and `npm run dev` in the other.

---

## 2. Put it online: Neon (database) + Render (API) + Vercel (website)

```
 Browser ──► Vercel (website) ──/api/*──► Render (Python API) ──► Neon (PostgreSQL)
```
The website forwards `/api/*` to Render, so the browser only ever sees your Vercel domain and login
cookies just work. Do the steps **in this order** — each one needs an address from the one before.

### Step 0 — Put the code on GitHub
github.com → **New repository** (private is fine) → upload the unzipped folder, or:
```bash
git init && git add . && git commit -m "first version"
git remote add origin https://github.com/<you>/<repo>.git && git push -u origin main
```

### Step 1 — Database on Neon (about 5 minutes)
1. neon.tech → sign up → **New project** → region **AWS Asia Pacific (Singapore)** (closest to India).
2. On the dashboard, copy the **connection string** (starts with `postgresql://…`). Keep it handy.
   You can paste it exactly as shown; the app adds the driver name itself.

### Step 2 — API on Render (about 10 minutes)
1. render.com → sign up with GitHub → **New → Blueprint** → choose your repository.
   Render reads `render.yaml` and sets everything up.
2. When asked, paste the Neon connection string into **DATABASE_URL**. Leave **OPENROUTER_API_KEY** empty for now.
   (`SESSION_SECRET` is generated for you automatically.)
3. Click **Apply**. The first build takes 5–10 minutes. Tables are created automatically when the API starts.
4. When it shows **Live**, copy the address, e.g. `https://munshi-api.onrender.com`, and open
   `https://munshi-api.onrender.com/health` in your browser. You should see `{"status":"ok"}`.
5. *Optional — demo accounts online:* on your own computer run
   `DATABASE_URL="<your Neon string>" PYTHONPATH=. python scripts/seed_personal_demo.py`

> **Plan:** `render.yaml` uses the **Starter** plan (about $7/month). You can change `plan: starter` to
> `plan: free`, but a free service sleeps after 15 minutes idle and the next visitor waits up to a minute
> (sign-in may time out once while it wakes). Fine for a demo; not for real users.

### Step 3 — Website on Vercel (about 5 minutes)
1. vercel.com → sign up with GitHub → **Add New → Project** → import the same repository.
   Framework is detected as **Next.js**; leave build settings as they are.
2. Before clicking Deploy, open **Environment Variables** and add:
   - `BACKEND_URL` = your Render address from Step 2 (no slash at the end) — **required**; the build
     stops with a clear message if it's missing
   - optional branding: `NEXT_PUBLIC_BRAND_NAME`, `NEXT_PUBLIC_BRAND_ACCENT`, … (section 3)
3. **Deploy.** Open the Vercel address → **Create free account** → add a bill → ask the assistant.

`BACKEND_URL` and the brand variables are read when the site is **built**. If you change them later,
go to **Deployments → ⋯ → Redeploy**.

### Turning on full AI conversation (optional)
openrouter.ai → create an API key → on Render set `OPENROUTER_API_KEY` to it and `LLM_ENABLED` to `true`
→ Render redeploys by itself. Without a key the assistant still answers its supported questions.

### Custom domain
Vercel → Project → **Domains** → add e.g. `app.yourbrand.in` and follow the DNS instructions.
Nothing else changes: the API stays on Render behind the website.

### If something goes wrong
| Symptom | Fix |
|---|---|
| Vercel build fails with "BACKEND_URL is not set" | Add it (Step 3.2), then redeploy |
| Website loads but sign-up says "Something went wrong" | Open `<Render address>/health`. If it doesn't load, check Render → Logs. If it does, check `BACKEND_URL` on Vercel has no typo, then redeploy |
| Render log: "SESSION_SECRET is still the default" | Set `SESSION_SECRET` on Render to a long random value |
| Render log mentions the database | Re-copy the Neon connection string into `DATABASE_URL` |
| Console keeps returning to the login page | `CONSOLE_API_KEY` on Vercel must equal `API_KEY` on Render, and your account must be staff (`create_staff.py`) |
| First request after a while is very slow | You're on Render's free plan; it was asleep |

## 3. The staff console (second website)

The console is its own website in the `console/` folder. It uses the **same Render API and database**;
you only add one more Vercel project.

```
 Personal app  (Vercel project 1, repo root)   ──┐
                                                 ├──/api/*──► Render API ──► Neon
 Staff console (Vercel project 2, console/)    ──┘
```

**Locally** (API already running on :8000):
```bash
cd console && npm install && npm run dev -- -p 3001      # http://localhost:3001
```
Console login needs a staff account:
- demo: `python scripts/seed_demo_data.py` creates `staff@demo.in` / `demo12345` plus the business demo data
- real: `python scripts/create_staff.py priya@yourfirm.in "Priya Sharma"`

**Online:**
1. On **Render** → your API service → **Environment**: confirm `CONSOLE_ENABLED` is `true`, and copy the
   value of `API_KEY` (the Blueprint generated it).
2. On **Vercel** → **Add New → Project** → import the **same** repository again.
3. Set **Root Directory** to `console` (click *Edit* next to it). Framework: Next.js.
4. Environment variables:
   - `BACKEND_URL` = your Render address (same as the personal app)
   - `CONSOLE_API_KEY` = the `API_KEY` value from step 1 (keep it secret — never prefix it with `NEXT_PUBLIC_`)
   - optional: `NEXT_PUBLIC_BRAND_NAME`, `NEXT_PUBLIC_BRAND_ACCENT`
5. Deploy, then create your staff account against the online database (on your computer):
   `DATABASE_URL="<Neon string>" PYTHONPATH=. python scripts/create_staff.py you@firm.in "Your Name"`
   (or run `seed_demo_data.py` with the same `DATABASE_URL` for the demo accounts).
6. Open the console address → sign in. Anyone who isn't staff is sent back to the login page.

**Security built in:** strangers and personal-app users can't open any console page or API route; the console
API filters out personal-app bills on every query (tested in `tests/test_console_security.py`); the console is
hidden from search engines.

## 4. White-labelling for a partner

Everything visible is set by environment variables on the **website** (then redeploy):

| Variable | Example | Effect |
|---|---|---|
| `NEXT_PUBLIC_BRAND_NAME` | `Kotak TaxMate` | Name everywhere, page titles |
| `NEXT_PUBLIC_BRAND_TAGLINE` | `Tax help for Kotak customers` | Landing page and titles |
| `NEXT_PUBLIC_BRAND_ACCENT` | `#E11D48` | Buttons, highlights, charts |
| `NEXT_PUBLIC_BRAND_LOGO_URL` | `https://…/logo.png` | Replaces the default mark |
| `NEXT_PUBLIC_BRAND_SUPPORT_EMAIL` | `help@partner.in` | Footer |
| `NEXT_PUBLIC_BRAND_SHOW_POWERED_BY` | `false` | Hides the "verified tax rules" footnote |

One deployment per partner (a separate Vercel project + its own API and database) keeps each partner's
customers completely separate. That is the simplest safe model to start with.

---

## 5. Turning on photo reading (OCR)

PDF bills with selectable text work out of the box. Photos and scanned PDFs need OCR:
```bash
pip install -r requirements-ml.txt          # PaddleOCR; large download
```
On Render, change `dockerfilePath` in `render.yaml` to `./Dockerfile.ml` and pick a plan with at least 2 GB RAM. Without OCR, a photo uploads but most fields
will be empty — the app says so on the bill page.

---

## 6. Before real users

- [ ] `SESSION_SECRET` set to a long random value; `COOKIE_SECURE=true`.
- [ ] Database backups on (Neon/Supabase do this on paid tiers).
- [ ] Update `data/tax/rules_india.json` after every Union Budget (it is labelled with its financial year).
- [ ] Have a CA review the tax rules and the wording of the assistant's answers.
- [ ] Add a privacy policy: you are storing people's financial documents (India's DPDP Act, 2023 applies).
- [ ] Add password reset by email (not built yet).
