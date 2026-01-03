# Algorithmes de Recherche de Combos - TagadAI

Ce document décrit en détail les algorithmes de recherche de combos implémentés dans l'IA LeekWars.

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture commune](#architecture-commune)
3. [Algorithmes de base](#algorithmes-de-base)
   - [PTS - Priority Target Simulation](#pts---priority-target-simulation)
   - [MCTS - Monte Carlo Tree Search](#mcts---monte-carlo-tree-search)
   - [BeamSearch - Recherche en faisceau](#beamsearch---recherche-en-faisceau)
4. [Modes hybrides](#modes-hybrides)
   - [HYBRID](#hybrid)
   - [HYBRID_GUIDED](#hybrid_guided)
   - [HYBRID_BEAM](#hybrid_beam)
5. [Comparaison détaillée](#comparaison-détaillée)
6. [Guide de choix](#guide-de-choix)
7. [Exemples concrets](#exemples-concrets)
8. [Tuning et configuration](#tuning-et-configuration)

---

## Vue d'ensemble

L'IA dispose de **6 modes** de recherche de combos, configurables via `AI.mode` :

| Mode | Constante | Description courte |
|------|-----------|-------------------|
| PTS | `MODE_PTS = 0` | Greedy target-first, très rapide |
| MCTS | `MODE_MCTS = 1` | Arbre de recherche avec UCB1 |
| BEAM | `MODE_BEAM = 2` | Faisceau de candidats, multi-path |
| HYBRID | `MODE_HYBRID = 3` | PTS seed → MCTS sur 1 cellule |
| HYBRID_GUIDED | `MODE_HYBRID_GUIDED = 4` | PTS guide l'ordre des cellules MCTS |
| HYBRID_BEAM | `MODE_HYBRID_BEAM = 5` | PTS guide l'ordre des cellules Beam |

**Mode par défaut** : `HYBRID_GUIDED` (meilleur compromis qualité/performance)

---

## Architecture commune

Tous les algorithmes partagent la même infrastructure :

### Structures de données

```
Combo
├── actions: Array<Action>      // Séquence d'actions ordonnées
├── finalPosition: Position     // Position de fin de tour
└── score: real                 // Score total (actions + position)

Action
├── item: Item                  // Arme ou chip utilisé
├── from: Cell                  // Cellule d'attaque (ou Fight.selfCell pour self-cast)
├── to: Cell                    // Cellule cible
├── consequences: Consequences  // État après l'action
└── score: real                 // Score de cette action

Consequences
├── currentCell: Cell           // Position après action
├── currentTP/MP: integer       // Ressources restantes
├── _alterations: Map           // Buffs/debuffs appliqués
├── _killed: Map                // Entités tuées
└── score: real                 // Score cumulé des effets
```

### Flux d'exécution commun

```
1. MapAction.getMapBestAction()     // Pré-calcul des meilleures actions par (cell, item)
2. Pour chaque cellule atteignable :
   │
   ├── Récupérer les actions disponibles
   ├── Fusionner les actions self-cast
   ├── [ALGORITHME SPÉCIFIQUE]      // PTS, MCTS, ou BeamSearch
   └── Garder le meilleur combo
   │
3. Ajouter la position finale (MapPosition.findBestPosition)
4. Retourner le combo avec le meilleur score
```

### Chaînage des conséquences

Le **chaînage des conséquences** est crucial : chaque action est évaluée en tenant compte de l'état résultant des actions précédentes.

```
Action 1 (buff STR +100)
    ↓ consequences: STR augmentée
Action 2 (attaque)
    ↓ bénéficie du buff → dégâts augmentés → meilleur score
```

Sans chaînage, l'action 2 serait évaluée sans le buff, donnant un score incorrect.

---

## Algorithmes de base

### PTS - Priority Target Simulation

**Fichier** : `AI/PTS`

#### Principe

PTS itère **cible par cible** au lieu de cellule par cellule. Pour chaque paire (cible, item), il génère une "Opportunity" avec toutes les cellules d'attaque valides.

#### Algorithme

```
1. GÉNÉRATION DES OPPORTUNITÉS
   Pour chaque item (non en cooldown) :
     Pour chaque cible (ennemis, alliés, soi) :
       Si cible invincible et ennemie : skip
       Calculer les cellules d'attaque valides
       Créer Opportunity(cible, item, cellules, baseScore)

2. TRI
   - Self-cast en premier (buffs/heals prioritaires)
   - Puis par score décroissant

3. CONSTRUCTION GREEDY
   Pour chaque opportunité triée :
     Si exécutable (TP, CD, cible vivante, cellule atteignable) :
       Créer action chaînée
       Si score > 0 : ajouter au combo
       Mettre à jour état (TP, MP, position, usages)

4. POSITIONNEMENT FINAL
   Trouver meilleure position de fin de tour
```

#### Complexité

- **Temps** : O(items × cibles) pour la génération, O(opportunités) pour la construction
- **Espace** : O(opportunités) - pas de structure arborescente

#### Avantages

| Avantage | Explication |
|----------|-------------|
| **Très rapide** | Single-pass greedy, pas d'exploration |
| **Faible consommation ops** | ~50k-100k ops typiquement |
| **Prévisible** | Déterministe, même résultat à chaque fois |
| **Scale avec cibles** | O(cibles) au lieu de O(cellules) |

#### Inconvénients

| Inconvénient | Explication |
|--------------|-------------|
| **Myope** | Choisit le meilleur local, peut rater des synergies |
| **Ordre figé** | L'ordre de tri détermine tout |
| **Pas d'exploration** | Ne teste pas d'ordres alternatifs |

#### Exemple

```
Opportunités générées :
  1. Cure sur soi (score: 500)      ← self-cast, prioritaire
  2. Laser sur Ennemi1 (score: 450)
  3. Pistol sur Ennemi2 (score: 300)
  4. Shield sur soi (score: 200)    ← self-cast, prioritaire

Après tri :
  1. Cure (self-cast)
  2. Shield (self-cast)
  3. Laser
  4. Pistol

Construction :
  - Cure → OK, ajouté (TP: 10→7)
  - Shield → OK, ajouté (TP: 7→5)
  - Laser → OK, ajouté (TP: 5→2)
  - Pistol → Pas assez de TP, skip

Combo final : Cure → Shield → Laser → Move(cell:245)
```

---

### MCTS - Monte Carlo Tree Search

**Fichier** : `AI/MCTS`

#### Principe

MCTS construit un arbre de recherche où chaque nœud représente un état après une séquence d'actions. L'algorithme **UCB1** équilibre exploration (essayer de nouvelles actions) et exploitation (approfondir les meilleures).

#### Algorithme

```
1. INITIALISATION
   Créer nœud racine (état initial)
   Pré-calculer actions prunées (top-K par score)

2. BOUCLE MCTS (max 150 itérations)

   a. SÉLECTION (UCB1)
      Descendre dans l'arbre en choisissant le fils avec meilleur UCB:
      UCB = moyenne + C × √(ln(parent.visits) / visits)
      où C = 1.414 (√2)

   b. EXPANSION
      Si nœud pas terminal et pas fully expanded :
        Ajouter un fils avec une action non essayée

   c. SIMULATION (Rollout)
      Depuis le nouveau nœud, jouer greedy jusqu'à 3 actions
      Calculer score total (actions + danger position finale)

   d. BACKPROPAGATION
      Remonter le score jusqu'à la racine
      Incrémenter visits et totalValue de chaque nœud

3. EXTRACTION
   Suivre le chemin des fils les plus visités
   Construire le combo correspondant
```

#### Structure MCTSNode

```
MCTSNode
├── parent: MCTSNode?
├── children: Array<MCTSNode>
├── action: Action?              // Action qui a mené à ce nœud
├── state: Consequences          // État du jeu à ce nœud
├── remainingTP/MP: integer
├── weaponInHand: Item?
├── visits: integer              // Nombre de visites
├── totalValue: real             // Somme des scores des simulations
├── untriedActions: Array<Action>
└── isTerminal: boolean
```

#### Formule UCB1

```
UCB(nœud) = exploitation + exploration
          = (totalValue / visits) + C × √(ln(parent.visits) / visits)

- exploitation : score moyen observé
- exploration : bonus pour les nœuds peu visités
- C = 1.414 : constante d'exploration (√2, standard)
```

#### Complexité

- **Temps** : O(iterations × profondeur_arbre × actions)
- **Espace** : O(nœuds_créés) - structure arborescente

#### Avantages

| Avantage | Explication |
|----------|-------------|
| **Exploration intelligente** | UCB1 balance exploration/exploitation |
| **Trouve des synergies** | Peut découvrir des ordres non-évidents |
| **Anytime** | Plus d'itérations = meilleur résultat |
| **Rollouts** | Évalue les actions en contexte futur |

#### Inconvénients

| Inconvénient | Explication |
|--------------|-------------|
| **Coût élevé** | ~200k-400k ops typiquement |
| **Structure arbre** | Mémoire et overhead de création de nœuds |
| **Rollouts stochastiques** | Variance dans l'évaluation |
| **Paramètres sensibles** | C, MAX_ITERATIONS à tuner |

#### Exemple

```
Arbre après 50 itérations :

                    [Racine]
                   visits: 50
                  /    |    \
            [Cure]  [Laser] [Shield]
            v:25    v:15     v:10
           /   \      |
     [Laser] [Pistol] [Cure]
       v:18    v:7     v:15

Meilleur chemin (par visits) : Racine → Cure (25) → Laser (18)

Note: Cure puis Laser a été exploré plus que Laser seul
      car le buff de Cure améliore les simulations suivantes
```

---

### BeamSearch - Recherche en faisceau

**Fichier** : `AI/BeamSearch`

#### Principe

BeamSearch maintient un **faisceau** (beam) de K meilleures séquences partielles à chaque niveau de profondeur. À chaque niveau, on étend tous les candidats avec toutes les actions valides, puis on garde les K meilleurs.

#### Algorithme

```
1. INITIALISATION
   beam = [état_initial]  // Un seul candidat au départ
   Pré-calculer actions prunées

2. BOUCLE (max 6 niveaux de profondeur)

   candidates = []

   Pour chaque état dans beam :
     Pour chaque action pruned valide :
       Si action exécutable (TP, CD, cible vivante) :
         nouvel_état = étendre(état, action)
         Si score action > 0 :
           ajouter nouvel_état à candidates

   Si candidates vide : break

   Trier candidates par score décroissant
   beam = top-K(candidates)  // Garder les K meilleurs

3. EXTRACTION
   Meilleur combo = beam[0]  // Premier = meilleur score
   Ajouter position finale
```

#### Structure BeamState

```
BeamState
├── actions: Array<Action>       // Séquence construite
├── state: Consequences          // État courant
├── remainingTP/MP: integer
├── weaponInHand: Item?
├── usageCounts: Map<Item, int>  // Utilisations par item
├── score: real                  // Score cumulé
└── startCell: Cell
```

#### Complexité

- **Temps** : O(BEAM_WIDTH × MAX_DEPTH × actions)
- **Espace** : O(BEAM_WIDTH × MAX_DEPTH) - linéaire, pas d'arbre

#### Configuration

```
BEAM_WIDTH = 15        // Candidats gardés par niveau
MAX_DEPTH = 6          // Profondeur max (nombre d'actions)
MAX_ACTIONS_TO_TRY = 8 // Pruning des actions
```

#### Avantages

| Avantage | Explication |
|----------|-------------|
| **Multi-path** | Explore plusieurs séquences en parallèle |
| **Pas de rollout** | Évaluation directe, pas de simulation |
| **Mémoire bornée** | O(beam_width), pas d'arbre |
| **Déterministe** | Résultat reproductible |
| **Bon compromis** | Entre PTS (trop greedy) et MCTS (trop coûteux) |

#### Inconvénients

| Inconvénient | Explication |
|--------------|-------------|
| **Beam fini** | Peut perdre des bonnes séquences au pruning |
| **Pas d'exploration UCB** | Pas de balance exploration/exploitation |
| **Sensible au width** | Trop petit = myope, trop grand = lent |

#### Exemple

```
Depth 0: beam = [∅]

Depth 1: étendre avec toutes les actions
  candidates = [Cure(500), Laser(450), Shield(200), Pistol(300)]
  beam (top-3) = [Cure(500), Laser(450), Pistol(300)]

Depth 2: étendre chaque candidat
  Cure → [Cure+Laser(900), Cure+Shield(700), Cure+Pistol(750)]
  Laser → [Laser+Pistol(700), Laser+Shield(600)]
  Pistol → [Pistol+Laser(680)]

  Tous candidats triés :
    [Cure+Laser(900), Cure+Pistol(750), Cure+Shield(700), ...]

  beam (top-3) = [Cure+Laser(900), Cure+Pistol(750), Cure+Shield(700)]

Depth 3: continuer...

Résultat final : Cure → Laser → ... (meilleur score cumulé)
```

---

## Modes hybrides

Les modes hybrides combinent PTS avec un autre algorithme pour bénéficier des avantages des deux.

### HYBRID

**Principe** : PTS d'abord, puis MCTS **uniquement sur la cellule choisie par PTS**.

```
1. Exécuter PTS → ptsCombo, ptsScore
2. Extraire la cellule de départ du combo PTS
3. Exécuter MCTS depuis cette cellule → mctsCombo, mctsScore
4. Retourner le meilleur des deux
```

**Schéma** :
```
PTS ──→ cellule 245 ──→ MCTS(245) ──→ meilleur(PTS, MCTS)
                            │
                            └── (ignore les autres cellules)
```

**Avantages** :
- Plus rapide que MCTS complet (1 cellule au lieu de toutes)
- PTS guide vers une bonne cellule

**Inconvénients** :
- MCTS limité à une seule position
- Peut rater des combos depuis d'autres cellules

### HYBRID_GUIDED

**Principe** : PTS d'abord, puis MCTS sur **toutes les cellules ordonnées par score PTS**.

```
1. Exécuter PTS → ptsCombo, ptsScore
   (PTS remplit aussi PTS.lastCellScores : Map<Cell, score>)

2. Trier les cellules par score PTS décroissant

3. Pour chaque cellule (dans l'ordre de priorité) :
   - Si budget épuisé : break
   - Exécuter MCTS depuis cette cellule
   - Garder le meilleur combo

4. Retourner max(ptsCombo, mctsCombo)
```

**Schéma** :
```
PTS ──→ scores par cellule ──→ MCTS(245) ──→ MCTS(301) ──→ MCTS(189)...
            │                      │             │             │
            │                      └─────────────┴─────────────┘
            │                           ordre de priorité PTS
            └── 245: 800
                301: 750
                189: 600
```

**Exemple concret** :
```
1. PTS trouve un combo score 800 depuis cellule 245
2. MCTS explore dans l'ordre PTS :
   - Cellule 245 → score 850
   - Cellule 301 → score 920  ← Meilleur !
   - Cellule 189 → (budget épuisé, skip)
3. Retourne MCTS(301) avec score 920
```

**Avantages** :
- Vrai MCTS complet (toutes les cellules)
- Dégradation intelligente : si budget serré, meilleures cellules explorées d'abord
- Ne peut jamais faire pire que PTS seul
- Peut trouver un meilleur combo depuis une cellule différente de celle de PTS

**Inconvénients** :
- Plus lent que HYBRID simple
- Peut timeout sur les dernières cellules

### HYBRID_BEAM

**Principe** : Comme HYBRID_GUIDED mais avec BeamSearch au lieu de MCTS.

```
1. Exécuter PTS → ptsCombo, ptsScore

2. Trier les cellules par score PTS décroissant

3. Pour chaque cellule (dans l'ordre de priorité) :
   - Si budget épuisé : break
   - Exécuter BeamSearch depuis cette cellule
   - Garder le meilleur combo

4. Retourner max(ptsCombo, beamCombo)
```

**Avantages** :
- BeamSearch moins coûteux que MCTS
- Peut explorer plus de cellules dans le budget
- Bonne alternative si MCTS timeout

---

## Comparaison détaillée

### Tableau comparatif

| Critère | PTS | MCTS | BeamSearch |
|---------|-----|------|------------|
| **Complexité temps** | O(targets × items) | O(iter × depth × actions) | O(beam × depth × actions) |
| **Ops typiques** | 50k-100k | 200k-400k | 100k-200k |
| **Qualité combo** | ★★★☆☆ | ★★★★★ | ★★★★☆ |
| **Exploration** | Aucune (greedy) | UCB1 (équilibrée) | Multi-path (limitée) |
| **Déterminisme** | Oui | Non (rollouts) | Oui |
| **Mémoire** | O(opportunities) | O(nodes) arbre | O(beam × depth) |
| **Trouve synergies** | Rarement | Souvent | Parfois |
| **Paramétrage** | Simple | Complexe (C, iter) | Moyen (width, depth) |

### Graphique conceptuel

```
Qualité
  ↑
  │                    ★ MCTS
  │                ★ BeamSearch
  │            ★ HYBRID_GUIDED
  │        ★ HYBRID_BEAM
  │    ★ PTS
  │
  └──────────────────────────→ Coût (ops)
       50k   100k   200k   300k
```

### Quand chaque algo brille

| Situation | Meilleur algo | Pourquoi |
|-----------|---------------|----------|
| Budget ops serré | PTS | Minimal ops, résultat décent |
| Beaucoup de buffs/synergies | MCTS | Exploration trouve les ordres optimaux |
| Équilibre qualité/perf | BeamSearch | Multi-path sans overhead arbre |
| Comparaison fiable | HYBRID_GUIDED | Teste vraiment PTS vs MCTS |
| Leek basse statistique | PTS | Moins d'actions possibles |
| Leek haute statistique | MCTS/Beam | Plus de combos intéressants |

---

## Guide de choix

### Arbre de décision

```
                    ┌─────────────────┐
                    │ Budget ops ?    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         < 150k ops    150k-300k ops    > 300k ops
              │              │              │
              ▼              ▼              ▼
           ┌─────┐      ┌────────┐      ┌──────┐
           │ PTS │      │ Beam/  │      │ MCTS │
           └─────┘      │ Hybrid │      └──────┘
                        └────────┘
```

### Recommandations par contexte

| Contexte | Mode recommandé | Justification |
|----------|-----------------|---------------|
| **Combat standard** | `HYBRID_GUIDED` | Meilleur compromis, ne rate jamais le meilleur |
| **Tests/Debug** | `PTS` | Rapide, reproductible |
| **Recherche qualité max** | `MODE_MCTS` | Exploration complète |
| **Leek level < 100** | `HYBRID_BEAM` | Moins d'actions, beam suffit |
| **Leek level > 300** | `HYBRID_GUIDED` | Beaucoup d'items, MCTS utile |
| **Farmer fight (multi-leek)** | `PTS` ou `HYBRID_BEAM` | Budget partagé entre leeks |

---

## Exemples concrets

### Exemple 1 : Combo simple (3 actions)

**Situation** : 10 TP, items = [Pistol(3TP), Laser(4TP), Cure(3TP)]

| Algo | Résultat | Explication |
|------|----------|-------------|
| PTS | Cure → Laser → stay | Self-cast first, puis meilleur dégât |
| MCTS | Cure → Laser → stay | Même résultat, validé par exploration |
| Beam | Cure → Laser → stay | Même résultat |

→ **Cas simple** : tous les algos convergent.

### Exemple 2 : Synergie buff (STR boost)

**Situation** : 12 TP, items = [Protein(2TP, +50 STR), Pistol(3TP), Destroyer(5TP)]

Sans buff : Destroyer fait 200 dmg, Pistol fait 80 dmg
Avec Protein : Destroyer fait 250 dmg, Pistol fait 100 dmg

| Algo | Résultat | Score | Explication |
|------|----------|-------|-------------|
| PTS | Destroyer → Pistol → Pistol | 360 | Prend le plus gros dégât d'abord |
| MCTS | Protein → Destroyer → Pistol | 370 | Explore et trouve la synergie |
| Beam | Protein → Destroyer → Pistol | 370 | Multi-path trouve aussi |

→ **Synergies** : MCTS et Beam trouvent, PTS rate.

### Exemple 3 : Kill chain

**Situation** : 15 TP, Kill donne +2 TP (passif), Ennemi1 a 50 HP, Ennemi2 a 200 HP

| Algo | Résultat | Explication |
|------|----------|-------------|
| PTS | Attack Ennemi2 (plus de points) × N | Cible le score le plus élevé d'abord |
| MCTS | Kill Ennemi1 → Attack Ennemi2 × N | Simule le bonus TP du kill |
| Beam | Kill Ennemi1 → Attack Ennemi2 × N | Trouve via multi-path |

→ **Passifs** : MCTS et Beam exploitent les kills grâce au chaînage.

### Exemple 4 : Positionnement critique

**Situation** : HP faible, danger élevé sur certaines cellules

| Algo | Résultat | Explication |
|------|----------|-------------|
| PTS | Attaque depuis cellule dangereuse | Maximise damage, ignore position |
| MCTS | Attaque depuis cellule safe | Rollout inclut le danger |
| Beam | Attaque depuis cellule safe | Score inclut danger via position |

→ **Danger** : Tous gèrent via le scoring de position, mais MCTS l'intègre mieux dans ses rollouts.

---

## Tuning et configuration

### Paramètres par algorithme

#### PTS
Pas de paramètres configurables - algorithme déterministe basé sur le scoring.

#### MCTS
```leekscript
static real EXPLORATION_CONSTANT = 1.414  // √2, standard UCB1
static integer MAX_ACTIONS_TO_TRY = 8     // Pruning action space
static integer MAX_ITERATIONS = 150       // Iterations par cellule
static integer SAFETY_BUFFER = 200000     // Ops réservées pour play()
```

| Paramètre | Effet si augmenté | Effet si diminué |
|-----------|-------------------|------------------|
| `EXPLORATION_CONSTANT` | Plus d'exploration, moins de focus | Plus d'exploitation, risque local max |
| `MAX_ACTIONS_TO_TRY` | Plus d'options, plus lent | Moins d'options, peut rater des combos |
| `MAX_ITERATIONS` | Meilleure qualité, plus lent | Plus rapide, moins précis |
| `SAFETY_BUFFER` | Plus de marge, moins d'exploration | Plus d'exploration, risque timeout |

#### BeamSearch
```leekscript
static integer BEAM_WIDTH = 15            // Candidats par niveau
static integer MAX_DEPTH = 6              // Profondeur max
static integer MAX_ACTIONS_TO_TRY = 8     // Pruning action space
static integer SAFETY_BUFFER = 200000     // Ops réservées pour play()
```

| Paramètre | Effet si augmenté | Effet si diminué |
|-----------|-------------------|------------------|
| `BEAM_WIDTH` | Moins de pruning, plus lent | Plus rapide, peut perdre des bons chemins |
| `MAX_DEPTH` | Combos plus longs | Combos plus courts |
| `MAX_ACTIONS_TO_TRY` | Plus d'options par état | Moins d'options, plus rapide |

### Recommandations de tuning

**Pour plus de qualité** (si ops disponibles) :
```leekscript
MCTS.MAX_ITERATIONS = 200
BeamSearch.BEAM_WIDTH = 20
BeamSearch.MAX_DEPTH = 8
```

**Pour plus de vitesse** (si budget serré) :
```leekscript
MCTS.MAX_ITERATIONS = 80
MCTS.MAX_ACTIONS_TO_TRY = 5
BeamSearch.BEAM_WIDTH = 8
BeamSearch.MAX_DEPTH = 4
```

---

## Classement final

### Par qualité de combo (meilleur en haut)

1. **MCTS** ★★★★★ - Exploration UCB1, trouve les synergies complexes
2. **HYBRID_GUIDED** ★★★★½ - MCTS complet avec fallback PTS
3. **BeamSearch** ★★★★☆ - Multi-path efficace
4. **HYBRID_BEAM** ★★★★☆ - Beam avec guidance PTS
5. **HYBRID** ★★★½☆ - MCTS limité à 1 cellule
6. **PTS** ★★★☆☆ - Greedy, rate les synergies

### Par efficacité (ops utilisées)

1. **PTS** ★★★★★ - ~50k-100k ops
2. **BeamSearch** ★★★★☆ - ~100k-200k ops
3. **HYBRID** ★★★½☆ - ~150k-250k ops
4. **HYBRID_BEAM** ★★★☆☆ - ~150k-300k ops
5. **HYBRID_GUIDED** ★★½☆☆ - ~200k-400k ops
6. **MCTS** ★★☆☆☆ - ~300k-500k ops

### Recommandation globale

| Usage | Mode | Justification |
|-------|------|---------------|
| **Production** | `HYBRID_GUIDED` | Meilleur compromis qualité/fiabilité |
| **Alternative** | `HYBRID_BEAM` | Si HYBRID_GUIDED timeout souvent |
| **Expérimentation** | `MODE_MCTS` ou `MODE_BEAM` | Pour comparer les algos purs |
| **Debug/Tests** | `MODE_PTS` | Rapide et reproductible |

---

## Annexe : Changement de mode

Pour changer l'algorithme, modifier dans `main` la ligne `AI.mode = ...` :

```leekscript
// ╔══════════════════════════════════════════════════════════════════════════╗
// ║                         ALGORITHM CONFIGURATION                          ║
// ╠══════════════════════════════════════════════════════════════════════════╣
// ║  MODE_PTS           Fast greedy, target-first (~50k ops)                 ║
// ║  MODE_MCTS          Full tree search (~300k ops)                         ║
// ║  MODE_BEAM          Multi-path beam search (~150k ops)                   ║
// ║  MODE_HYBRID        PTS seeds MCTS on 1 cell (~150k ops)                 ║
// ║  MODE_HYBRID_GUIDED PTS guides MCTS cell order (~250k ops) [RECOMMENDED] ║
// ║  MODE_HYBRID_BEAM   PTS guides BeamSearch (~200k ops)                    ║
// ╚══════════════════════════════════════════════════════════════════════════╝
AI.mode = AI.MODE_HYBRID_GUIDED
```

**Note** : On utilise une assignation directe (`AI.mode = ...`) car LeekScript ne permet pas les appels de méthode au scope global (en dehors des fonctions).

Après modification, uploader le fichier `main` avec :
```bash
python -m src.tools.aisync put <main_id> tagadalive/main
```

---

## Structure des fichiers

```
AI/
├── AI                    # Façade principale, getCombo()
├── Algorithms/
│   ├── MCTS              # Monte Carlo Tree Search
│   ├── PTS               # Priority Target Simulation
│   ├── BeamSearch        # Beam Search
│   └── Hybrid            # Modes hybrides (combinaisons)
├── Scoring               # Système de scoring
├── ScoringConfig         # Constantes ML-tunable
├── BattleState           # État de la bataille
├── EntityCoefs           # Coefficients par type d'entité
├── ScoringModifiers      # Modificateurs de score
└── Opportunity           # Opportunités pour PTS
```
