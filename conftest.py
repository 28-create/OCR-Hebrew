"""Keep automated UI tests away from the user's persistent preferences."""
import os
import tempfile
from PySide6.QtCore import QSettings
import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
_preferences = tempfile.TemporaryDirectory(prefix='aleph-test-settings-')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _preferences.name)


@pytest.fixture(autouse=True)
def isolated_preferences():
    for section in ('Quick', 'Professional'):
        QSettings('AlephOCR', section).clear()
