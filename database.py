"""
database.py
Cria e conecta ao banco de dados do sistema de estoque.

O sistema roda sobre dois bancos, escolhidos automaticamente:

- **SQLite** (padrão): um arquivo local, sem servidor. É o modo de
  desenvolvimento e de quem roda tudo na própria máquina.
- **PostgreSQL**: usado quando existe uma URL de conexão configurada.
  É o modo da nuvem, porque o disco do Streamlit Community Cloud é
  efêmero e um arquivo SQLite lá seria apagado a qualquer momento.

O resto do código não sabe qual dos dois está embaixo. `get_connection()`
devolve sempre um objeto com a mesma interface — `execute`, `commit`,
`close`, linhas acessadas por nome de coluna — e as diferenças de dialeto
ficam todas neste arquivo.

Estrutura:
- insumos: cada ingrediente/produto controlado no estoque
- pratos: itens do cardápio
- ficha_tecnica: quanto de cada insumo um prato consome
- compras: entradas de estoque (o que foi comprado)
- vendas_diarias: quantos de cada prato foram vendidos em um dia
- contagens_fisicas: contagem manual mensal, para reconciliar com o teórico
- usuarios: quem pode entrar no sistema (senha guardada como hash, nunca em texto)
- permissoes: quais áreas do app cada usuário pode abrir
"""

import os
import sqlite3
import threading
from pathlib import Path

CAMINHO_DEMO = Path(__file__).parent / "estoque_demo.db"


def modo_demo() -> bool:
    """True quando o app está publicado como vitrine, com dados fictícios.

    É ligado pela variável de ambiente MODO_DEMO no app de demonstração do
    Streamlit Cloud. O app real não define essa variável.
    """
    return os.environ.get("MODO_DEMO", "").strip().lower() in ("1", "true", "sim")


# ESTOQUE_DB permite rodar o app sobre outro arquivo (ex: o de demonstração)
# sem encostar nos dados reais. Em modo demonstração o padrão já é o banco
# fictício, para não depender de configurar a variável certa lá na nuvem.
DB_PATH = Path(
    os.environ.get("ESTOQUE_DB")
    or (CAMINHO_DEMO if modo_demo() else Path(__file__).parent / "estoque.db")
)


def url_do_postgres():
    """URL de conexão do Postgres, ou None para usar o SQLite local.

    Procura primeiro na variável de ambiente e depois nos secrets do
    Streamlit, que é como a nuvem entrega a credencial. O import do
    Streamlit é protegido porque este módulo também roda em scripts
    soltos (seed_demo.py, migrar_para_nuvem.py), fora do app.

    Em modo demonstração devolve None de saída, aconteça o que acontecer.
    É o cinto de segurança da vitrine: mesmo que alguém cole a credencial
    do banco real nos secrets do app de demonstração, ele não chega nos
    dados do restaurante — cai no SQLite fictício.
    """
    if modo_demo():
        return None

    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st

        return st.secrets["postgres"]["url"]
    except Exception:
        return None


def backend():
    """'postgres' ou 'sqlite', conforme a configuração encontrada."""
    return "postgres" if url_do_postgres() else "sqlite"


# ---------- Tradução de dialeto ----------

def traduzir_placeholders(sql: str) -> str:
    """Troca os '?' do SQLite pelos '%s' do psycopg.

    Assim as consultas continuam escritas uma vez só, no dialeto do
    SQLite, e valem para os dois bancos. Dois cuidados:

    - um '?' dentro de aspas é texto, não parâmetro, e fica como está;
    - todo '%' precisa ser dobrado, **inclusive dentro de aspas**, porque
      o psycopg varre a consulta inteira procurando marcador e não sabe
      o que é literal. Foi exatamente aqui que a primeira versão errou.

    Só deve ser chamada quando a consulta leva parâmetros: sem eles o
    psycopg não interpreta '%', e o '%%' sobreviveria no resultado.
    """
    resultado = []
    aspas = None
    for caractere in sql:
        if caractere == "%":
            resultado.append("%%")
        elif aspas:
            if caractere == aspas:
                aspas = None
            resultado.append(caractere)
        elif caractere in ("'", '"'):
            aspas = caractere
            resultado.append(caractere)
        elif caractere == "?":
            resultado.append("%s")
        else:
            resultado.append(caractere)
    return "".join(resultado)


def _para_postgres(ddl: str) -> str:
    """Adapta o DDL escrito em SQLite para o Postgres."""
    return (
        ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        .replace("REAL", "DOUBLE PRECISION")
    )


def separar_comandos(script: str):
    """Quebra um script em comandos, ignorando ';' dentro de aspas."""
    comandos, atual, aspas = [], [], None
    for caractere in script:
        if aspas:
            if caractere == aspas:
                aspas = None
            atual.append(caractere)
        elif caractere in ("'", '"'):
            aspas = caractere
            atual.append(caractere)
        elif caractere == ";":
            comandos.append("".join(atual))
            atual = []
        else:
            atual.append(caractere)
    comandos.append("".join(atual))
    return [c for c in comandos if c.strip()]


# ---------- Conexão Postgres ----------

# Abrir uma conexão por consulta custa caro num banco remoto (cada uma
# refaz o TLS). O código chama get_connection()/close() dezenas de vezes,
# então a conexão é reaproveitada por thread — cada sessão do Streamlit
# roda na sua — e o close() vira um no-op.
_local = threading.local()


