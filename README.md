# Assiduité — OFPPT

Application de suivi hebdomadaire des absences : thème vert foncé et fond clair, compte administrateur unique, répertoire par matricule, nom, prénom, groupe et site ; import Excel puis saisie manuelle des absences justifiées ou non, recherche et export CSV.

**Pour Vercel : lire [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md).**

## Développement local

Python 3.12 :

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell : .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.manage
COOKIE_SECURE=false uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sous PowerShell, utiliser `$env:COOKIE_SECURE="false"` puis lancer uvicorn sans le préfixe. `COOKIE_SECURE=false` est réservé au test HTTP local.

Sans `DATABASE_URL`, SQLite est utilisé dans `data/absence.sqlite3`, uniquement hors Vercel. Avec `DATABASE_URL`, les données sont enregistrées dans PostgreSQL. Les tables sont créées au premier accès. Le mot de passe est haché avec scrypt ; les cookies sont HttpOnly, SameSite et Secure par défaut ; la session expire après 8 h.

Un stagiaire supprimé entraîne la suppression de ses absences après confirmation. Une ligne représente une absence hebdomadaire ; plusieurs lignes sont possibles pour une même personne et semaine. Le format XML `.xls` de l’export interne et les `.xlsx` sont acceptés. Les matricules sont du texte converti en majuscules. Aucun fichier réel ni secret n’est livré dans le code.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
node --check app/static/app.js
```

Les tests couvrent le flux sur SQLite, la connexion, l’expiration, la limitation des essais, le CRUD, les imports xlsx/XML, les doublons et les requêtes PostgreSQL adaptées. Le fonctionnement sur une base PostgreSQL réelle et le déploiement Vercel doivent être vérifiés sur l’infrastructure cible.

## Docker / VM

Les fichiers Docker et Compose sont conservés pour un déploiement sur une VM Linux, y compris sous VMware. `docker compose run --rm app python -m app.manage` configure le compte ; `docker compose up -d --build` démarre l’application. Un proxy HTTPS est requis pour l’accès réseau avec les cookies sécurisés. Ne pas détruire le volume de données ; prévoir une sauvegarde privée de la base. Ne pas utiliser cette configuration Docker sur Vercel.

## Licence et données

Code MIT. Application indépendante, sans logo officiel intégré ; aucun droit sur les marques OFPPT n’est accordé. Ne publier aucun Excel interne, base ou sauvegarde dans GitHub. Les versions statiques de démonstration antérieures ne font pas partie de ce paquet.
