# Algorithmes de Recherche de Combos - TagadAI

Ce document décrit les algorithmes de recherche de combos implémentés dans l'IA LeekWars.

> **Ce fichier a été réécrit le 2026-08-23** : la version précédente documentait une
> génération antérieure de l'IA (PTS, UnifiedMCTS, modes Hybrid/HybridGuided/HybridBeam)
> qui n'existe plus dans le code. Voir `AI/AI` et `AI/Algorithms/` pour l'état réel.

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Fait architectural clé : pas de lookahead](#fait-architectural-clé--pas-de-lookahead)
3. [ComboExplorer (mode par défaut)](#comboexplorer-mode-par-défaut)
4. [ActionKnapsack](#actionknapsack)
5. [ComboBuilder et Combo.add](#combobuilder-et-comboadd)
6. [MCTS](#mcts)
7. [BeamSearch](#beamsearch)
8. [Scoring et coefficients figés](#scoring-et-coefficients-figés)
9. [Changer de mode](#changer-de-mode)

---

## Vue d'ensemble

`AI.mode` (dans `AI/AI`) n'a que **trois** constantes :

| Mode | Constante | Fichier | Rôle |
|------|-----------|---------|------|
| Combo Explorer | `MODE_COMBO_EXPLORER = 9` | `AI/Algorithms/ComboExplorer` | Exploration multi-phase, **mode par défaut**, utilisé par `main` |
| MCTS | `MODE_MCTS = 1` | `AI/Algorithms/MCTS` | Arbre de recherche UCB1, existe toujours mais n'est pas le chemin actif |
| Beam Search | `MODE_BEAM = 2` | `AI/Algorithms/BeamSearch` | Faisceau de candidats, existe toujours mais n'est pas le chemin actif |

`tagadalive/main` fixe `AI.mode = AI.MODE_COMBO_EXPLORER`. Il n'existe plus de PTS, plus
d'UnifiedMCTS, et aucun mode hybride (`Hybrid` est un fichier présent dans
`AI/Algorithms/` mais aucune constante `MODE_HYBRID*` ne le sélectionne — vérifier son
statut réel avant de s'y fier, ce document n'a pas audité son contenu).

`AI/Algorithms/` contient aussi `ActionKnapsack`, `BulbGreedy` et `ComboBuilder`, qui ne
sont pas des modes sélectionnables via `AI.mode` mais des briques utilisées par
`ComboExplorer`.

---

## Fait architectural clé : pas de lookahead

**Aucun algorithme ne simule au-delà du tour courant.** Il n'y a pas de recherche
multi-tours, pas d'arbre de jeu qui projette le tour adverse, pas de rollout qui
regarde plusieurs tours en avant. Le "futur" est représenté uniquement à l'intérieur
de l'évaluation d'un combo à un seul tour, via :

- `turnsLeft` et les tables de `durationMitigation` (combien de tours un effet/buff
  compte vraiment avant la fin probable du combat),
- `getEffectiveDuration` (durée effective d'un effet, pondérée par ces tables),
- des modificateurs liés à l'ordre de jeu (qui joue avant qui),
- les cartes de danger/menace dans `Controlers/Maps/` : `MapDanger`, `MapCellScore`,
  `MapAction` (et les autres : `MapDamage`, `MapPath`, `MapPosition`, `MapSummon`,
  `MapSupport`, `MapTactical`).

C'est le fait le plus important pour comprendre l'architecture actuelle : la qualité
du jeu vient de la richesse de l'évaluation à un tour, pas d'une recherche en
profondeur sur plusieurs tours.

---

## ComboExplorer (mode par défaut)

**Fichier** : `AI/Algorithms/ComboExplorer`. Point d'entrée : `ComboExplorer.explore()`.

### Principe

Ce n'est ni un greedy single-pass ni un arbre de recherche : c'est un **ordonnancement
fixe de phases**, chacune explorant une famille de combos différente. Chaque phase
appelle `ctx.shouldStop()` avant de s'exécuter ; dès que le budget d'opérations restant
passe sous la réserve (`ExplorerConfig.OPERATION_BUFFER_*`), les phases suivantes sont
sautées. La phase 0 (Stay) tourne toujours en premier et garantit un résultat même si
tout le reste est coupé.

### Ordre réel des phases (lu dans `explore()`)

| Phase | Nom interne | Fonction | Description (lue dans le code) |
|-------|-------------|----------|----------------------------------|
| 0 | Stay | `phaseStay` | Reste sur place — base bon marché, 0 MP offensif, tourne toujours |
| SAFE | Safe | `phaseConstrainedEnd(..., "SAFE")` | Maximise les dégâts en forçant la position finale sur la cellule la plus sûre (`MapPosition.findBestPositionFromMap`) ; tourne toujours |
| T | Target Focus | `phaseTargetFocus` | Par ennemi non-bulbe vivant : énumération de préfixes (Libération × buffs Force × Neutrino × niveaux de MP) ; par allié pouvant mourir : 2 variantes de buff MP |
| I | Inversion | `phaseInversion` | Stratégies utilisant l'inversion (chip Inversion) |
| R | Repotting | `phaseRepotting` | Échange de position avec un bulbe allié (rempotage) |
| A | Attract | `phaseAttract` | Attraction simple (grappin seul) |
| P | Push | `phasePush` | Poussée simple (gant de boxe seul) |
| AP | Attract-Push | `phaseAttractPush` | Combos attraction + poussée (grappin + gant de boxe) |
| PIP | Pull-Inversion-Push | `phasePullInvPush` | Combos tirer-inverser-pousser (grappin + inversion + gant de boxe) |
| 1 | Single-cell | `phaseSingleCell` | Échantillonnage MP sur une seule cellule (1a : portée courante sans buff, 1b : portée étendue avec buffs MP minimaux, 1c : cellules atteignables via saut/téléportation) |
| 2 | Multi-cell pairs | `phaseMultiCell` | Paires de cellules parmi les top-K les plus intéressantes (`INTERESTING_CELLS_K_PHASE2 = 15`), les deux ordres, buffs MP minimaux si nécessaire |
| 3 | Three-cell | `phaseThreeCell` | Triplets de cellules parmi les top-K (`INTERESTING_CELLS_K_PHASE3 = 10`), les 6 ordres |

Chaque phase (sauf 0 et SAFE) est précédée d'un `if (!ctx.shouldStop())` : la troncature
se fait donc dans cet ordre exact, du début vers la fin de la liste ci-dessus — un combat
avec peu d'opérations disponibles peut ne jamais atteindre les phases 2/3.

`phaseConstrainedEnd` est la fonction générique derrière la phase SAFE (forcer la
position de fin de tour sur une cellule cible donnée) ; le commentaire de code
l'appelle en interne "PHASE OTK ESCAPE" mais elle n'est utilisée dans `explore()` que
pour construire la phase SAFE — ce n'est pas une phase distincte de l'ordonnancement.

### Sélection et exécution

- **Sélection des actions** : par knapsack (`ActionKnapsack`), pour une allocation
  optimale du budget TP.
- **Ordre d'exécution** : par priorité (indépendant de l'ordre de sélection).
- **Fallback greedy** : après un kill, remplit le TP restant.
- **Chaînage des conséquences** : chaque action est évaluée avec l'état résultant des
  actions précédentes (buffs, HP, position).
- **Buffs MP** : empilés au minimum nécessaire pour atteindre une cellule étendue.

---

## ActionKnapsack

**Fichier** : `AI/Algorithms/ActionKnapsack`.

Résout un **sac à dos borné (bounded knapsack)** pour choisir, parmi un pool d'actions
disponibles, le sous-ensemble qui maximise la somme des scores sous une contrainte de
TP (`maxTP`). Gère :

- les coûts de changement d'arme (le coût de base d'une action dépend de l'arme
  actuellement en main, via `weaponIdx` sur chaque `KnapsackItem`),
- les limites d'usage par item (`maxUse`),
- une sélection par programmation dynamique plutôt que gloutonne.

C'est un outil utilisé par `ComboExplorer` (via `ComboBuilder`) pour une meilleure
allocation du TP qu'une simple sélection gloutonne par score décroissant.

---

## ComboBuilder et Combo.add

**Fichier** : `AI/Algorithms/ComboBuilder`. Centralise la construction de combo pour
éviter la duplication entre les phases de `ComboExplorer` : sélection knapsack, tri par
priorité, fallback greedy, calcul de la position finale. Expose des méthodes
spécialisées (`buildAtCell`, `buildAtCellBuffed`, `buildForTargetPrefixed`,
`buildForAlly`, `buildAcrossCells`, …) toutes paramétrées par un `ExplorationContext`
(ressources initiales, cartes d'atteignabilité, cellules à ignorer).

La construction elle-même passe par `Combo.add(action)` (`Model/Combos/Combo`) :

```leekscript
boolean add(Action action) {
    // rejette si le nombre d'usages de l'item dépasse maxUse
    // sinon : actualise l'action avec les conséquences courantes du combo
    // n'ajoute que si le score cumulé actualisé dépasse le score cumulé précédent
}
```

Autrement dit, **`Combo.add` est une porte sur l'amélioration du score cumulé** :
une action n'est retenue que si elle fait strictement progresser le score total du
combo par rapport à l'état actuel (`actualized.score! > prevScore`), pas seulement si
elle a un score positif en isolation.

---

## MCTS

**Fichier** : `AI/Algorithms/MCTS`. Toujours présent, sélectionnable via
`AI.MODE_MCTS`, mais **pas le mode par défaut**.

Arbre de recherche classique avec sélection UCB1 :

```leekscript
static final real EXPLORATION_CONSTANT = 1.414  // sqrt(2)
```

```leekscript
real getUCBScore(real explorationConstant) {
    if (this.visits == 0) return 999999.0
    real exploitation = this.totalValue / this.visits
    real exploration = explorationConstant * sqrt(log(this.parent!.visits as real) / this.visits)
    return exploitation + exploration
}
```

**Point important** : `totalValue` accumule des scores de combo bruts, qui sont
couramment de l'ordre de plusieurs milliers (kills, dégâts, buffs). Le terme
d'exploitation (`totalValue / visits`) est donc lui-même de cet ordre de grandeur,
alors que le terme d'exploration (`1.414 × sqrt(ln(visits_parent)/visits)`) reste
petit (grandeur unitaire à quelques dizaines dans les régimes usuels de `visits`).
En pratique, le terme d'exploitation domine presque toujours la sélection : **cette
implémentation de MCTS est donc effectivement gloutonne**, ce qui explique pourquoi
elle n'est pas le chemin porteur de l'IA (`ComboExplorer` a pris ce rôle).

---

## BeamSearch

**Fichier** : `AI/Algorithms/BeamSearch`. Toujours présent, sélectionnable via
`AI.MODE_BEAM`, pas le mode par défaut.

Maintient un faisceau de largeur fixe des meilleures séquences partielles :

1. À chaque profondeur, étend chaque état du faisceau avec toutes les actions
   valides, note les candidats par score d'action seul.
2. Garde les `BEAM_WIDTH` meilleurs candidats.
3. La position finale n'est évaluée qu'à la fin, sur les candidats survivants du
   faisceau final (`totalScore = actionScore + positionScore`) — pas à chaque niveau
   intermédiaire, pour rester bon marché en opérations.

Pas de structure arborescente (mémoire linéaire en `beam_width × depth`), pas de
rollout, pas d'UCB1 — sélection purement gloutonne du top-K à chaque niveau.

---

## Scoring et coefficients figés

**Fichier** : `HiddenKnowledges/ScoringConfig`, `HiddenKnowledges/Scoring`.

```leekscript
static boolean DYNAMIC_COEFS = false   // valeur par défaut
```

Avec `DYNAMIC_COEFS = false` (le défaut) :

- `Scoring.refresh()` précalcule et **fige** les coefficients dynamiques par
  (entité, stat) **en début de tour**, dans `_cache_dynamic_coef`.
- `Scoring.getDynamicCoef()` fait alors une pure lecture de cache pendant toute
  l'exploration de `ComboExplorer` — les modificateurs (`ScoringModifiers`) voient
  donc l'état du champ de bataille **au début du tour**, pas l'état simulé au fil
  du combo (HP après dégâts, morts en cours de combo, etc.).
- Si `DYNAMIC_COEFS = true`, `getDynamicCoef()` recalcule tout dynamiquement à
  partir du HP simulé dans les conséquences courantes — mais ce n'est pas le
  réglage actif par défaut.

Ce détail renforce le point de la section précédente : la "connaissance du futur"
de l'IA est essentiellement figée en début de tour, sauf le peu que
`ComboExplorer`/`Combo`/`Consequences` recalculent explicitement pendant la
construction d'un combo (chaînage de conséquences, kills, buffs).

---

## Changer de mode

Dans `tagadalive/main` :

```leekscript
// ╔═════════════════════════════════════════════════════════════════════╗
// ║                      ALGORITHM CONFIGURATION                        ║
// ╠═════════════════════════════════════════════════════════════════════╣
// ║  MODE_MCTS             Full tree search                             ║
// ║  MODE_BEAM             Multi-path beam search                       ║
// ║  MODE_COMBO_EXPLORER   Multi-phase exploration [DEFAULT]            ║
// ╚═════════════════════════════════════════════════════════════════════╝
AI.mode = AI.MODE_COMBO_EXPLORER
```

Après modification, uploader `main` :

```bash
python -m src.tools.aisync put main tagadalive/main
```
