from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
import os
import sys
import tempfile
import threading
import time

from PySide6.QtCore import Qt, QRect, Signal, QThread, QTimer, QMimeData, QSettings
from PySide6.QtGui import QFont, QTextOption, QTextCursor, QTextBlockFormat, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QSpinBox, QLineEdit, QTextEdit,
    QFileDialog, QMessageBox, QInputDialog, QSplitter, QStackedWidget, QScrollArea,
    QProgressBar, QMenu, QDialog, QDialogButtonBox, QAbstractSpinBox, QSizePolicy)

from core import Document, Options, Result, Candidate, Cancelled, clean_text, parse_pages, recognize, save_text, ASSETS
from widgets import PageView, STYLE, app_icon, init_fonts
from version import VERSION


class OcrWorker(QThread):
    resultReady = Signal(object)
    message = Signal(str)
    progress = Signal(int, int)
    failed = Signal(str)

    def __init__(self, document, pages, options, box=None, rotations=None):
        super().__init__()
        self.document, self.pages, self.options = document, pages, options
        self.box, self.rotations = box, rotations or {}
        self.cancel = threading.Event()

    def run(self):
        from ocr.running_elements import filter_batch
        completed = []
        for n, page in enumerate(self.pages):
            if self.cancel.is_set():
                break
            try:
                started = time.monotonic()
                self.message.emit(f'Page {page + 1} · préparation de l’image…')
                image = self.document.render(page, self.options.dpi, self.box, self.rotations.get(page, 0))
                candidates = recognize(image, self.options, self.cancel,
                    lambda stage: self.message.emit(f'Page {page + 1} · {stage}'))
                label = f'Page {page + 1}' + (' · sélection' if self.box else ' · entière')
                result = Result(page, label, candidates, time.monotonic() - started, Path(self.document.path).name, image=image)
                completed.append(result)
            except Cancelled:
                break
            except Exception as error:
                self.failed.emit(f'Page {page + 1} : {error}')
            self.progress.emit(n + 1, len(self.pages))
        filter_batch(completed, self.options)
        for result in completed:
            self.resultReady.emit(result)


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, action, name=None, tip=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(action)
    if tip:
        widget.setToolTip(tip)
    return widget


