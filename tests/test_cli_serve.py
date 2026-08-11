"""Tests de `nfogen serve` (`nfogen/cli.py`) : demarre l'API + l'interface
web via uvicorn -- `uvicorn.run` est mocke, aucun serveur reel ne demarre."""
from __future__ import annotations

import sys

from nfogen import cli


def test_serve_calls_uvicorn_run_with_default_host_and_port(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs)))

    assert cli.main(["serve"]) == 0

    assert len(calls) == 1
    _app, kwargs = calls[0]
    assert kwargs == {"host": "0.0.0.0", "port": 8000}


def test_serve_passes_through_custom_host_and_port(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))

    cli.main(["serve", "--host", "127.0.0.1", "--port", "9000"])

    assert calls[0] == {"host": "127.0.0.1", "port": 9000}


def test_serve_without_api_extras_gives_a_clear_error(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "uvicorn", None)  # simule `uvicorn` non installe

    assert cli.main(["serve"]) == 1
    assert "pip install" in capsys.readouterr().err


def test_serve_does_not_interfere_with_normal_flag_based_usage():
    """`serve` n'est reconnu qu'en toute premiere position : les autres
    commandes (--list, generation...) continuent de fonctionner normalement."""
    assert cli.main(["--list"]) == 0
