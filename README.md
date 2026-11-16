# Litter Box Tracker

Automatic per-cat weight tracker for a PetSafe ScoopFree SmartSpin (Roman and Morty). GitHub Actions fetches visits from the Pet Companion cloud every 6 hours and publishes a dashboard to GitHub Pages.

## One-time setup

1. Push this folder to a GitHub repo.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Add these three:

   - `PETSAFE_EMAIL` — your Pet Companion email
   - `PETSAFE_PASSWORD` — your Pet Companion password
   - `APP_PROFILE` — the full contents of `petsafe-app-profile.json` (paste the entire file)

3. In **Settings → Pages**, set **Source** to **GitHub Actions**.
4. Run the **Update dashboard** workflow once (Actions tab → Run workflow), or push to `main`. After it finishes, the dashboard is at your Pages URL (`https://<you>.github.io/<repo>/`).

On your iPhone, open that URL and use **Share → Add to Home Screen** to get an app icon.

`petsafe-app-profile.json` and `visits.json` are gitignored and are never committed. Only `litter-log.json` (the cumulative visit history) is written back to the repo.
