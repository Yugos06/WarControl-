# Windows 11 Setup

## Etat valide

- Node.js LTS et npm sont installes sur cette machine.
- Le dashboard web build correctement.
- Le collector gere mieux les chemins Windows 11.
- L'API a ses dependances Python installees dans `api/.venv`.

## 1. Ouvrir un nouveau terminal

Apres l'installation de Node.js, ouvre un nouveau terminal PowerShell pour que `node` et `npm` soient dans le `PATH`.

## 2. Lancer l'API

Depuis la racine du repo :

```powershell
cd api
.venv\Scripts\Activate.ps1
$env:WARCONTROL_INGEST_KEY="change-me"
uvicorn api.main:app --reload
```

API attendue sur `http://127.0.0.1:8000`.

## 3. Lancer le dashboard

Dans un second terminal :

```powershell
cd web
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
npm run dev
```

Dashboard attendu sur `http://127.0.0.1:3000`.

## 4. Lancer le collector

Dans un troisieme terminal :

```powershell
cd collector
python agent.py --edition auto --api-url http://127.0.0.1:8000 --api-key change-me --server NationGlory --source TonPseudo
```

Si l'auto-detection rate :

```powershell
python agent.py --edition java --log-path "$env:USERPROFILE\.minecraft\logs\latest.log" --api-url http://127.0.0.1:8000 --api-key change-me --server NationGlory --source TonPseudo
```

```powershell
python agent.py --edition bedrock --log-path "$env:APPDATA\Minecraft Bedrock\logs\latest.log" --api-url http://127.0.0.1:8000 --api-key change-me --server NationGlory --source TonPseudo
```

## 5. Verifications rapides

- API health : `http://127.0.0.1:8000/health`
- Events : `http://127.0.0.1:8000/events`
- Stats : `http://127.0.0.1:8000/stats`
- Dashboard : `http://127.0.0.1:3000`

## 6. Notes utiles

- Le spool offline du collector est dans `%APPDATA%\WarControl\outbox.jsonl`.
- La base SQLite est creee par defaut dans `%APPDATA%\WarControl\warcontrol.db` sur Windows.
- Si PowerShell ne trouve pas `npm`, ferme et rouvre le terminal.

## 7. Lanceur commission

Depuis la racine du repo, tu peux lancer tout le systeme en arriere-plan avec :

```powershell
.\start-warcontrol.bat
```

Configuration cliente en une fois :

```powershell
.\configure-warcontrol.bat
```

Le lanceur cree automatiquement une cle interne locale pour faire communiquer l'API et le collector. Le client n'a pas besoin de renseigner cette cle a la main.

Launcher desktop simple :

```powershell
.\launch-warcontrol-ui.bat
```

Le launcher desktop permet de :

- sauvegarder la configuration locale
- demarrer WarControl
- arreter WarControl
- ouvrir le dashboard
- lancer Minecraft

Pour tout arreter :

```powershell
.\stop-warcontrol.bat
```

Logs runtime :

- `runtime-logs\api.log`
- `runtime-logs\web.log`
- `runtime-logs\collector.log`
