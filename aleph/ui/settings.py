"""Stable settings; old Smart OCR preferences never enter this workflow."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox,
    QComboBox, QSpinBox, QLabel, QDialogButtonBox, QKeySequenceEdit, QTabWidget,
    QWidget, QScrollArea)


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.t = window.t
        self.values = {}
        self.setWindowTitle(self.t('settings'))
        self.setLayoutDirection(window.layoutDirection())
        self.resize(670, 540)
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs
        outer.addWidget(tabs)

        def section(key):
            body = QWidget()
            form = QFormLayout(body)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setVerticalSpacing(16)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(body)
            tabs.addTab(scroll, self.t(key))
            return form

        def label(key, help_key=None):
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(self.t(key)))
            if help_key:
                info = QLabel('ⓘ')
                info.setToolTip(self.t(help_key))
                info.setAccessibleName(self.t(help_key))
                row.addWidget(info)
            row.addStretch()
            return widget

        def combo(form, setting, title, choices, default, help_key=None):
            control = QComboBox()
            for text, value in choices:
                control.addItem(text, value)
            current = window.settings.value(setting, default)
            control.setCurrentIndex(max(0, control.findData(current)))
            if help_key:
                control.setToolTip(self.t(help_key))
            form.addRow(label(title, help_key), control)
            self.values[setting] = control
            return control

        def check(form, setting, title, default=False, help_key=None):
            control = QCheckBox()
            control.setChecked(window.settings.value(setting, default, type=bool))
            def update_text():
                control.setText(('✓ ' if control.isChecked() else '') + self.t(title))
            control.toggled.connect(update_text)
            update_text()
            if help_key:
                control.setToolTip(self.t(help_key))
            form.addRow(control)
            self.values[setting] = control
            return control

        general = section('general_settings')
        combo(general, 'language', 'interface_language',
              [('עברית', 'he'), ('Français', 'fr'), ('English', 'en')], 'he')
        check(general, 'v04_always_on_top', 'pin', False, 'top_help')
        check(general, 'start_maximized', 'start_maximized')
        ocr = section('ocr_settings')
        combo(ocr, 'v04_script', 'writing',
              [(self.t('auto'), 'auto'), (self.t('square'), 'square'), (self.t('rashi'), 'rashi')], 'auto', 'writing_help')
        combo(ocr, 'v04_profile', 'profile',
              [(self.t('torah'), 'torah'), (self.t('general'), 'general')], 'torah', 'profile_help')
        check(ocr, 'v04_eng', 'latin_eng', False, 'latin_help')
        check(ocr, 'v04_fra', 'latin_fra', False, 'latin_help')
        check(ocr, 'v04_join_lines', 'join_lines', True, 'join_lines_help')
        combo(ocr, 'v04_nikud', 'nikud', [(self.t('nikud_keep'), 'keep'),
              (self.t('nikud_hide'), 'hide'), (self.t('nikud_remove'), 'remove')], 'keep', 'nikud_help')
        note = QLabel(self.t('raw_help'))
        note.setWordWrap(True)
        ocr.addRow(note)
        capture = section('capture_settings')
        shortcut = QKeySequenceEdit(QKeySequence(window.settings.value('v04_shortcut', 'Ctrl+Shift+O')))
        shortcut.setMaximumSequenceLength(1)
        shortcut.setToolTip(self.t('shortcut_help'))
        self.values['v04_shortcut'] = shortcut
        capture.addRow(label('shortcuts', 'shortcut_help'), shortcut)
        check(capture, 'retain_image', 'retain_image', True, 'retain_help')
        combo(capture, 'v04_after_capture', 'after_capture', [(self.t('preview_first'), 'preview'),
              (self.t('recognize_after'), 'recognize')], 'recognize', 'after_help')
        display = section('display_settings')
        fonts = sorted(set(QFontDatabase.families(QFontDatabase.WritingSystem.Hebrew)) | {'Arial'})
        font = combo(display, 'font', 'font', [(f, f) for f in fonts], 'Arial', 'font_help')
        size = QSpinBox()
        size.setRange(8, 72)
        size.setValue(window.settings.value('font_size', 18, type=int))
        self.values['font_size'] = size
        display.addRow(self.t('size'), size)
        preview = QLabel('שָׁלוֹם — רש״י — Exemple 123')
        preview.setWordWrap(True)
        def update_preview():
            preview.setFont(QFont(font.currentText(), size.value()))
        font.currentTextChanged.connect(update_preview)
        size.valueChanged.connect(update_preview)
        update_preview()
        display.addRow(preview)
        advanced = section('advanced_settings')
        combo(advanced, 'v04_resolution', 'resolution', [(self.t('automatic'), 'auto'),
              ('300 DPI', '300'), ('360 DPI', '360'), ('450 DPI', '450')], 'auto', 'resolution_help')
        check(advanced, 'v04_diagnostics', 'diagnostics')
        developer = QLabel(self.t('experimental_info'))
        developer.setWordWrap(True)
        advanced.addRow(developer)
        self.error = QLabel()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox()
        buttons.addButton(self.t('save'), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.t('cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def save(self):
        sequence = self.values['v04_shortcut'].keySequence()
        if sequence.isEmpty() or not (sequence[0].keyboardModifiers() &
            (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.error.setText(self.t('shortcut_help') + ' (Ctrl / Alt)')
            return
        for key, widget in self.values.items():
            if isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            else:
                value = widget.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            self.window.settings.setValue(key, value)
        self.accept()


def show_settings(window, tab=None):
    dialog = SettingsDialog(window)
    if tab is not None:
        dialog.tabs.setCurrentIndex(tab)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        window.apply_preferences()
