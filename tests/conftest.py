"""
Cada teste roda num SQLite novo, numa pasta temporária.

MODO_DEMO=1 tem que estar ligado ANTES de importar o database.py: é o único
interruptor que força o SQLite. ESTOQUE_DB sozinho só escolhe o arquivo, e
numa máquina com a credencial do Neon configurada os testes iriam para o
banco real — foi assim que o seed_demo.py escreveu em produção.
"""

import os
import tempfile
from pathlib import Path

import pytest

os.environ["MODO_DEMO"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ["ESTOQUE_DB"] = str(Path(tempfile.mkdtemp(prefix="estoque-testes-")) / "vazio.db")

import database  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Banco vazio, com as tabelas criadas, só deste teste."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "estoque.db")
    # A segunda tranca: confere o que de fato vai acontecer, não o que
    # deveria acontecer.
    assert database.backend() == "sqlite"
    assert database.url_do_postgres() is None
    database.criar_tabelas()
    return database.DB_PATH
