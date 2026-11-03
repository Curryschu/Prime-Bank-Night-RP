# PrimeBank – Night RP

Fiktive RP-Bank für Night RP. Kein echtes Bankkonto und kein echtes Geld.

## Funktionen
- Anmeldung und Namensanzeige über Discord OAuth2
- Automatische PrimeBank-Kontonummer
- Kontostand und letzte Transaktionen
- Überweisungen zwischen PrimeBank-Konten
- Admin-Verwaltung zum Gutschreiben/Abziehen von RP-Geld

## 1. Discord OAuth2 einrichten
1. Öffne https://discord.com/developers/applications und wähle deine Anwendung (oder erstelle eine).
2. Unter **OAuth2 → General** kopierst du `Client ID` und `Client Secret`.
3. Füge bei **Redirects** exakt diese URL hinzu: `https://DEINE-RENDER-URL.onrender.com/callback`
4. In Render setzt du:
   - `DISCORD_CLIENT_ID` = Client ID
   - `DISCORD_CLIENT_SECRET` = Client Secret
   - `DISCORD_REDIRECT_URI` = exakt dieselbe Callback-URL

Der Login benötigt nur den OAuth2-Scope `identify`. Es wird kein Discord-Passwort abgefragt.

## 2. Render-Umgebungsvariablen
- `SECRET_KEY`: langer zufälliger geheimer Wert (Render kann ihn generieren)
- `DATABASE_PATH`: `/var/data/primebank.sqlite`
- `COOKIE_SECURE`: `true`
- `CURRENCY_NAME`: z. B. `Night-Dollar`
- `ADMIN_DISCORD_IDS`: Discord User-IDs der Bank-Admins, mehrere IDs mit Komma trennen

Die mitgelieferte `render.yaml` richtet einen persistenten Datenträger ein. Dafür kann je nach Render-Tarif ein kostenpflichtiger Dienst erforderlich sein. Ohne persistenten Datenträger können SQLite-Daten bei Neustarts/Deployments verloren gehen.

## 3. Admin
Trage deine persönliche Discord User-ID in `ADMIN_DISCORD_IDS` ein. Als Admin kannst du unter `/admin` Konten aufladen oder Geld abziehen. Die ID findest du in Discord mit aktiviertem Entwicklermodus über Rechtsklick auf dein Profil → Benutzer-ID kopieren.

## 4. Lokal testen
```bash
pip install -r requirements.txt
set SECRET_KEY=lokaler-test-schluessel
set DISCORD_CLIENT_ID=...
set DISCORD_CLIENT_SECRET=...
set DISCORD_REDIRECT_URI=http://127.0.0.1:5000/callback
set COOKIE_SECURE=false
set ADMIN_DISCORD_IDS=DEINE_DISCORD_USER_ID
python app.py
```

Dann `http://127.0.0.1:5000` öffnen.
