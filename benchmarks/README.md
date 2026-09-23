# Comparaison OCR locale

Le corpus synthétique `corpus-v02` reste inchangé. Il ne démontre pas la qualité
sur un livre réel. Le PDF de שער הכונות (pages 185–204) est absent des pièces
jointes accessibles au début de cette étape : aucun résultat réel n'est inventé.

Exécuter depuis le dépôt :

    .venv/Scripts/python benchmarks/compare.py --output benchmarks/reports/comparison.json

L'ancien moteur est chargé depuis le commit immuable `aacd560` avec `git show`.
Le programme ne lance aucun accès réseau. Les deux moteurs reçoivent les mêmes
images, vérités terrain, scripts et langues. Le rapport indique CER standard,
CER et exactitude sans niqqud (1-CER, non bornée), ordre RTL, nombre de blocs,
temps, sorties complètes et régressions.
Les caractères de ponctuation comptent ; les espaces consécutifs sont normalisés.
Les indices de confiance du moteur ne sont pas des mesures de précision.
Sur un corpus réel, `truth_verified` doit être vrai pour chaque cas. Le rapport
sépare la porte d'exactitude de la validation finale afin qu'une transcription
OCR provisoire ne puisse jamais être présentée comme une vérité humaine.

Le rapport réel ventile aussi les éditions observées : substitutions, omissions,
insertions, espaces, ponctuation, gershayim, geresh, niqqud, lignes potentiellement
fusionnées/coupées, ordre des blocs et paires de lettres substituées. Les paires
ne viennent d'aucune liste supposée : elles sont comptées dans les sorties. Les
écarts de nombre de lignes sont signalés comme *candidats* car un retour visuel
peut être volontaire. Les objectifs de développement sont 1 % (paragraphe),
1,5 % (colonne), 2 % (page) et 4 % (petites notes), tous sans niqqud.

Pour un benchmark réel, créer `benchmarks/local/cases.json` (non versionné) :

```json
{"cases": [
  {"name": "page-185", "kind": "page", "document": "livre.pdf", "page": 1,
   "truth": "page-185.txt", "script": "auto", "layout": "auto",
   "anchors": ["début colonne droite", "début colonne gauche"]},
  {"name": "paragraphe-185", "kind": "paragraph", "document": "livre.pdf",
   "page": 1, "box": [0.55, 0.2, 0.94, 0.4], "truth": "paragraphe.txt"}
]}
```

`page` est l'index **1-based dans le PDF fourni**, pas le numéro imprimé du livre.
`box` est une zone normalisée [gauche, haut, droite, bas]. Les chemins sont relatifs
au manifeste. Préparer les quatre catégories page/column/paragraph/notes avec des
transcriptions humaines exactes et des ancres uniques dans l'ordre RTL attendu.
Une ancre absente compte comme un échec d'ordre, pas comme un succès.

    .venv/Scripts/python benchmarks/compare.py --real benchmarks/local/cases.json --output benchmarks/reports/real.json

Ne pas versionner le livre, ses captures ou ses transcriptions sans autorisation.
Les sorties réelles restent locales aussi. Sans transcription/ancres, ni CER ni
ordre de lecture ne peuvent être mesurés honnêtement.
