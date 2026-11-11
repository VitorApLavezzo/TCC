"""Contexto de uso no Linux: tempo sem teclado e mouse e programa na janela da frente."""
import os
import sys

import psutil
import pytest

from tests._paths import AGENT_DIR

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import sensors  # noqa: E402


class FakeSession:
    def __init__(self, idle_ms=None, pid=None, error=None):
        self._idle_ms, self._pid, self._error = idle_ms, pid, error

    def idle_ms(self):
        if self._error:
            raise self._error
        return self._idle_ms

    def active_window_pid(self):
        if self._error:
            raise self._error
        return self._pid


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(sensors, "IS_LINUX", True)
    monkeypatch.setattr(sensors, "IS_WINDOWS", False)


def _session(monkeypatch, session):
    monkeypatch.setattr(sensors, "_x11_session", lambda: session)


@pytest.mark.usefixtures("linux")
class TestLinuxPresence:
    def test_idle_time_comes_in_seconds(self, monkeypatch):
        _session(monkeypatch, FakeSession(idle_ms=12500))
        assert sensors.idle_seconds() == 12.5

    def test_foreground_names_the_program_of_the_active_window(self, monkeypatch):
        _session(monkeypatch, FakeSession(pid=os.getpid()))
        assert sensors.foreground_process() == (os.getpid(), psutil.Process().name())

    def test_no_active_window_has_no_foreground(self, monkeypatch):
        _session(monkeypatch, FakeSession(pid=None))
        assert sensors.foreground_process() is None

    def test_window_of_a_program_that_already_closed_has_no_foreground(self, monkeypatch):
        _session(monkeypatch, FakeSession(pid=2 ** 22 + 12345))
        assert sensors.foreground_process() is None

    def test_failing_session_never_stops_the_collection(self, monkeypatch):
        _session(monkeypatch, FakeSession(error=OSError("servidor X fechou")))
        assert sensors.idle_seconds() is None
        assert sensors.foreground_process() is None

    def test_without_graphical_session_there_is_no_context(self, monkeypatch):
        _session(monkeypatch, None)
        assert sensors.idle_seconds() is None
        assert sensors.foreground_process() is None


class TestX11Session:
    def test_no_display_means_no_session(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(sensors, "_x11", None)
        assert sensors._x11_session() is None

    def test_wayland_is_not_read_through_x11(self, monkeypatch):
        """No Wayland o X11 só vê os programas antigos: o tempo sem uso sairia errado."""
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(sensors, "_x11", None)
        assert sensors._x11_session() is None


@pytest.mark.parametrize("desktop", ["cinnamon", "nemo-desktop", "gnome-shell", "plasmashell", "xfdesktop",
                                     "cinnamon-screensaver"])
def test_program_descending_from_the_linux_desktop_is_not_user_driven(desktop):
    from types import SimpleNamespace

    from app.services.context import is_user_driven
    started_at_login = SimpleNamespace(pid=900, ancestors=[700, 1])
    assert is_user_driven(started_at_login, foreground_pid=700, foreground_name=desktop) is False


def test_program_started_from_a_terminal_window_is_user_driven():
    from types import SimpleNamespace

    from app.services.context import is_user_driven
    from_terminal = SimpleNamespace(pid=900, ancestors=[800, 700, 1])
    assert is_user_driven(from_terminal, foreground_pid=700, foreground_name="gnome-terminal-server") is True
