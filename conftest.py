"""Keep automated UI tests away from the user's persistent preferences."""
import os
import tempfile
from PySide6.QtCore import QSettings
import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
_preferences = tempfile.TemporaryDirectory(prefix='aleph-test-settings-')
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _preferences.name)


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch):
    # The organization/application constructor uses the native registry on
    # Windows even when setDefaultFormat has been called. Keep tests off it.
    def test_settings(organization, application):
        return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         organization, application)

    monkeypatch.setattr('app.QSettings', test_settings)
    monkeypatch.setattr('quick.QSettings', test_settings)
    monkeypatch.setattr('ui.main_window.QSettings', test_settings)
    for section in ('Quick', 'Professional'):
        test_settings('AlephOCR', section).clear()
