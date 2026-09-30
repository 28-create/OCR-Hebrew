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


def model_for(options):
    # Legacy automatic preferences cannot enable multi-model OCR in stable mode.
    return 'heb_rashi' if options.script == 'rashi' else 'heb'


def cache_key(image, options):
    digest = hashlib.sha256(image.tobytes())
    digest.update(repr((image.mode, image.size)).encode())
    digest.update(json.dumps(asdict(options), sort_keys=True).encode())
    return digest.hexdigest()


def recognize_faithful(image, options, cancel, *, use_cache=True, diagnostics=None):
    from core import Cancelled, preprocess, run_tesseract
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
    result = run_tesseract(prepared, model_for(options), 6, cancel, 'OCR brut',
                           preserve_text=True, dpi=options.dpi)
    result.model = model_for(options)
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
        from core import Cancelled
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
