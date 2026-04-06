# 🎾 Tennis Value Bet Bot

Bot Telegram qui scanne les matchs ATP/WTA et détecte les **value bets** en comparant les cotes du marché à des probabilités estimées via un modèle multi-facteurs.

---

## 🚀 Installation rapide

### 1. Cloner et installer

```bash
git clone <ton-repo>
cd tennis_valuebet_bot
pip install -r requirements.txt
```

### 2. Configurer les clés API

```bash
cp .env.example .env
# Puis éditer .env avec tes clés
```

| Variable | Source | Plan gratuit |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) sur Telegram | ✅ Gratuit |
| `ODDS_API_KEY` | [the-odds-api.com](https://the-odds-api.com) | ✅ 500 req/mois |
| `APISPORTS_KEY` | [rapidapi.com/api-sports](https://rapidapi.com/api-sports/api/api-tennis) | ✅ 100 req/jour |

### 3. Configurer les alertes automatiques

Dans `config.py`, ajoute ton chat Telegram ID dans `ALLOWED_CHAT_IDS` :

```python
ALLOWED_CHAT_IDS = [123456789]  # Ton chat ID
```

> 💡 Pour trouver ton chat ID : envoie `/start` à [@userinfobot](https://t.me/userinfobot)

### 4. Lancer le bot

```bash
python bot.py
```

---

## 📱 Commandes Telegram

| Commande | Description |
|---|---|
| `/start` | Menu principal avec boutons |
| `/scan` | Scan immédiat de tous les matchs |
| `/matches` | Liste des matchs à venir avec cotes |
| `/status` | Configuration actuelle |
| `/help` | Aide |

---

## 🧮 Modèle de calcul

### Probabilité estimée (P_est)

Combinaison pondérée de 5 facteurs :

| Facteur | Poids | Source |
|---|---|---|
| Ranking ATP/WTA | 30% | API-Sports (points officiels) |
| Forme récente | 25% | Résultats des 5 derniers matchs |
| Surface | 20% | Win rate historique par surface |
| H2H | 15% | Confrontations directes |
| Fatigue | 10% | Matchs joués récemment |

### Calcul de l'edge

```
Edge = (P_est × cote) − 1
```

Un edge positif signifie que la cote offerte est supérieure à la valeur réelle du pari.

**Exemple :** P_est = 55%, cote = 2.20
→ Edge = (0.55 × 2.20) − 1 = **+21%** ✅

### Mise recommandée (Kelly)

```
f = (P_est × cote − 1) / (cote − 1)
Mise = f × Kelly_fraction × Bankroll
```

Le quart de Kelly (25%) est utilisé par défaut pour réduire la variance.

---

## ⚙️ Paramètres ajustables (`.env`)

| Paramètre | Défaut | Description |
|---|---|---|
| `MIN_EDGE` | `0.05` | Edge minimum pour alerter (5%) |
| `KELLY_FRACTION` | `0.25` | Fraction Kelly appliquée |
| `BANKROLL` | `1000` | Bankroll de référence en € |
| `SCAN_INTERVAL` | `30` | Minutes entre deux scans |

---

## 📁 Structure du projet

```
tennis_valuebet_bot/
├── bot.py            # Point d'entrée
├── config.py         # Configuration centrale
├── data_fetcher.py   # Récupération cotes (The Odds API) + stats (API-Sports)
├── analyzer.py       # Modèle de calcul + détection value bets
├── formatter.py      # Formatage messages Telegram
├── handlers.py       # Handlers des commandes
├── scheduler.py      # Scan automatique périodique
├── requirements.txt
├── .env.example
└── data/
    └── sent_valuebets.json   # Déduplification des alertes
```

---

## ⚠️ Avertissements

- Ce bot est un **outil d'aide à la décision**, pas un oracle.
- Les probabilités estimées sont imparfaites — le modèle s'améliore avec le temps.
- **Ne joue jamais plus que tu ne peux te permettre de perdre.**
- Respecte les lois sur les jeux d'argent de ton pays.

---

## 🔧 Améliorations possibles

- [ ] Backtesting sur données historiques (Tennis Abstract)
- [ ] Modèle Elo personnalisé par surface
- [ ] Base de données SQLite pour tracker les performances
- [ ] Dashboard web (FastAPI + Chart.js)
- [ ] Filtrage par tournoi via commande Telegram
- [ ] Support des paris en sets (handicap)
