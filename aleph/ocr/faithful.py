"""Stable OCR: one explicit model, one user rectangle, unmodified engine text."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import threading
import time

from PySide6.QtCore import QThread, Signal

_cache = OrderedDict()
_lock = threading.Lock()
CACHE_LIMIT = 12


def resolved_script(options, image=None):
    """Explicit choice wins; 'auto' falls back to square Hebrew on any doubt."""
    if options.script == 'rashi':
        return 'rashi'
    if options.script == 'square':
        return 'square'
    if image is not None:
        try:
            try:
                from .script_classifier import classify_script
            except ImportError:  # package layout
                from aleph.ocr.script_classifier import classify_script
            label = classify_script(image.convert('RGB')).label
        except Exception:
            return 'square'
        if label == 'rashi':
            return 'rashi'
        if label == 'mixed':
            return 'mixed'
    return 'square'


def model_string(script, options):
    bases = {'rashi': ['heb_rashi'], 'mixed': ['heb', 'heb_rashi']}.get(script, ['heb'])
    langs = set(getattr(options, 'languages', ()) or ())
    if langs and not langs <= {'heb', 'heb_rashi', 'eng', 'fra'}:
        raise ValueError('Select at least one supported OCR language.')
    latin = [code for code in ('eng', 'fra') if code in langs]
    return '+'.join(bases + latin)


def model_for(options, image=None):
    """Single Tesseract pass: Hebrew base from script plus optional Latin.

    The Latin checkboxes only append ``eng``/``fra`` to the ``-l`` string
    (``heb+eng``). No dictionary or word replacement is involved.
    """
    return model_string(resolved_script(options, image), options)


def cache_key(image, options):
    digest = hashlib.sha256(image.tobytes())
    digest.update(repr((image.mode, image.size)).encode())
    digest.update(json.dumps(asdict(options), sort_keys=True).encode())
    return digest.hexdigest()


def recognize_faithful(image, options, cancel, *, use_cache=True, diagnostics=None):
    try:
        from core import Cancelled, preprocess, run_tesseract
    except ImportError:  # package layout (python -m aleph.app from the parent dir)
        from aleph.core import Cancelled, preprocess, run_tesseract
    if cancel.is_set():
        raise Cancelled()
    key = cache_key(image, options)
    if use_cache:
        with _lock:
            if key in _cache:
                _cache.move_to_end(key)
                if diagnostics is not None:
                    diagnostics['cache_hit'] = True
                return deepcopy(_cache[key])
    # Use the grayscale/contrast preparation of the old raw pass for parity.
    # The source image itself is kept untouched for preview and PNG export.
    prepared = preprocess(image, deskew=False)
    script = resolved_script(options, image)
    model = model_string(script, options)
    result = run_tesseract(prepared, model, 6, cancel, 'OCR brut',
                           preserve_text=True, dpi=options.dpi)
    result.model = model
    if diagnostics is not None:
        diagnostics['script'] = script
    if cancel.is_set():
        raise Cancelled()
    if use_cache:
        with _lock:
            _cache[key] = deepcopy(result)
            _cache.move_to_end(key)
            while len(_cache) > CACHE_LIMIT:
                _cache.popitem(last=False)
    if diagnostics is not None:
        diagnostics['cache_hit'] = False
    return result


class FaithfulWorker(QThread):
    resultReady = Signal(object, object)
    failed = Signal(str)

    def __init__(self, image, options):
        super().__init__()
        self.image = image.copy()
        self.options = options
        self.cancel = threading.Event()

    def run(self):
        try:
            from core import Cancelled
        except ImportError:  # package layout (python -m aleph.app from the parent dir)
            from aleph.core import Cancelled
        started = time.perf_counter()
        diagnostics = {}
        try:
            result = recognize_faithful(self.image, self.options, self.cancel, diagnostics=diagnostics)
            diagnostics['ocr_ms'] = round((time.perf_counter() - started) * 1000, 1)
            self.resultReady.emit(result, diagnostics)
        except Cancelled:
            pass
        except Exception as error:
            self.failed.emit(str(error))
