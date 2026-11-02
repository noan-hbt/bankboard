# 01 — Analyse du PRD

## 1. Ce que le produit est réellement

Le PRD décrit trois produits empilés, qui doivent être construits dans cet ordre :

| Couche | Rôle | Sans elle… |
|---|---|---|
| **Ledger fiable** (sync, brut, normalisation, classification) | Vérité comptable : chaque euro est compté une fois, avec la bonne nature (dépense, virement, investissement…) | toutes les métriques sont fausses, l'IA raconte des chiffres faux |
| **Moteurs déterministes** (métriques, prédictions, détecteurs, simulations) | Transforme le ledger en état, tendances, prévisions, *insights structurés* | le produit est un relevé bancaire |
| **Couche narrative / décision** (Command Center, Advisor, Ask Your Money) | Explique, priorise, propose | l'utilisateur doit lire 15 graphiques |

Le « Financial Twin » n'est pas un composant à part : c'est **l'ensemble des profils calculés par les moteurs, versionnés dans le temps (snapshots) et accompagnés d'un niveau de confiance**. On le construit donc incrémentalement : chaque moteur P0/P1 alimente un profil.

## 2. Invariants non négociables (extraits et reformulés)

1. **Aucun chiffre produit par le LLM.** Le LLM ne voit que des sorties de tools typées ; tout montant affiché provient d'une fonction pure testée.
2. **La donnée brute est immuable.** `transaction_raw` est append-only ; tout le reste est rejouable depuis le brut.
3. **Idempotence de la sync.** Rejouer une sync N fois = même état. Une transaction bancaire n'est jamais dupliquée.
4. **Correction manuelle prioritaire.** Une classification `source = manual` n'est jamais écrasée par un rejeu du pipeline.
5. **Explicabilité.** Chaque métrique complexe retourne sa décomposition (`explanation`), chaque prédiction son intervalle et sa confiance.
6. **Indépendance fournisseur.** Ni Revolut ni Enable Banking ne sont connus hors de `providers/`. Ni un fournisseur LLM hors de `ai/providers/`.
7. **Pas de logique métier dans le frontend.** Le frontend affiche, il ne calcule pas (hors formatage).
8. **Isolation utilisateur.** Chaque requête est filtrée par `user_id` au niveau repository.

## 3. Points ambigus et décisions prises

| Sujet | Ambiguïté | Décision |
|---|---|---|
| Représentation des montants | float vs décimal | `NUMERIC(19,4)` en base, `Decimal` en Python, **centimes `Int64`** dans les DataFrames analytiques (calcul exact). |
| Signe | crédit/débit séparés chez Enable Banking | Montant **signé** côté canonique (`< 0` = sortie). L'indicateur d'origine reste dans le brut. |
| Transactions *pending* | elles changent d'identifiant/montant en devenant *booked* | Les *pending* sont stockées mais **éphémères** : à chaque sync, les pending non ré-observées dans la fenêtre sont supprimées. Seules les *booked* entrent dans les métriques historiques ; les pending entrent dans le cash disponible. |
| Clé de déduplication sans identifiant bancaire | Revolut fournit `entry_reference`/`transaction_id` mais pas toujours | `dedup_key = provider_id` sinon `sha256(date, montant, devise, libellé, contrepartie) + '#' + rang d'occurrence` (deux cafés identiques le même jour restent deux transactions, et le rejeu reproduit les mêmes clés car les fenêtres de sync commencent toujours à minuit). |
| Investissements | dépense ou non ? | `kind = investment` : exclu des dépenses et du taux d'épargne négatif ; compté comme épargne investie. |
| Virements internes | | `kind = transfer`, appariés par `transfer_group_id` ; exclus des revenus/dépenses. |
| Safe-to-spend « aujourd'hui » | horizon flou | 4 horizons définis par une **date de fin** : fin de journée, fin de semaine (dimanche), veille du prochain revenu prédit, fin de mois. Les revenus attendus ne sont **jamais** ajoutés (prudence). |
| Buffer minimum | PRD : « 900 € » sans règle | Préférence utilisateur ; défaut = 50 % de la dépense essentielle mensuelle moyenne (remplacé par *Cash Buffer Intelligence* en P1). |
| Multi-devises | | P0 : devise de base par utilisateur ; les comptes dans une autre devise sont listés mais exclus des agrégats et signalés dans *Data Health*. |
| Auth utilisateur | P0 mais produit personnel | Email + mot de passe (scrypt), sessions opaques en cookie `HttpOnly; SameSite=Lax`, contrôle `Origin` sur les requêtes mutantes. Remplaçable par OIDC plus tard. |
| Event engine | infra lourde ? | Table `domain_events` (outbox) + dispatcher in-process. Les handlers sont idempotents ; passage à une queue (Redis/arq) sans changer les modules. |

## 4. Risques principaux

1. **Qualité de classification** → tout le reste en dépend. Mitigation : règles versionnées + confiance + écran Data Health + corrections manuelles prioritaires.
2. **Virements mal détectés** → doublent revenus et dépenses. Mitigation : appariement multi-critères + tests dédiés.
3. **Expiration du consentement PSD2** (≈ 90-180 j) → données silencieusement figées. Mitigation : `consent_valid_until`, état de connexion, alerte Data Health, *Data Confidence Score*.
4. **Sur-alerte** → l'utilisateur ignore tout. Mitigation : `importance × confidence`, fingerprint, états `new/ongoing/resolved/ignored`, max 5 éléments en ATTENTION.
5. **Scope** : 80+ features. Mitigation : découpage vertical strict (cf. `04-roadmap.md`), modules activables.

## 5. Ce que le P0 doit prouver

> Connexion Revolut → transactions stockées sans doublon → normalisées → métriques exactes → Command Center utilisable chaque jour.

Tout le P0 doit fonctionner **en mode démo** (12 mois synthétiques passant par exactement le même chemin de code que Enable Banking), afin de développer sans dépendre de la banque.