class _CursorPostgres:
    """Cursor com a mesma cara do sqlite3: fetchone/fetchall em dicionário."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        if params:
            self._cursor.execute(traduzir_placeholders(sql), params)
        else:
            self._cursor.execute(sql)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        raise NotImplementedError(
            "lastrowid não existe no Postgres — use 'RETURNING id' na consulta."
        )


class _ConexaoPostgres:
    """Conexão Postgres vestida com a interface do sqlite3."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cursor = self._conn.cursor()
        if params:
            cursor.execute(traduzir_placeholders(sql), params)
        else:
            cursor.execute(sql)
        return _CursorPostgres(cursor)

    def executescript(self, script):
        for comando in separar_comandos(_para_postgres(script)):
            self._conn.cursor().execute(comando)

    def cursor(self):
        return _CursorPostgres(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # A conexão é reaproveitada; fechar aqui anularia o ganho.
        pass


def _conexao_postgres():
    import psycopg
    from psycopg.rows import dict_row

    conn = getattr(_local, "conn", None)
    if conn is not None and not conn.closed:
        try:
            conn.execute("SELECT 1")
            return _ConexaoPostgres(conn)
        except Exception:
            # Conexão caiu (timeout do servidor, rede). Abre outra.
            try:
                conn.close()
            except Exception:
                pass

    conn = psycopg.connect(url_do_postgres(), row_factory=dict_row)
    _local.conn = conn
    return _ConexaoPostgres(conn)


# ---------- Conexão ----------

def get_connection():
    """Retorna uma conexão pronta para uso, no banco que estiver configurado."""
    if backend() == "postgres":
        return _conexao_postgres()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


ESQUEMA = """
        CREATE TABLE IF NOT EXISTS insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            unidade_medida TEXT NOT NULL,      -- ex: kg, g, l, ml, un
            estoque_minimo REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pratos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS ficha_tecnica (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prato_id INTEGER NOT NULL REFERENCES pratos(id),
            insumo_id INTEGER NOT NULL REFERENCES insumos(id),
            quantidade_por_prato REAL NOT NULL,  -- quanto do insumo 1 unidade do prato consome
            UNIQUE(prato_id, insumo_id)
        );

        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insumo_id INTEGER NOT NULL REFERENCES insumos(id),
            quantidade REAL NOT NULL,
            data TEXT NOT NULL,          -- formato YYYY-MM-DD
            fornecedor TEXT,
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS vendas_diarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prato_id INTEGER NOT NULL REFERENCES pratos(id),
            quantidade INTEGER NOT NULL,
            data TEXT NOT NULL           -- formato YYYY-MM-DD
        );

        CREATE TABLE IF NOT EXISTS contagens_fisicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insumo_id INTEGER NOT NULL REFERENCES insumos(id),
            quantidade_contada REAL NOT NULL,
            data TEXT NOT NULL,          -- formato YYYY-MM-DD
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,          -- PBKDF2-SHA256, em hexadecimal
            salt TEXT NOT NULL,                -- salt aleatório por usuário, em hexadecimal
            criado_em TEXT NOT NULL,           -- formato YYYY-MM-DD
            nome TEXT,                         -- nome de quem usa, só pra leitura humana
            papel TEXT NOT NULL DEFAULT 'usuario',    -- 'admin' ou 'usuario'
            status TEXT NOT NULL DEFAULT 'pendente',  -- 'pendente', 'aprovado' ou 'recusado'
            decidido_em TEXT,                  -- quando o admin aprovou ou recusou
            decidido_por TEXT                  -- qual admin decidiu
        );

        CREATE TABLE IF NOT EXISTS permissoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            area TEXT NOT NULL,                -- chave da área, ver AREAS em auth.py
            UNIQUE(usuario_id, area)
        );

        CREATE TABLE IF NOT EXISTS mapeamento_produtos_zig (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL UNIQUE,          -- código do produto na Zig
            nome_produto TEXT,                 -- nome na Zig, só pra referência humana
            prato_id INTEGER REFERENCES pratos(id),  -- NULL quando o produto é ignorado
            ignorar INTEGER NOT NULL DEFAULT 0 -- 1 = item que não consome estoque (couvert, loja)
        );

        CREATE TABLE IF NOT EXISTS mapeamento_produtos_nfe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_cnpj TEXT NOT NULL,
            codigo_produto TEXT NOT NULL,      -- cProd da nota fiscal
            descricao_produto TEXT,            -- xProd, só pra referência humana
            insumo_id INTEGER NOT NULL REFERENCES insumos(id),
            fator_conversao REAL NOT NULL DEFAULT 1,  -- ex: nota vem em "cx" mas insumo é em "kg"
            UNIQUE(fornecedor_cnpj, codigo_produto)
        );
"""

# Colunas acrescentadas depois que a tabela usuarios já existia em bancos
# reais. O CREATE TABLE acima só vale para bancos novos.
COLUNAS_NOVAS_DE_USUARIOS = {
    "nome": "TEXT",
    "papel": "TEXT NOT NULL DEFAULT 'usuario'",
    "status": "TEXT NOT NULL DEFAULT 'pendente'",
    "decidido_em": "TEXT",
    "decidido_por": "TEXT",
}


def criar_tabelas():
    conn = get_connection()

    if backend() == "postgres":
        conn.executescript(ESQUEMA)
        for coluna, tipo in COLUNAS_NOVAS_DE_USUARIOS.items():
            conn.execute(f"ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS {coluna} {tipo}")
        onde = "PostgreSQL (nuvem)"
    else:
        cursor = conn.cursor()
        cursor.executescript(ESQUEMA)
        existentes = {linha[1] for linha in cursor.execute("PRAGMA table_info(usuarios)")}
        for coluna, tipo in COLUNAS_NOVAS_DE_USUARIOS.items():
            if coluna not in existentes:
                cursor.execute(f"ALTER TABLE usuarios ADD COLUMN {coluna} {tipo}")
        onde = str(DB_PATH)

    conn.commit()
    conn.close()
    print(f"Banco de dados criado/atualizado em: {onde}")


if __name__ == "__main__":
    criar_tabelas()
