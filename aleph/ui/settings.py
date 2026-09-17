from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QCheckBox, QComboBox, QSpinBox,
    QLabel, QDialogButtonBox, QKeySequenceEdit, QScrollArea, QWidget)


def show_settings(window):
    t, settings = window.t, window.settings
    dialog = QDialog(window)
    dialog.setWindowTitle(t('settings'))
    dialog.resize(610, 720)
    outer = QVBoxLayout(dialog)
    privacy = QLabel(t('privacy'))
    privacy.setWordWrap(True)
    outer.addWidget(privacy)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    body = QWidget()
    form = QFormLayout(body)
    scroll.setWidget(body)
    outer.addWidget(scroll)
    checks = {}
    for key, default in [('auto_copy', False), ('close_after_copy', False), ('show_image', True),
                         ('session_history', True), ('retain_image', True), ('ignore_headers', True),
                         ('ignore_pages', True), ('include_repeated', False), ('enhanced', True), ('deskew', True)]:
        checkbox = QCheckBox(t(key))
        checkbox.setChecked(settings.value(key, default, type=bool))
        checks[key] = checkbox
        form.addRow(checkbox)
    form.addRow(QLabel(t('languages')))
    languages = {}
    for code, text in [('heb', 'עברית'), ('heb_rashi', 'רש״י'), ('fra', 'Français'), ('eng', 'English')]:
        checkbox = QCheckBox(text)
        checkbox.setChecked(code in settings.value('ocr_languages', ['heb', 'heb_rashi']))
        languages[code] = checkbox
        form.addRow(checkbox)
    font = QComboBox()
    font.setEditable(False)
    families = QFontDatabase.families(QFontDatabase.WritingSystem.Hebrew)
    if not families:
        families = ['Arial']
    font.addItems(sorted(families))
    font.setCurrentText(settings.value('font', 'Arial'))
    size = QSpinBox()
    size.setRange(8, 72)
    size.setValue(settings.value('font_size', 18, type=int))
    preview = QLabel('אבגדה — רש״י — Exemple 123')
    def update_preview():
        preview.setFont(QFont(font.currentText(), size.value()))
    font.currentTextChanged.connect(update_preview)
    size.valueChanged.connect(update_preview)
    update_preview()
    form.addRow(t('font'), font)
    form.addRow(t('size'), size)
    form.addRow(preview)
    keys = {}
    for key, label, default in [('shortcut_area', 'area', 'Ctrl+Shift+O'), ('shortcut_window', 'window', 'Ctrl+Shift+W'),
                                ('shortcut_add', 'add', 'Ctrl+Shift+A'), ('shortcut_redo', 'redo', 'Ctrl+Shift+R')]:
        editor = QKeySequenceEdit(QKeySequence(settings.value(key, default)))
        editor.setMaximumSequenceLength(1)
        keys[key] = editor
        form.addRow(t(label), editor)
    buttons = QDialogButtonBox()
    buttons.addButton(t('save'), QDialogButtonBox.ButtonRole.AcceptRole)
    buttons.addButton(t('cancel'), QDialogButtonBox.ButtonRole.RejectRole)
    def accept():
        if not any(c.isChecked() for c in languages.values()):
            privacy.setText(t('select_language'))
            return
        dialog.accept()
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    outer.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    for key, checkbox in checks.items():
        settings.setValue(key, checkbox.isChecked())
    settings.setValue('ocr_languages', [code for code, c in languages.items() if c.isChecked()])
    settings.setValue('font', font.currentText())
    settings.setValue('font_size', size.value())
    for key, editor in keys.items():
        sequence = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if sequence:
            settings.setValue(key, sequence)
    window.apply_font()
    window.apply_display(window.display.currentIndex())
    window.install_hotkeys()
