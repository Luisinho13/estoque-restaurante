"""
A tradução do dialeto SQLite para o Postgres, em database.py.

As consultas são escritas uma vez só, com '?', e traduzidas na hora. O
SQLite não pega erro de dialeto, então é aqui que ele tem que aparecer.
"""

import database
from database import _para_postgres, separar_comandos, traduzir_placeholders


def test_interrogacao_vira_marcador_do_psycopg():
    assert (traduzir_placeholders("SELECT * FROM insumos WHERE nome = ? AND id > ?")
            == "SELECT * FROM insumos WHERE nome = %s AND id > %s")


def test_interrogacao_entre_aspas_e_texto():
    assert (traduzir_placeholders("SELECT 'Tudo certo?' WHERE nome = ?")
            == "SELECT 'Tudo certo?' WHERE nome = %s")
    assert traduzir_placeholders('SELECT "col?" FROM t') == 'SELECT "col?" FROM t'


def test_porcentagem_e_dobrada_inclusive_entre_aspas():
    """O bug da primeira versão: '%' sem escapar quebrava a consulta no psycopg."""
    assert (traduzir_placeholders("SELECT * FROM insumos WHERE nome LIKE '%molho%' AND id = ?")
            == "SELECT * FROM insumos WHERE nome LIKE '%%molho%%' AND id = %s")
    assert traduzir_placeholders("SELECT 10 % 3, ?") == "SELECT 10 %% 3, %s"


def test_aspas_escapadas_nao_desalinham_a_traducao():
    """'' dentro do texto fecha e reabre as aspas, e o '?' seguinte continua texto."""
    assert (traduzir_placeholders("SELECT 'd''água?' WHERE id = ?")
            == "SELECT 'd''água?' WHERE id = %s")


def test_ddl_do_sqlite_vira_ddl_do_postgres():
    ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, quantidade REAL NOT NULL)"
    assert (_para_postgres(ddl)
            == "CREATE TABLE t (id SERIAL PRIMARY KEY, quantidade DOUBLE PRECISION NOT NULL)")


def test_separar_comandos_ignora_ponto_e_virgula_entre_aspas():
    script = "INSERT INTO t VALUES ('a;b');\n  CREATE TABLE x (id INTEGER);\n\n"
    assert separar_comandos(script) == [
        "INSERT INTO t VALUES ('a;b')",
        "\n  CREATE TABLE x (id INTEGER)",
    ]


def test_esquema_se_separa_em_um_create_por_comando():
    """O separador quebra em todo ';' fora de aspas, inclusive dentro de
    comentário. Um ';' num comentário do esquema derrubaria o app no Neon,
    e o SQLite (que roda o script inteiro) nunca mostraria isso."""
    comandos = separar_comandos(_para_postgres(database.ESQUEMA))
    assert comandos
    for comando in comandos:
        sem_comentarios = "\n".join(
            linha.split("--")[0] for linha in comando.splitlines()
        ).strip()
        assert sem_comentarios.startswith("CREATE "), comando[:80]
        assert sem_comentarios.count("(") == sem_comentarios.count(")"), comando[:80]
