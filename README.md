# Version 9 — deux exports

Remplacer les fichiers Python du dépôt par ceux de l'archive. Fichier principal : app.py. Modules nécessaires : fusion.py, pnm.py, parametrage.py, trame.py. Installer requirements.txt.

## Fonctionnement
1. Charger FEC initial et PNM analytique (CP850 pour LAUNAY).
2. Vérifier/modifier les correspondances des journaux et comptes 512. Les codes 10,50,51,60,70 sont proposés en OD,BNP,CMB,HA,VT pour le format documenté. Les noms des journaux ne sont pas changés ; les comptes 512 restent inchangés par défaut.
3. Télécharger les deux fichiers : PENNYLANE_IMPORT.csv et ECRITURES_A_VERIFIER.csv.

La numérotation est automatique, sans case à cocher : JOURNAL-REFERENCE_PNM-COMPTEUR_UNIQUE. Le compteur évite les collisions entre exercices, dates et pièces. Si aucune référence unique n'est déterminée, la pièce va en vérification avec un identifiant technique. Libellé de ligne = PieceRef du FEC. Libellé de pièce commun à la pièce. Dates, montants et lettrage source conservés.

PENNYLANE_IMPORT.csv reprend les 15 colonnes de la trame fournie dans leur ordre, plus Poids de la catégorie en dernière colonne. UTF-8 BOM, point-virgule, une ligne d'en-tête. Mapper Identifiant de ligne et Poids de la catégorie pour les ventilations. Les montants comptables sont répétés uniquement pour la ventilation, ils ne doivent pas être sommés sans dédupliquer l'identifiant.

Toute pièce source contenant une ligne problématique est mise EN ENTIER dans ECRITURES_A_VERIFIER.csv : ambiguïté PNM, références contradictoires, dates multiples, déséquilibre, poids invalide, code journal ou compte incompatible. Ce fichier reprend les mêmes colonnes, plus le motif, l'écriture FEC, la référence PNM et les candidats. Ne pas importer ce deuxième fichier avant correction.

Les deux fichiers se complètent : aucune ligne supprimée, aucune ligne source commune aux deux. L'export principal est contrôlé pour l'équilibre de chaque pièce et l'unicité journal/date/libellé. Les contrôles locaux ne peuvent pas vérifier les paramètres propres au dossier Pennylane ou la présence d'écritures déjà importées. Le lettrage source est conservé ; sa compatibilité dépend aussi du plan comptable du dossier.

La normalisation des poids reste un choix explicite. Sans correction, les pièces concernées vont simplement en vérification et ne bloquent pas les autres. Aucun compte 471 ni montant d'équilibrage n'est inventé.

Le FEC original doit être conservé : la trame ne reprend pas toutes ses colonnes, notamment DateLet et les libellés de ligne historiques. Les détails de rapprochement restent visibles dans l'app.

Tests : python -m unittest discover -s . -v
Lancement : python -m streamlit run app.py

## Comptes clients réservés
Les racines 41106 et 411900 sont automatiquement renommées : 4110652 devient 41110652. Conversion identique sur factures, règlements et AN, avant séparation des deux fichiers. Libellés et lettrage conservés. Si la destination existe déjà dans la source, suffixe numérique 01, 02… pour éviter toute fusion. Un champ permet de déclarer d’autres comptes clients rejetés par le dossier. La table des correspondances est visible dans l’app. Les comptes existants du dossier Pennylane ne sont pas consultés ; pour un tiers déjà importé sous un autre numéro, vérifier la correspondance avant de réimporter.
Source : https://help.pennylane.com/fr/articles/29609-parametrer-et-utiliser-le-plan-comptable

Correction V9 : comptes de destination exclusivement numériques, préfixe 4111. Les comptes non concernés restent inchangés. La correction est appliquée avant séparation des exports, donc les correspondances sont identiques dans les deux fichiers.
