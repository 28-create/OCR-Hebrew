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
