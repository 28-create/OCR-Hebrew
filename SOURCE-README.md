# Aleph OCR — sources

Application Windows entièrement hors ligne, centrée sur la capture d’écran et
l’OCR immédiat en hébreu classique, Rachi, français et anglais. Le mode
professionnel prend en charge les PDF, les images, les pages et l’export RTL.

## Exécuter depuis les sources

Avec Python 3.14 64 bits sous Windows, dans le dossier extrait :

```powershell
python -m venv work/.venv
work/.venv/Scripts/python.exe -m pip install -r requirements.txt
work/.venv/Scripts/python.exe work/aleph/app.py
```

L'installation des bibliothèques nécessite Internet ; leur utilisation non.
Le moteur et les modèles OCR sont inclus dans `work/aleph/assets`.

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
work/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/test-run work/test_core.py work/test_app.py work/test_quick.py work/test_smart_ocr.py work/test_session.py
work/.venv/Scripts/python.exe work/verify_release.py
```

Les tests couvrent les textes hébreux, le Rachi, les PDF, la segmentation RTL,
les exports, les variantes, le niqqud, l'historique et le traitement par lot. Les exemples
de reconnaissance sont synthétiques : leurs résultats ne constituent pas
une mesure de précision sur les livres anciens ou sur tous les styles Rachi.

Les fichiers source de l'application et le logo original sont sous licence
MIT. Les autres composants conservent leurs licences respectives, incluses
dans les ressources. Aucune clé de service externe n'est nécessaire.
