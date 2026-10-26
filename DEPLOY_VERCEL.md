# Déployer sur Vercel

Ce ZIP contient le code complet, avec le premier thème vert foncé, une connexion administrateur unique, un import Excel OFPPT et la saisie manuelle des absences.

## 1. Préparer le projet

Décompresser le ZIP. Placer son contenu dans un dépôt GitHub (fichier `index.py` à la racine), puis importer ce dépôt dans Vercel. Choisir le preset **FastAPI** ou laisser la détection automatique. Ne pas choisir un export statique ni GitHub Pages. Aucun build JavaScript n’est nécessaire.

Autre possibilité : installer le CLI officiel `npm install -g vercel`, ouvrir un terminal dans le dossier et utiliser `vercel`, puis `vercel --prod` après configuration.

## 2. Connecter une base PostgreSQL

Dans Vercel → Storage / Marketplace, connecter un fournisseur PostgreSQL tel que Neon, ou utiliser votre base PostgreSQL existante. Le serveur doit disposer de sa chaîne de connexion dans `DATABASE_URL` (utiliser la connexion poolée recommandée par votre fournisseur, avec TLS).

SQLite est réservé au développement local. Le programme refuse de l’utiliser sur Vercel : les données doivent être persistantes et partagées entre les instances.

## 3. Configurer les variables serveur

Dans Vercel → Project → Settings → Environment Variables, définir :

| Variable | Valeur |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL privée avec TLS, fournie par votre base |
| `ADMIN_USERNAME` | Votre identifiant administrateur |
| `ADMIN_PASSWORD` | Un mot de passe unique d’au moins 12 caractères |
| `COOKIE_SECURE` | `true` |

Ne pas utiliser le préfixe `NEXT_PUBLIC_`. Ne jamais publier `.env` ou les identifiants dans GitHub. `.env.example` montre uniquement le format. Redéployer après modification de ces variables.

Les tables et le compte sont initialisés au premier accès à l’API. Le compte est créé uniquement si aucun compte n’existe. Changer `ADMIN_PASSWORD` après cela ne change pas le mot de passe stocké : utiliser `python -m app.manage` depuis un environnement privé connecté à la même `DATABASE_URL` pour le réinitialiser. Cette commande révoque les sessions actives.

Pour tester un déploiement preview, utiliser une base de test distincte et un compte de test. Ne pas réutiliser les données réelles en preview.

## 4. Importer le fichier de l’établissement

Après connexion : **Importer Excel** → choisir `bd stagiaire 2026-2027.xls` → feuille `Export`.

Association reconnue automatiquement :

| Colonne du fichier | Champ |
| --- | --- |
| `MatriculeEtudiant` | Matricule unique |
| `Nom` | Nom |
| `Prenom` | Prénom |
| `groupe` | Groupe |
| `Site` | Site |

Ce fichier `.xls` est un export **XML Spreadsheet 2003** : il est pris en charge sans conversion. Les `.xlsx` sont également acceptés. Les anciens `.xls` binaires doivent être réenregistrés en `.xlsx`. Limite : 4 Mo par fichier, environ 10 000 lignes, 100 colonnes.

Vérifier l’aperçu, puis confirmer l’import. Les doublons dans le fichier bloquent l’import ; les matricules déjà en base sont ignorés sans écrasement. Le fichier Excel réel n’est pas inclus dans ce ZIP ni préchargé dans le site : l’import authentifié conserve les données dans PostgreSQL. Les absences sont ensuite ajoutées manuellement.

## 5. Vérifier et sauvegarder

- Vérifier la connexion et l’import, puis créer une absence et recharger la page.
- Vérifier les statuts, les filtres par semaine et l’export CSV.
- Prévoir des sauvegardes PostgreSQL auprès du fournisseur. Un CSV n’est pas une sauvegarde complète.

L’application utilise FastAPI sur Vercel, sans Docker ni VM à administrer pour cet hébergement. Les fichiers Docker restent disponibles pour un hébergement sur VM.

Le code est prêt à configurer ; ce ZIP n’est pas un déploiement réalisé. Une connexion PostgreSQL réelle et le déploiement Vercel restent à valider dans votre compte.
