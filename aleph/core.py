"""Offline document rendering, OCR, and exports for Aleph."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageOps, ImageFilter
import pypdfium2 as pdfium

PDF_LOCK = threading.RLock()
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets'
MAX_PIXELS = 28_000_000


class Cancelled(Exception):
    pass


def clean_text(text: str, vowels: bool = True, join_lines: bool = False) -> str:
    text = unicodedata.normalize('NFC', text)
    text = re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]', '', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\x0c', '')
    text = '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n'))
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not vowels:
        text = re.sub('[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]', '', text)
    if join_lines:
        text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    return text


HEBREW_MARKS = re.compile('[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]')


def without_nikud(text: str) -> str:
    return HEBREW_MARKS.sub('', unicodedata.normalize('NFC', text))


def hebrew_typography(text: str) -> str:
    """Apply conservative, local Hebrew punctuation rules without changing words."""
    # Double quote between Hebrew letters is the Hebrew acronym mark.
    text = re.sub(r'(?<=[\u05d0-\u05ea])["”](?=[\u05d0-\u05ea])', '״', text)
    # Apostrophe after one Hebrew letter is the Hebrew geresh.
    text = re.sub(r'(?<=[\u05d0-\u05ea])[' + "'’" + r'](?=\s|$|[.,:;!?])', '׳', text)
    return text


def repair_mixed_rtl(text: str) -> str:
    """Repair a common OCR order where an LTR run is emitted before a Hebrew line."""
    repaired = []
    for line in text.splitlines():
        hebrew = len(re.findall('[\u05d0-\u05ea]', line))
        latin = len(re.findall('[A-Za-zÀ-ÿ]', line))
        leading_filename = re.match(r'^\s*[A-Za-z0-9_-]+\.[A-Za-z]{2,5}\s+(?=[\u05d0-\u05ea])', line)
        if (hebrew > latin or (leading_filename and hebrew >= 8)) and re.match(r'^\s*[A-Za-zÀ-ÿ]', line):
            match = re.match(r'^(.*?)(?=[\u05d0-\u05ea])', line)
            if match and match.group(1).strip():
                prefix = match.group(1).strip()
                line = line[match.end():].strip() + ' ' + prefix
        repaired.append(line)
    return '\n'.join(repaired)


def probable_overlap(previous: str, following: str, minimum: int = 3) -> tuple[int, int]:
    """Return overlapping word count and source character count; never mutates text."""
    from domain.text import overlap
    return overlap(previous, following, minimum)


def parse_pages(value: str, total: int) -> list[int]:
    if not value.strip():
        return list(range(total))
    result = set()
    for part in value.replace(';', ',').split(','):
        match = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', part)
        if not match:
            raise ValueError('Indiquez les pages ainsi : 1-3, 5, 8-10.')
        start = int(match[1])
        end = int(match[2] or match[1])
        if start < 1 or end > total or start > end:
            raise ValueError(f'Les pages doivent être comprises entre 1 et {total}.')
        result.update(range(start - 1, end))
    return sorted(result)


@dataclass
class Document:
    path: str
    password: str = ''
    pages: int = 0
    is_pdf: bool = False

    def __post_init__(self):
        self.is_pdf = Path(self.path).suffix.lower() == '.pdf'
        if self.is_pdf:
            with PDF_LOCK, pdfium.PdfDocument(self.path, password=self.password) as doc:
                self.pages = len(doc)
        else:
            with Image.open(self.path) as image:
                self.pages = getattr(image, 'n_frames', 1)
        if not self.pages:
            raise ValueError('Ce document ne contient aucune page.')

    def render(self, index: int, dpi: int = 320, box=None, rotation: int = 0) -> Image.Image:
        if not 0 <= index < self.pages:
            raise ValueError('Numéro de page incorrect.')
        if self.is_pdf:
            with PDF_LOCK, pdfium.PdfDocument(self.path, password=self.password) as doc:
                page = doc[index]
                w, h = page.get_size()
                scale = min(dpi / 72, (MAX_PIXELS / max(1, w * h)) ** .5)
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert('RGB')
                bitmap.close()
                page.close()
        else:
            with Image.open(self.path) as source:
                source.seek(index)
                image = ImageOps.exif_transpose(source).convert('RGB')
            if image.width * image.height > MAX_PIXELS:
                ratio = (MAX_PIXELS / (image.width * image.height)) ** .5
                image = image.resize((int(image.width * ratio), int(image.height * ratio)))
        if rotation:
            image = image.rotate(-rotation, expand=True, fillcolor='white')
        if box:
            x0, y0, x1, y1 = box
            bounds = (max(0, round(x0 * image.width)), max(0, round(y0 * image.height)),
                      min(image.width, round(x1 * image.width)), min(image.height, round(y1 * image.height)))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                raise ValueError('La zone sélectionnée est trop petite.')
            image = image.crop(bounds)
        return image

    def extract(self, index: int) -> str:
        if not self.is_pdf:
            return ''
        with PDF_LOCK, pdfium.PdfDocument(self.path, password=self.password) as doc:
            page = doc[index]
            textpage = page.get_textpage()
            text = textpage.get_text_bounded()
            textpage.close()
            page.close()
        return clean_text(text)


@dataclass
class Options:
    script: str = 'auto'
    layout: str = 'auto'
    dpi: int = 360
    enhanced: bool = True
    deskew: bool = True
    languages: tuple[str, ...] = ('heb', 'heb_rashi')
    profile: str = 'torah'
    typography: str = 'auto'
    ignore_running_headers: bool = True
    ignore_pagination: bool = True
    include_repeated: bool = False


@dataclass
class WordDecision:
    selected_text: str
    alternatives: list[str]
    engine_confidence: float
    consensus_strength: float
    source_block: int
    bbox: tuple[float, float, float, float] | None = None
    uncertain: bool = False


@dataclass
class Candidate:
    text: str
    confidence: float
    uncertain: list[str]
    label: str
    words: int
    boxes: list[tuple[str, float, float, float, float, float]] = field(default_factory=list)
    model: str = ''
    blocks: list['BlockResult'] = field(default_factory=list)
    decisions: list[WordDecision] = field(default_factory=list)


@dataclass
class BlockResult:
    box: tuple[int, int, int, int]
    order: int
    kind: str
    image: Image.Image
    candidates: list[Candidate]
    selected: int = 0
    model: str = ''
    score: float = 0
    included: bool = True
    exclusion_reason: str = ''


@dataclass
class Result:
    page: int
    label: str
    candidates: list[Candidate] = field(default_factory=list)
    elapsed: float = 0
    source: str = ''
    selected: int = 0
    edited_text: str | None = None
    edits: dict[int, str] = field(default_factory=dict)
    image: Image.Image | None = None

    @property
    def text(self):
        return self.edited_text if self.edited_text is not None else self.candidates[self.selected].text


def preprocess(image: Image.Image, deskew: bool, binary: bool = False, transform=None) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=.3)
    if deskew and min(gray.size) > 150:
        small = gray.copy()
        small.thumbnail((1000, 1000))
        small = small.point(lambda x: 0 if x < 170 else 255)
        def score(angle):
            rotated = np.asarray(small.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=255))
            return float(np.var((rotated < 128).sum(axis=1)))
        baseline = score(0)
        angles = np.arange(-3, 3.01, .5)
        best = max(angles, key=score)
        if best and score(best) > baseline * 1.08:
            gray = gray.rotate(float(best), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
            if transform is not None:
                transform['angle'] = float(best)
    if binary:
        # Local background normalization retains fine Rashi strokes on yellowed paper.
        background = gray.filter(ImageFilter.GaussianBlur(18))
        normalized = np.clip(np.asarray(gray, dtype=float) * 245 / np.maximum(np.asarray(background, dtype=float), 1), 0, 255)
        gray = Image.fromarray(normalized.astype('uint8')).point(lambda x: 0 if x < 180 else 255)
    return ImageOps.expand(gray, border=24, fill='white')


def engine_path() -> Path:
    path = ASSETS / 'tesseract' / 'tesseract.exe'
    if not path.is_file():
        raise RuntimeError('Le moteur OCR est absent. Réextrayez le dossier complet de l’application.')
    return path


def run_tesseract(image: Image.Image, lang: str, psm: int, cancel: threading.Event, label: str) -> Candidate:
    if cancel.is_set():
        raise Cancelled()
    with tempfile.TemporaryDirectory(prefix='aleph-ocr-') as folder:
        folder = Path(folder)
        source = folder / 'page.png'
        output = folder / 'result'
        image.save(source, dpi=(360, 360))
        command = [str(engine_path()), str(source), str(output), '--tessdata-dir', str(ASSETS / 'tesseract' / 'tessdata'),
                   '-l', lang, '--oem', '1', '--psm', str(psm), '-c', 'tessedit_create_txt=1', '-c', 'tessedit_create_tsv=1']
        env = os.environ.copy()
        env['OMP_THREAD_LIMIT'] = '2'
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        with (folder / 'errors.log').open('wb') as error_file:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=error_file, env=env, creationflags=flags)
            started = time.monotonic()
            while process.poll() is None:
                if cancel.wait(.08) or time.monotonic() - started > 240:
                    process.kill()
                    process.wait()
                    if cancel.is_set():
                        raise Cancelled()
                    raise RuntimeError('Cette page est trop complexe. Sélectionnez une zone plus petite.')
        if process.returncode:
            error = (folder / 'errors.log').read_text(encoding='utf-8', errors='replace')
            raise RuntimeError('La reconnaissance a échoué : ' + error[-900:])
        text = clean_text(output.with_suffix('.txt').read_text(encoding='utf-8'))
        rows = list(csv.DictReader(StringIO(output.with_suffix('.tsv').read_text(encoding='utf-8')), delimiter='\t', quoting=csv.QUOTE_NONE))
        word_rows = [(clean_text(row.get('text', '')), float(row.get('conf', -1)), row) for row in rows if row.get('level') == '5']
        word_rows = [(word, conf, row) for word, conf, row in word_rows if word and conf >= 0]
        words = [(word, conf) for word, conf, _ in word_rows]
        boxes = [(word, int(row['left']) / image.width, int(row['top']) / image.height,
                  int(row['width']) / image.width, int(row['height']) / image.height, conf)
                 for word, conf, row in word_rows]
        confidence = sum(conf * len(word) for word, conf in words) / max(1, sum(len(word) for word, _ in words))
        uncertain = list(dict.fromkeys(word for word, conf in words if conf < 75))
        return Candidate(text, confidence, uncertain, label, len(words), boxes)


def recognize(image: Image.Image, options: Options, cancel: threading.Event, progress=lambda value: None,
              raw=None, draft_callback=None) -> list[Candidate]:
    from ocr.engine import recognize_blocks
    return recognize_blocks(image, options, cancel, progress, raw, draft_callback)


def export_docx(path: str, text: str, font='Arial', font_size=14):
    """Small, standards-based Word document; all paragraphs and runs are RTL."""
    paragraphs = []
    font = escape(font, {'"': '&quot;'})
    half_points = max(16, min(144, int(font_size) * 2))
    for line in text.split('\n'):
        paragraphs.append('<w:p><w:pPr><w:bidi/><w:jc w:val="right"/></w:pPr><w:r><w:rPr>'
                          f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/><w:rtl/>'
                          f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/><w:lang w:bidi="he-IL"/>'
                          '</w:rPr><w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>')
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ''.join(paragraphs) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'
    content_types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    relationships = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types)
        archive.writestr('_rels/.rels', relationships)
        archive.writestr('word/document.xml', document)


def save_text(path: str, text: str, font='Arial', font_size=14):
    """Atomic save keeps an existing user file intact if writing fails."""
    target = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.aleph-', suffix=target.suffix, dir=target.parent)
    os.close(descriptor)
    try:
        if target.suffix.lower() == '.docx':
            export_docx(temporary, text, font, font_size)
        else:
            Path(temporary).write_text(text, encoding='utf-8-sig')
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