def row(*widgets):
    layout = QHBoxLayout()
    layout.setSpacing(7)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class AlephWindow(QMainWindow):
    def __init__(self, settings=True):
        super().__init__()
        self.setWindowTitle('Aleph OCR — mode professionnel')
        self.setWindowIcon(app_icon())
        self.resize(1400, 880)
        self.setMinimumSize(1040, 720)
        self.setAcceptDrops(True)
        self.document = None
        self.page = 0
        self.rotations = {}
        self.results = []
        self.current_result = None
        self.worker = None
        self.errors = []
        self.updating = False
        self.dirty = False
        self.temporary = tempfile.TemporaryDirectory(prefix='aleph-session-')
        self.settings = QSettings('AlephOCR', 'Professional') if settings else None
        self.build_ui()
        self.bind_shortcuts()
        self.restore_options()
        self.set_document_controls(False)
        self.update_count()
        self.statusBar().showMessage('Prêt · traitement 100 % local · aucun document envoyé sur Internet')

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName('header')
        top = QHBoxLayout(header)
        top.setContentsMargins(24, 16, 24, 16)
        mark = QLabel()
        mark.setFixedSize(64, 64)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(app_icon().pixmap(58, 58))
        top.addWidget(mark)
        top.addSpacing(5)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label('Aleph OCR', 'brand'))
        brand.addWidget(label('HÉBREU & RACHI  /  DE LA PAGE AU TEXTE', 'tagline'))
        top.addLayout(brand)
        top.addStretch()
        top.addWidget(label('100 % HORS LIGNE', 'badge'))
        top.addSpacing(14)
        self.open_button = button('Ouvrir un document', self.open_dialog, 'primary', 'PDF, PNG, JPEG, TIFF · Ctrl+O')
        self.paste_button = button('Coller une image', self.paste_image, tip='Copiez une image ou une capture, puis collez-la ici.')
        top.addWidget(self.open_button)
        top.addWidget(self.paste_button)
        top.addWidget(button('Aide', self.show_help, 'subtle'))
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(18, 18, 18, 12)
        body.setSpacing(14)
        outer.addLayout(body, 1)
        sidebar = QFrame()
        sidebar.setObjectName('panel')
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(15, 18, 15, 15)
        side.addWidget(label('RECONNAISSANCE', 'section'))
        side.addWidget(label('Réglages de lecture', 'panelTitle'))
        side.addSpacing(9)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_body = QWidget()
        scroll_body.setObjectName('settingsBody')
        settings_layout = QVBoxLayout(scroll_body)
        settings_layout.setContentsMargins(0, 0, 5, 0)
        settings_layout.setSpacing(8)
        settings_layout.addWidget(label('Écriture du document'))
        self.script = QComboBox()
        for text, value in [('Automatique · hébreu + Rachi', 'auto'), ('Hébreu classique', 'square'), ('Rachi / רש״י', 'rashi'), ('Page mixte · texte + Rachi', 'mixed')]:
            self.script.addItem(text, value)
        settings_layout.addWidget(self.script)
        settings_layout.addWidget(label('Organisation du passage'))
        self.layout_mode = QComboBox()
        for text, value in [('Mise en page automatique', 'auto'), ('Un bloc / une colonne', 'block'), ('Une seule ligne', 'line'), ('Colonnes détectées · RTL', 'columns')]:
            self.layout_mode.addItem(text, value)
        self.layout_mode.setToolTip('Détecte les espaces entre colonnes et paragraphes. Vérifiez l’ordre sur les mises en page complexes.')
        settings_layout.addWidget(self.layout_mode)
        settings_layout.addWidget(label('Résolution du PDF'))
        self.resolution = QComboBox()
        for text, value in [('300 ppp · rapide', 300), ('360 ppp · équilibré', 360), ('450 ppp · petits caractères', 450)]:
            self.resolution.addItem(text, value)
        self.resolution.setCurrentIndex(1)
        settings_layout.addWidget(self.resolution)
        self.enhanced = QCheckBox('Précision renforcée')
        self.enhanced.setChecked(True)
        self.enhanced.setToolTip('Compare les niveaux de gris et le contraste local. Les deux lectures restent disponibles dans le résultat.')
        self.deskew = QCheckBox('Redresser les lignes')
        self.deskew.setChecked(True)
        self.ocr_languages = {code: QCheckBox(name) for code, name in [('heb', 'עברית'), ('heb_rashi', 'רש״י'), ('fra', 'Français'), ('eng', 'English')]}
        for code, checkbox in self.ocr_languages.items():
            checkbox.setChecked(code in ('heb', 'heb_rashi'))
        settings_layout.addWidget(self.enhanced)
        settings_layout.addWidget(self.deskew)
        for checkbox in self.ocr_languages.values():
            settings_layout.addWidget(checkbox)
        self.ignore_headers = QCheckBox('Ignorer les en-têtes/pieds répétés')
        self.ignore_headers.setChecked(True)
        self.ignore_pages = QCheckBox('Ignorer la pagination détectée')
        self.ignore_pages.setChecked(True)
        self.include_repeated = QCheckBox('Inclure les éléments répétitifs')
        for checkbox in (self.ignore_headers, self.ignore_pages, self.include_repeated):
            settings_layout.addWidget(checkbox)
        settings_layout.addSpacing(10)
        settings_layout.addWidget(label('PLUSIEURS PAGES', 'section'))
        self.page_range = QLineEdit()
        self.page_range.setPlaceholderText('Toutes, ou 1-3, 5, 8')
        self.page_range.setToolTip('Laissez vide pour traiter toutes les pages. La sélection de zone ne s’applique pas au traitement par lot.')
        settings_layout.addWidget(self.page_range)
        self.batch_button = button('Lire ces pages', self.start_batch)
        settings_layout.addWidget(self.batch_button)
        settings_layout.addSpacing(10)
        settings_layout.addWidget(label('Conseil Rachi\nCadrez un seul commentaire, puis choisissez « Un bloc / une colonne ».', 'hint', True))
        settings_layout.addStretch()
        scroll.setWidget(scroll_body)
        side.addWidget(scroll, 1)
        self.read_button = button('Reconnaître la page', self.start_current, 'primary', 'Lire la sélection ou la page entière · Ctrl+Entrée')
        side.addWidget(self.read_button)
        self.cancel_button = button('Annuler la lecture', self.cancel_work, 'danger')
        self.cancel_button.hide()
        side.addWidget(self.cancel_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        side.addWidget(self.progress_bar)
        body.addWidget(sidebar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        body.addWidget(splitter, 1)
        preview = QFrame()
        preview.setObjectName('panel')
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(15, 16, 15, 12)
        title_row = QHBoxLayout()
        title_row.addWidget(label('Document original', 'panelTitle'))
        title_row.addStretch()
        self.page_counter = label('—', 'muted')
        title_row.addWidget(self.page_counter)
        preview_layout.addLayout(title_row)
        self.filename = label('PDF, images et captures d’écran', 'muted')
        self.filename.setMaximumHeight(20)
        preview_layout.addWidget(self.filename)
        self.preview_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_logo = QLabel()
        empty_logo.setPixmap(app_icon().pixmap(112, 112))
        empty_layout.addWidget(empty_logo, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(16)
        empty_layout.addWidget(label('Retrouvez les mots.', 'emptyTitle'), 0, Qt.AlignmentFlag.AlignHCenter)
        text = label('Glissez un PDF ou une image ici.\nSélectionnez un passage, puis copiez son texte.', 'muted', True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(text)
        empty_layout.addSpacing(18)
        empty_layout.addWidget(button('Choisir un document', self.open_dialog), 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(10)
        empty_layout.addWidget(button('Essayer l’exemple hébreu + Rachi', self.open_demo, 'subtle'), 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.view = PageView()
        self.view.selectionChanged.connect(self.selection_changed)
        self.preview_stack.addWidget(empty)
        self.preview_stack.addWidget(self.view)
        preview_layout.addWidget(self.preview_stack, 1)
        self.zone_label = label('Tracez un rectangle pour lire uniquement un passage.', 'muted', True)
        preview_layout.addWidget(self.zone_label)
        self.previous_button = button('‹', lambda: self.navigate(-1), tip='Page précédente')
        self.next_button = button('›', lambda: self.navigate(1), tip='Page suivante')
        self.page_spin = QSpinBox()
        self.page_spin.setPrefix('Page ')
        self.page_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self.go_to_page)
        self.rotate_button = button('Tourner', self.rotate, tip='Tourner la page de 90°')
        self.fit_button = button('Ajuster', self.view.fit_page)
        preview_layout.addLayout(row(self.previous_button, self.page_spin, self.next_button, self.rotate_button, self.fit_button))
        preview_layout.addLayout(row(button('−', lambda: self.view.zoom(1 / 1.2)), button('+', lambda: self.view.zoom(1.2)), button('Page entière', self.view.clear_selection)))
        splitter.addWidget(preview)

        result_panel = QFrame()
        result_panel.setObjectName('panel')
        result_panel.setMinimumWidth(330)
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(15, 16, 15, 15)
        result_layout.addWidget(label('Texte reconnu', 'panelTitle'))
        self.result_meta = label('Votre texte apparaîtra ici, prêt à être corrigé.', 'muted', True)
        result_layout.addWidget(self.result_meta)
        self.history = QComboBox()
        self.history.setPlaceholderText('Historique de cette session')
        self.history.currentIndexChanged.connect(self.select_result)
        result_layout.addWidget(self.history)
        self.variants = QComboBox()
        self.variants.setPlaceholderText('Lectures disponibles')
        self.variants.currentIndexChanged.connect(self.select_variant)
        result_layout.addWidget(self.variants)
        self.editor = QTextEdit()
        self.editor.setObjectName('hebrewEditor')
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.editor.setAcceptRichText(False)
        self.editor.setFont(QFont('Arial', 19))
        self.editor.setPlaceholderText('הטקסט שזוהה יופיע כאן\n\nLe texte est modifiable. Cochez la case ci-dessous pour surligner les passages douteux.')
        option = self.editor.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        option.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.document().setDefaultTextOption(option)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.textChanged.connect(self.text_edited)
        result_layout.addWidget(self.editor, 1)
        self.count = label('', 'muted')
        result_layout.addWidget(self.count)
        self.highlight_check = QCheckBox('Signaler les mots incertains')
        self.highlight_check.setChecked(False)
        self.highlight_check.toggled.connect(self.highlight_uncertain)
        result_layout.addWidget(self.highlight_check)
        result_layout.addWidget(button('Retirer le niqqud', lambda: self.transform_text(vowels=False)))
        self.copy_button = button('Copier le texte', self.copy_text, 'primary')
        self.export_button = button('Exporter…', self.export_menu)
        result_layout.addLayout(row(self.copy_button, self.export_button))
        self.native_button = button('Récupérer le texte déjà présent dans le PDF', self.extract_native, 'subtle')
        self.native_button.setToolTip('Page entière uniquement. Si le texte extrait est mal ordonné, utilisez la reconnaissance de l’image.')
        result_layout.addWidget(self.native_button)
        splitter.addWidget(result_panel)
        splitter.setSizes([550, 430])
        for combo in [self.script, self.layout_mode, self.resolution, self.history, self.variants]:
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(1)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def bind_shortcuts(self):
        for sequence, action in [('Ctrl+O', self.open_dialog), ('Ctrl+Return', self.start_current), ('Ctrl+Shift+V', self.paste_image), ('Ctrl+Shift+C', self.copy_text), ('Escape', self.view.clear_selection)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)

    def restore_options(self):
        if self.settings:
            for name, widget in [('script', self.script), ('layout', self.layout_mode), ('resolution', self.resolution)]:
                value = self.settings.value(name, widget.currentIndex(), type=int)
                widget.setCurrentIndex(max(0, min(widget.count() - 1, value)))

    def set_document_controls(self, enabled):
        for widget in [self.read_button, self.batch_button, self.page_spin, self.rotate_button, self.previous_button, self.next_button]:
            widget.setEnabled(enabled)
        self.native_button.setEnabled(bool(enabled and self.document and self.document.is_pdf))

    def open_dialog(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Ouvrir un PDF ou une image', '', 'Documents (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;Tous les fichiers (*)')
        if path:
            self.open_document(path)

    def open_demo(self):
        self.open_document(str(ASSETS / 'demo.png'))

    def open_document(self, path):
        if self.worker:
            return
        try:
            try:
                document = Document(path)
            except Exception as error:
                if getattr(error, 'err_code', None) != 4:
                    raise
                password, ok = QInputDialog.getText(self, 'PDF protégé', 'Mot de passe du document :', QLineEdit.EchoMode.Password)
                if not ok:
                    return
                document = Document(path, password)
            image = document.render(0, 130)
            self.document = document
            self.page = 0
            self.rotations = {}
            self.filename.setText(Path(path).name)
            self.filename.setToolTip(str(path))
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, document.pages)
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.set_document_controls(True)
            self.show_page(image)
            self.statusBar().showMessage(f'{document.pages} page(s) · sélectionnez un passage ou lancez la lecture de la page')
        except Exception as error:
            QMessageBox.warning(self, 'Ouverture impossible', f'Ce document ne peut pas être ouvert.\n\n{error}')

    def show_page(self, image=None):
        if not self.document:
            return
        if image is None:
            image = self.document.render(self.page, 130, rotation=self.rotations.get(self.page, 0))
        self.view.set_image(image)
        self.preview_stack.setCurrentIndex(1)
        QTimer.singleShot(0, self.view.fit_page)
        self.page_counter.setText(f'{self.page + 1} / {self.document.pages}')
        self.previous_button.setEnabled(self.page > 0)
        self.next_button.setEnabled(self.page < self.document.pages - 1)

    def navigate(self, delta):
        if self.document:
            self.page_spin.setValue(max(1, min(self.document.pages, self.page + 1 + delta)))

    def go_to_page(self, page):
        if self.document:
            previous = self.page
            try:
                image = self.document.render(page - 1, 130, rotation=self.rotations.get(page - 1, 0))
                self.page = page - 1
                self.show_page(image)
            except Exception as error:
                self.page_spin.blockSignals(True)
                self.page_spin.setValue(previous + 1)
                self.page_spin.blockSignals(False)
                QMessageBox.warning(self, 'Page illisible', str(error))

    def rotate(self):
        if self.document:
            self.rotations[self.page] = (self.rotations.get(self.page, 0) + 90) % 360
            self.show_page()

    def selection_changed(self, selected):
        self.read_button.setText('Reconnaître la sélection' if selected else 'Reconnaître la page')
        self.zone_label.setText('Zone sélectionnée · seul ce passage sera reconnu.' if selected else 'Tracez un rectangle pour lire uniquement un passage.')

    def paste_image(self):
        if self.worker:
            return
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            QMessageBox.information(self, 'Coller une image', 'Copiez d’abord une image, ou faites une capture avec Windows + Maj + S.\nRevenez ensuite ici et cliquez sur « Coller une image ».')
            return
        path = str(Path(self.temporary.name) / f'capture-{time.time_ns()}.png')
        if image.save(path, 'PNG'):
            self.open_document(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.worker:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.worker and event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.open_document(url.toLocalFile())
                    event.acceptProposedAction()
                    break

    def options(self):
        return Options(self.script.currentData(), self.layout_mode.currentData(), self.resolution.currentData(),
                       self.enhanced.isChecked(), self.deskew.isChecked(),
                       tuple(code for code, checkbox in self.ocr_languages.items() if checkbox.isChecked()),
                       ignore_running_headers=self.ignore_headers.isChecked(), ignore_pagination=self.ignore_pages.isChecked(),
                       include_repeated=self.include_repeated.isChecked(), pipeline='experimental')

    def start_current(self):
        if self.document and not self.worker:
            self.start_job([self.page], self.view.normalized_selection())

    def start_batch(self):
        if not self.document or self.worker:
            return
        try:
            pages = parse_pages(self.page_range.text(), self.document.pages)
        except ValueError as error:
            QMessageBox.warning(self, 'Pages à lire', str(error))
            return
        self.start_job(pages)

    def start_job(self, pages, box=None):
        self.errors = []
        self.progress_bar.setRange(0, len(pages))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_button.show()
        for widget in [self.read_button, self.batch_button, self.open_button, self.paste_button, self.native_button]:
            widget.setEnabled(False)
        self.worker = OcrWorker(self.document, pages, self.options(), box, dict(self.rotations))
        self.worker.resultReady.connect(self.add_result)
        self.worker.message.connect(self.statusBar().showMessage)
        self.worker.progress.connect(lambda n, total: self.progress_bar.setValue(n))
        self.worker.failed.connect(self.errors.append)
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.statusBar().showMessage('Annulation en cours… les pages déjà reconnues sont conservées.')

    def job_finished(self):
        cancelled = self.worker.cancel.is_set()
        self.worker.deleteLater()
        self.worker = None
        self.cancel_button.hide()
        self.progress_bar.hide()
        for widget in [self.read_button, self.batch_button, self.open_button, self.paste_button]:
            widget.setEnabled(True)
        self.native_button.setEnabled(bool(self.document and self.document.is_pdf))
        message = 'Lecture annulée · résultats déjà obtenus conservés.' if cancelled else 'Lecture terminée · vérifiez les mots surlignés avant de copier.'
        self.statusBar().showMessage(message)
        if self.errors:
            QMessageBox.warning(self, 'Certaines pages n’ont pas pu être lues', '\n\n'.join(self.errors[:8]))

    def add_result(self, result):
        # Preserve per-variant corrections when navigating the session history.
        # Lines arrive joined (paragraphs kept) so the join button is unnecessary.
        for candidate in result.candidates:
            candidate.text = clean_text(candidate.text, join_lines=True)
        self.results.append(result)
        self.history.addItem(f'{result.label} — {result.source}')
        self.history.setCurrentIndex(len(self.results) - 1)
        self.dirty = True

    def select_result(self, index):
        if not 0 <= index < len(self.results):
            return
        result = self.results[index]
        self.current_result = result
        self.variants.blockSignals(True)
        self.variants.clear()
        for candidate in result.candidates:
            score = f' · indice {candidate.confidence:.0f}/100' if candidate.confidence >= 0 else ''
            self.variants.addItem(candidate.label + score)
        self.variants.setCurrentIndex(result.selected)
        self.variants.blockSignals(False)
        self.show_result_text()

    def select_variant(self, index):
        if self.current_result and 0 <= index < len(self.current_result.candidates):
            self.current_result.selected = index
            self.current_result.edited_text = self.current_result.edits.get(index)
            self.show_result_text()

    def show_result_text(self):
        result = self.current_result
        self.updating = True
        self.editor.setPlainText(result.text)
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        block.setAlignment(Qt.AlignmentFlag.AlignRight)
        block.setLineHeight(135, 1)
        cursor.mergeBlockFormat(block)
        self.editor.document().clearUndoRedoStacks()
        self.updating = False
        candidate = result.candidates[result.selected]
        if not candidate.text:
            self.result_meta.setText('Aucun texte détecté. Essayez une zone plus serrée ou une autre écriture.')
        elif candidate.confidence < 0:
            self.result_meta.setText('Texte extrait du PDF · vérifiez l’ordre de lecture.')
        else:
            self.result_meta.setText(f'{len(candidate.uncertain)} mot(s) à vérifier · {result.elapsed:.1f} s\nL’indice du moteur n’est pas un taux d’exactitude.')
        self.highlight_uncertain()
        self.update_count()

    def text_edited(self):
        if self.current_result and not self.updating:
            text = self.editor.toPlainText()
            self.current_result.edited_text = text
            self.current_result.edits[self.current_result.selected] = text
            self.dirty = True
        self.update_count()
        self.highlight_uncertain()

    def update_count(self):
        text = self.editor.toPlainText()
        self.count.setText(f'{len(text.split())} mots · {len(text)} caractères · lecture de droite à gauche')
        self.copy_button.setEnabled(bool(text))
        self.export_button.setEnabled(bool(text or self.results))

    def highlight_uncertain(self):
        selections = []
        if self.current_result and self.highlight_check.isChecked():
            words = self.current_result.candidates[self.current_result.selected].uncertain
            for word in words:
                cursor = QTextCursor(self.editor.document())
                while True:
                    cursor = self.editor.document().find(word, cursor)
                    if cursor.isNull():
                        break
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    selection.format.setBackground(QColor('#fff0b6'))
                    selection.format.setToolTip('Mot incertain selon le moteur OCR : comparez avec l’image.')
                    selections.append(selection)
        self.editor.setExtraSelections(selections)

    def transform_text(self, vowels=True, join=False):
        text = self.editor.toPlainText()
        if not text:
            return
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(clean_text(text, vowels=vowels, join_lines=join))
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)

    def copy_text(self):
        cursor = self.editor.textCursor()
        text = cursor.selectedText().replace('\u2029', '\n') if cursor.hasSelection() else self.editor.toPlainText()
        if not text:
            return
        mime = QMimeData()
        mime.setText(text)
        mime.setHtml('<html><body><div dir="rtl" style="text-align:right;white-space:pre-wrap;font-family:Arial">' + escape(text) + '</div></body></html>')
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage('Texte copié · collez-le dans Word, un message ou votre éditeur.', 6000)

    def export_menu(self):
        menu = QMenu(self)
        menu.addAction('Texte affiché → Word (.docx)', lambda: self.export(False, True))
        menu.addAction('Texte affiché → texte (.txt)', lambda: self.export(False, False))
        menu.addSeparator()
        menu.addAction('Tous les résultats → Word (.docx)', lambda: self.export(True, True))
        menu.addAction('Tous les résultats → texte (.txt)', lambda: self.export(True, False))
        menu.exec(self.export_button.mapToGlobal(self.export_button.rect().bottomLeft()))

    def export(self, all_results=False, word=False):
        text = '\n\n'.join(f'[{item.source} · {item.label}]\n\n{item.text}' for item in self.results) if all_results else self.editor.toPlainText()
        if not text:
            return
        extension = 'docx' if word else 'txt'
        path, _ = QFileDialog.getSaveFileName(self, 'Exporter le texte reconnu', f'Capture-Otzar-texte.{extension}', f'Fichier {extension.upper()} (*.{extension})')
        if path:
            if not path.lower().endswith('.' + extension):
                path += '.' + extension
                if Path(path).exists() and QMessageBox.question(self, 'Remplacer le fichier ?', f'Le fichier {Path(path).name} existe déjà. Le remplacer ?') != QMessageBox.StandardButton.Yes:
                    return
            try:
                save_text(path, text)
                if all_results or len(self.results) <= 1:
                    self.dirty = False
                self.statusBar().showMessage(f'Texte enregistré : {path}', 10000)
            except Exception as error:
                QMessageBox.warning(self, 'Enregistrement impossible', str(error))

    def extract_native(self):
        if not self.document or not self.document.is_pdf or self.worker:
            return
        try:
            text = self.document.extract(self.page)
            if not text:
                QMessageBox.information(self, 'PDF numérisé', 'Cette page ne contient pas de texte exploitable. Utilisez « Reconnaître la page ».')
                return
            candidate = Candidate(text, -1, [], 'Texte intégré au PDF', len(text.split()))
            self.add_result(Result(self.page, f'Page {self.page + 1} · texte PDF', [candidate], source=Path(self.document.path).name))
        except Exception as error:
            QMessageBox.warning(self, 'Extraction impossible', str(error))

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Bien utiliser Aleph OCR')
        dialog.resize(680, 640)
        layout = QVBoxLayout(dialog)
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml(f'''<h2>Aleph OCR · OCR hébreu &amp; Rachi</h2>
<p>Ouvrez un PDF ou une image. Tracez un rectangle autour du passage voulu, cliquez sur <b>Reconnaître la sélection</b>, corrigez si nécessaire et copiez le texte.</p>
<h3>Choisir la bonne lecture</h3><p><b>Hébreu classique</b> pour les caractères carrés. <b>Rachi</b> utilise un modèle spécialisé dans les caractères imprimés Rachi. <b>Automatique</b> et <b>Page mixte</b> combinent les deux modèles. L’écriture manuscrite et les styles non entraînés ne sont pas pris en charge de façon fiable.</p>
<p>Pour une page ou une colonne, la mise en page automatique cherche les colonnes et paragraphes puis les lit séparément de droite à gauche. Vérifiez toujours l’ordre sur les mises en page complexes.</p>
<h3>Précision et relecture</h3><p>La précision renforcée compare deux traitements. Le menu au-dessus du texte permet de consulter les deux lectures. Les corrections sont conservées séparément. Le surlignage indique les mots dont l’indice moteur est inférieur à 75 ; un mot non surligné peut aussi être erroné. Cet indice n’est pas un pourcentage d’exactitude.</p>
<p>Le niqqud reconnu est conservé. Sa reconnaissance n’est pas garantie. Le bouton <b>Retirer le niqqud</b> enlève aussi les signes de cantillation. Les lignes sont collées automatiquement, paragraphes conservés. Ctrl+Z annule une modification.</p>
<h3>Copier, exporter et traiter des pages</h3><p>Copiez tout le texte ou seulement les mots sélectionnés dans l’éditeur. L’export Word conserve le sens droite à gauche. Les résultats restent disponibles dans l’historique tant que l’application est ouverte. Exportez-les avant de fermer.</p>
<p>Le traitement par lot lit des pages entières : indiquez par exemple <b>1-3, 5</b>. L’annulation conserve les résultats déjà terminés. La rotation est réglable par page.</p>
<h3>Raccourcis</h3><p>Ctrl+O : ouvrir · Ctrl+Entrée : reconnaître · Ctrl+Maj+V : coller une image · Ctrl+Maj+C : copier · Échap : retirer le cadre · Ctrl+molette : zoomer.</p>
<h3>Confidentialité</h3><p>Aleph OCR fonctionne sans Internet, compte ni abonnement. Les images de travail sont temporaires et supprimées après traitement ; les captures collées sont supprimées à la fermeture normale. Les réglages seuls sont mémorisés sur cet ordinateur.</p>
<p>Version {VERSION} · Tesseract 5.5.0 · modèles tessdata_best hébreu/français/anglais et modèle Rachi AvtechScientific / Pninim. Les licences et sources accompagnent l’application.</p>''')
        layout.addWidget(help_text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event):
        if self.worker:
            self.cancel_work()
            event.ignore()
            self.statusBar().showMessage('La lecture s’arrête. Vous pourrez ensuite fermer l’application.')
            return
        if self.dirty and self.results:
            answer = QMessageBox.question(self, 'Fermer Aleph OCR ?', 'L’historique de cette session sera fermé.\nAvez-vous copié ou exporté les textes à conserver ?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self.settings:
            for name, widget in [('script', self.script), ('layout', self.layout_mode), ('resolution', self.resolution)]:
                self.settings.setValue(name, widget.currentIndex())
        self.temporary.cleanup()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('document', nargs='?')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--quick-smoke-test', action='store_true')
    parser.add_argument('--experimental', action='store_true', help='Open the legacy Smart OCR developer interface')
    parser.add_argument('--screenshot')
    parser.add_argument('--self-test-report')
    args = parser.parse_args()
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AlephOCR.AlephOCR')
    application = QApplication(sys.argv[:1])
    init_fonts()
    application.setApplicationName('Aleph OCR')
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(app_icon())
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)
    if args.self_test_report:
        from PIL import Image
        report = {'version': VERSION, 'checks': []}
        try:
            for script in ['square', 'rashi']:
                candidates = recognize(Image.open(ASSETS / f'demo-{script}.png'), Options(script=script, layout='block'), threading.Event())
                if not candidates[0].text:
                    raise RuntimeError(f'No OCR output for {script}')
                report['checks'].append({'script': script, 'text': candidates[0].text, 'confidence': candidates[0].confidence})
            if args.document:
                doc = Document(args.document)
                rendered = doc.render(0)
                report['pdf'] = {'pages': doc.pages, 'size': rendered.size, 'text': doc.extract(0)}
            report['ok'] = True
        except Exception as error:
            report['ok'] = False
            report['error'] = str(error)
        Path(args.self_test_report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0 if report['ok'] else 1
    if args.smoke_test:
        window = AlephWindow(settings=not args.smoke_test)
        window.show()
        if args.document:
            window.open_document(args.document)
    else:
        from quick import QUICK_STYLE
        if args.experimental:
            from ui.legacy_main_window import MainWindow
        else:
            from ui.main_window import MainWindow
        application.setStyleSheet(STYLE + QUICK_STYLE)
        window = MainWindow()
        window.show()
        if args.document:
            window.open_document(args.document)
        if args.quick_smoke_test:
            from PIL import Image
            sample = Image.open(ASSETS / 'demo-square.png')
            if args.experimental:
                from core import Candidate
                window.current_image = sample
                window.current_rect = QRect(200, 150, 700, 260)
                window.show_capture_image(sample)
                window._set_result(Candidate('בשנת 2026 נכתב document.pdf\nברוכים הבאים לאוצר הספרים', 94, ['document.pdf'], 'בדיקה', 8), True)
                window.display.setCurrentIndex(2)
            else:
                from domain.session import RawReading
                record = window._add_record(sample, 'document.pdf')
                record.reading = RawReading('ברוכים הבאים לאוצר הספרים', 'heb', 94)
                record.edited_text = record.raw_text
                window._show_record_text()
                window.update_actions()
            def quick_smoke():
                if args.screenshot:
                    window.grab().save(args.screenshot)
                window.close()
                application.quit()
            QTimer.singleShot(800, quick_smoke)
    if args.smoke_test:
        def smoke():
            try:
                from core import engine_path
                assert engine_path().is_file()
                for name in ['heb', 'heb_rashi', 'eng', 'fra']:
                    assert (ASSETS / 'tesseract' / 'tessdata' / (name + '.traineddata')).stat().st_size > 100000
                window.open_demo()
                application.processEvents()
                if args.screenshot:
                    window.grab().save(args.screenshot)
            finally:
                window.dirty = False
                window.close()
                application.quit()
        QTimer.singleShot(700, smoke)
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
