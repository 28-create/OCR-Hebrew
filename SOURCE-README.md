# Aleph OCR — sources

Application Windows entièrement hors ligne. La version 0.4 propose un seul
parcours : préparer la capture, choisir manuellement une zone, reconnaître
son texte en hébreu carré ou Rachi, le vérifier puis le copier ou l’exporter.
Le texte brut du moteur reste conservé séparément des retouches. Aucun
découpage de page ni remplacement de mots n’est appliqué au parcours stable.
L’ancien Smart OCR reste disponible uniquement avec `--experimental`.

## Exécuter depuis les sources

Avec Python 3.14 64 bits sous Windows, dans le dossier extrait :

```powershell
python -m venv work/.venv
work/.venv/Scripts/python.exe -m pip install -r requirements.txt
work/.venv/Scripts/python.exe work/aleph/app.py
```

L'installation des bibliothèques nécessite Internet ; leur utilisation non.
Le moteur et les modèles OCR sont inclus dans `work/aleph/assets`.

Le bouton Capturer minimise l’application et affiche un petit contrôle
« Capture prête ». La sélection commence seulement après un clic sur ce
contrôle ou sur le raccourci global réglable. La barre des tâches et Alt+Tab
restent utilisables pendant la préparation. Les captures sont conservées dans
l’historique de la session avec leur image, leur résultat brut et leurs edits.
L’image source s’enregistre depuis son panneau, en PNG par défaut. Le texte
édité s’exporte en Word RTL ou en TXT UTF-8. Le PDF texte n’est pas proposé
tant que sa fidélité RTL n’est pas vérifiée.

## Construire l'installateur Windows

```powershell
work/.venv/Scripts/python.exe work/build_release.py
```

Le fichier à installer est `outputs/AlephOCR-Setup.exe`. Le programme portable
est `outputs/AlephOCR.exe` ; il est reconstruit avec le même logo. Le compilateur
Inno Setup 6 doit être installé, ou son chemin peut être donné dans la variable
`INNO_SETUP_ISCC`. Le script construit d'abord une application en dossier
(`work/release-stage/onedir/AlephOCR`), puis l'installateur et l'EXE portable. La version est
définie une seule fois dans `work/aleph/version.py` et est reprise dans
l'application, les métadonnées Windows et l'installateur.

L'installation propose Program Files par défaut, avec un choix par utilisateur
sans administrateur. Le menu Démarrer est créé automatiquement ; le raccourci
Bureau est facultatif. La désinstallation conserve les préférences par défaut
et demande explicitement avant de les supprimer. Les documents exportés ne
sont jamais inclus dans la désinstallation. La version actuelle n'est pas
signée ; une signature de l'EXE et de l'installateur peut être ajoutée plus tard.

## Vérifier

```powershell
work/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/test-run work/test_core.py work/test_app.py work/test_quick.py work/test_smart_ocr.py work/test_session.py work/test_v04.py
work/.venv/Scripts/python.exe work/verify_release.py
work/.venv/Scripts/python.exe work/benchmarks/compare_faithful.py
```

Les tests couvrent le parcours stable ainsi que l’ancien moteur expérimental.
Le benchmark local compare les deux OCR bruts sur les captures disponibles du
livre réel et les images synthétiques. Ses vérités de référence restent locales
et ne sont pas incluses dans les binaires. Aucun modèle automatique n’est
réactivé à partir de ces seuls résultats.

Les fichiers source de l'application et le logo original sont sous licence
MIT. Les autres composants conservent leurs licences respectives, incluses
dans les ressources. Aucune clé de service externe n'est nécessaire.
