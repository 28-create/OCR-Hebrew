# v0.3 — journal vérifiable

Base GitHub `main` : aacd56032ec90b38c8564f79d542ec10e59cc4e3.
Copie locale propre, branche initiale develop. `git pull --ff-only` tenté avant
modification : échec Schannel SEC_E_NO_CREDENTIALS ; essai OpenSSL : certificat
intermédiaire local absent. GitHub connecté a confirmé main identique au commit
local (compare : identical, 0 ahead, 0 behind). Branche de travail créée depuis
main : feature/v03-smart-ocr. Aucun changement de main, aucune fusion.

## Baseline — 16 septembre 2026

- pytest sans chemins : 6 erreurs de collecte dans d'anciens dossiers temporaires.
- les 3 fichiers de tests existants : **12 passed, 1 failed, 33.35s**.
- échec préexistant : test_hebrew_rules_and_overlap, préfixe document.pdf.
- app.py, quick.py, core.py, widgets.py et les trois tests inspectés avant édition.
- benchmark synthétique v0.2 exécuté sans modifier images ni transcriptions.
- document réel שער הכונות non trouvé : mesures réelles en attente du PDF et
  de transcriptions validées. Les tests synthétiques ne remplacent pas ce contrôle.

Étape 1 : collecte pytest limitée aux sources, réglages de tests isolés,
correction ciblée de l'ancien cas de préfixe nom de fichier, comparaison OCR
reproductible avec baseline immuable et infrastructure de corpus privé local.
L'heuristique historique de texte mixte n'est pas une solution générale au bidi.

Validation étape 1 : **13 passed, 33.35s**. Comparaison baseline : CER inchangé
sur les 7 cas (carré 0 ; Rachi .0761 ; mixte .0105 ; niqqud .2586 ; contraste
.0508 ; inclinaison 0 ; colonnes 0). Mesure standard incluant ponctuation et
espaces, donc non directement comparable au pourcentage historique v0.2 qui
les supprimait. Aucun corpus modifié pour améliorer les résultats.

## Étape 2 — Smart OCR

Extraction incrémentale vers `aleph/ocr/` : segmentation par espaces, colonnes
inégales RTL, paragraphes, titres traversants, candidats d'en-tête/pied et notes
heuristiques. OCR séparé heb / heb_rashi, essais complémentaires seulement sous
un seuil de confiance, lecture brute réutilisée et conservée. Les coordonnées
de mots sont ramenées à l'image source après marge/redressement. Candidate et
Result déclarent leurs états, les blocs gardent source, ordre, modèle et score.

Filtres de livre : répétition d'un texte de bord sur au moins deux pages ;
pagination évoluant avec les pages sur au moins trois pages. Pas de suppression
sur position seule. Les éléments exclus restent disponibles dans les blocs et
dans la variante brute. Le batch publie ses résultats après analyse de répétition.
Les langues OCR sont des sélections indépendantes, sans anglais/français forcés.

Validation : **22 passed, 32.56s**. Benchmark 7 cas : aucune régression, niqqud
CER .259259 -> .222222, exactitude sans niqqud .921053 -> 1 sur ce petit cas.
Les six autres CER sont inchangés. Ce n'est pas une garantie sur des scans réels.
Pas de classificateur appris ni dictionnaire hébreu : le score de plausibilité
est un indice de caractères, la classification de mise en page est heuristique.
PDF de référence et vérité terrain encore absents ; validation réelle bloquée.

## Étapes 3 et 4 — session, interface et livraison

Fenêtre principale unique : le passage rapide/pro révèle les outils avancés sans
recréer la fenêtre. Document, page, image, texte canonique, corrections, niqqud,
variantes et historique restent liés. Ouverture permanente PDF/PNG/JPEG/TIFF/
BMP/WEBP, toutes pages par défaut, page courante ou syntaxe personnalisée via
`parse_pages`. Capture, fenêtre et collage sont accessibles dans les deux modes.

Traductions centralisées HE/FR/EN pour la nouvelle fenêtre, ses réglages, erreurs,
fermeture et actions. Choix de langues OCR séparé. Historique explicite, images
de session configurables, OCR brut sélectionnable, doublons signalés sans
suppression silencieuse. L'édition avec niqqud masqué conserve les marques des
caractères inchangés. Polices hébraïques Windows, taille, aperçu et export DOCX.

Build 0.3.0 : SHA-256 attendus versionnés et vérifiés, archive source récursive,
workflow GitHub Actions Windows, recette PyInstaller reproductible. Diagnostic
du plantage historique : PyInstaller embarquait une implémentation ICU de Windows
à la place du shim système attendu par Qt. Ces deux DLL sont désormais exclues.
L'exécutable one-file a réussi OCR carré, OCR Rachi, PDF deux pages et smoke test
de la fenêtre dans un environnement isolé sans Python dans PATH.

Validation finale locale : **34 passed**. Tests dédiés ajoutés pour segmentation,
ordre RTL, langues OCR, en-têtes/pagination, niqqud non destructif, historique,
état rapide/pro, langue globale, page par défaut et capture simulée à 100/150/200 %.
La capture multi-écrans réelle et les raccourcis globaux restent à valider
manuellement sur plusieurs matériels Windows ; les tests ne prétendent pas le
contraire. Aucun support manuscrit n'est annoncé.

## Corpus réel — שער הכונות, pages imprimées 185–204

Le PDF réel de 20 pages a été rendu et inspecté intégralement hors ligne. Il ne
contient aucune couche texte. La page imprimée 185 fournit quatre découpes fixes :
paragraphe, colonne droite, page entière et petites notes. Le corpus, les images,
les transcriptions et les sorties restent dans `benchmarks/local/`, ignoré par Git.

La mesure a révélé deux défauts concrets puis guidé leur correction : les colonnes
denses restaient monolithiques, et les pieds de scanner passaient avant les notes.
Le moteur produit maintenant 5 blocs sur la colonne et 10 sur la page, dans
l'ordre corps RTL, notes, puis pied. Les blocs incertains comparent `heb`,
`heb_rashi` et leur consensus ; une sélection explicite de script reste prioritaire.

Résultat provisoire page entière contre la sortie de départ : CER 0 -> 0,00617,
exactitude sans niqqud 99,38 %, ordre RTL validé, temps 61 s, 10 blocs. La porte
de non-régression passe (seuil 0,02). Le paragraphe et les notes ont été relus sur
l'image ; les longues transcriptions de colonne et de page restent signalées
`truth_verified: false`. Le rapport refuse donc correctement la validation finale
du corpus réel jusqu'à leur relecture humaine exhaustive. Il ne transforme jamais
une sortie OCR provisoire en vérité terrain.

Validation code après ce lot : **35 passed**. Benchmark synthétique inchangé sur
six cas et amélioré sur le niqqud (CER 0,259 -> 0,222), sans régression.
