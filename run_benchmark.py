from pathlib import Path
import json
import re
import sys
import threading
import time
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from core import Options, recognize, without_nikud

ROOT = Path(__file__).parent
CORPUS = ROOT / 'corpus-v02'
truth = json.loads((CORPUS / 'truth.json').read_text(encoding='utf-8'))

def normalized(text, nikud=True):
    if not nikud:
        text = without_nikud(text)
    return ''.join(c.lower() for c in text if c.isalnum() or '\u0590' <= c <= '\u05ff')

def accuracy(expected, actual, nikud=True):
    left, right = normalized(expected, nikud), normalized(actual, nikud)
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (a != b)))
        row = new
    return 1 - row[-1] / max(1, len(left))

cases = [
    ('Hébreu carré propre', Path('work/aleph/assets/demo-square.png'), '\n'.join(json.loads(Path('work/aleph/assets/demo-truth.json').read_text(encoding='utf-8'))['square']), Options(script='square', layout='block')),
    ('Rachi imprimé propre', Path('work/aleph/assets/demo-rashi.png'), '\n'.join(json.loads(Path('work/aleph/assets/demo-truth.json').read_text(encoding='utf-8'))['rashi']), Options(script='rashi', layout='block')),
    ('Hébreu + français + anglais', CORPUS/'mixed.png', '\n'.join(truth['mixed']), Options(script='auto', layout='block', languages=('heb', 'heb_rashi', 'eng', 'fra'))),
    ('Texte avec niqqud', CORPUS/'nikud.png', '\n'.join(truth['nikud']), Options(script='square', layout='block')),
    ('Fond jauni, contraste faible', CORPUS/'low_contrast.png', '\n'.join(truth['low_contrast']), Options(script='auto', layout='block')),
    ('Page inclinée 2,2°', CORPUS/'skew.png', '\n'.join(truth['skew']), Options(script='square', layout='block', deskew=True)),
    ('Deux colonnes RTL', CORPUS/'columns.png', '\n'.join(truth['columns']), Options(script='square', layout='columns')),
]
rows = []
for name, path, expected, options in cases:
    started = time.perf_counter()
    candidate = recognize(Image.open(path), options, threading.Event())[0]
    elapsed = time.perf_counter() - started
    rows.append({'cas': name, 'caractères': accuracy(expected, candidate.text), 'sans_nikud': accuracy(expected, candidate.text, False),
                 'indice_moteur': candidate.confidence/100, 'secondes': elapsed, 'sortie': candidate.text})
report = ['# Benchmark OCR local — Aleph OCR 0.2.0', '',
          'Corpus synthétique reproductible exécuté hors ligne sur cette machine. La précision est calculée par distance d’édition sur les caractères utiles. Ce corpus valide les chemins techniques ; il ne représente pas tous les livres anciens.', '',
          '| Cas | Précision caractères | Sans niqqud | Indice moteur | Temps |', '|---|---:|---:|---:|---:|']
for row in rows:
    report.append(f"| {row['cas']} | {row['caractères']:.1%} | {row['sans_nikud']:.1%} | {row['indice_moteur']:.1%} | {row['secondes']:.2f} s |")
report += ['', '## Configuration retenue', '',
           '- Tesseract 5.5 local avec `tessdata_best` pour l’hébreu, le français et l’anglais.',
           '- Modèle spécialisé Rachi AvtechScientific/Pninim.',
           '- Deux prétraitements comparés : niveaux de gris et normalisation locale du fond.',
           '- Le moteur est appelé par une interface interne indépendante de la fenêtre, afin de pouvoir le remplacer après un benchmark sur des scans réels.', '',
           '## Limites de cette mesure', '',
           'Le corpus Rachi est créé avec une police connue du modèle et favorise donc ce moteur. Le niqqud, les mises en page talmudiques, les polices anciennes et les scans abîmés nécessitent un corpus réel fourni par les futurs utilisateurs. Les sorties détaillées sont jointes dans `benchmark-v0.2.json`.']
(Path('outputs')/'benchmark-v0.2.md').write_text('\n'.join(report), encoding='utf-8')
(Path('outputs')/'benchmark-v0.2.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
print('Benchmark written:', Path('outputs')/'benchmark-v0.2.md')
