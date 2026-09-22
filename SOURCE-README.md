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

## Reconstruire l'exécutable

```powershell
work/.venv/Scripts/python.exe work/build_release.py
```

Le fichier produit est `outputs/AlephOCR.exe`. Les bibliothèques Qt sont
partagées et peuvent être remplacées dans l'environnement source avant cette
reconstruction. Le programme n'est pas signé avec un certificat éditeur.

## Vérifier

```powershell
work/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/test-run
```

Les tests couvrent les textes hébreux, le Rachi, les PDF, la segmentation RTL,
les exports, les variantes, le niqqud, l'historique et le traitement par lot. Les exemples
de reconnaissance sont synthétiques : leurs résultats ne constituent pas
une mesure de précision sur les livres anciens ou sur tous les styles Rachi.

Les fichiers source de l'application et le logo original sont sous licence
MIT. Les autres composants conservent leurs licences respectives, incluses
dans les ressources. Aucune clé de service externe n'est nécessaire.
