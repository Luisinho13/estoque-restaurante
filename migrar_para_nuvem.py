"""
migrar_para_nuvem.py
Copia os dados do arquivo SQLite local para o Postgres da nuvem.

Uso:

    DATABASE_URL="postgresql://..." python migrar_para_nuvem.py
    DATABASE_URL="postgresql://..." python migrar_para_nuvem.py --de estoque_demo.db

O script é conservador de propósito:

- **Não apaga nada por conta própria.** Se alguma tabela de destino já
  tiver linhas, ele para e avisa, em vez de misturar dados. Para refazer
  a carga do zero, passe --limpar conscientemente.
- **Preserva os ids.** As tabelas se referenciam por id (ficha técnica
  aponta para prato e insumo, permissões apontam para usuário), então
  reescrever os ids quebraria as ligações. Depois de copiar, as sequências
  do Postgres são avançadas para não colidirem com os ids já usados.
- **Copia na ordem das dependências**, para não violar chave estrangeira.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import database

# A ordem importa: quem é referenciado vem antes de quem referencia.
TABELAS = [
    "insumos",
    "pratos",
    "usuarios",
    "ficha_tecnica",
    "compras",
    "vendas_diarias",
    "contagens_fisicas",
    "permissoes",
    "mapeamento_produtos_zig",
    "mapeamento_produtos_nfe",
]


def _ler_sqlite(caminho: Path):
    """Lê todas as tabelas do arquivo SQLite, em dicionários."""
    if not caminho.exists():
        sys.exit(f"Arquivo não encontrado: {caminho}")

    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    dados = {}
    for tabela in TABELAS:
        try:
            linhas = conn.execute(f"SELECT * FROM {tabela}").fetchall()
        except sqlite3.OperationalError:
            # Tabela que ainda não existe neste banco — segue o jogo.
            linhas = []
        dados[tabela] = [dict(linha) for linha in linhas]
    conn.close()
    return dados


def _contar_destino(conn):
    total = {}
    for tabela in TABELAS:
        total[tabela] = conn.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"]
    return total


def _limpar_destino(conn):
    # Ordem inversa: apaga quem referencia antes de quem é referenciado.
    for tabela in reversed(TABELAS):
        conn.execute(f"DELETE FROM {tabela}")
    conn.commit()


def _copiar(conn, tabela, linhas):
    if not linhas:
        return 0
    colunas = list(linhas[0])
    marcadores = ", ".join("?" for _ in colunas)
    sql = (
        f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({marcadores})"
    )
    for linha in linhas:
        conn.execute(sql, tuple(linha[coluna] for coluna in colunas))
    return len(linhas)


def _ajustar_sequencias(conn):
    """Avança os contadores de id do Postgres para depois do maior id copiado.

    Sem isso, o primeiro cadastro novo tentaria usar o id 1 e esbarraria
    numa linha que já existe.
    """
    for tabela in TABELAS:
        conn.execute(
            f"""SELECT setval(
                    pg_get_serial_sequence('{tabela}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {tabela}), 1),
                    (SELECT MAX(id) IS NOT NULL FROM {tabela})
                )"""
        )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Migra o banco local para a nuvem.")
    parser.add_argument(
        "--de", default=os.environ.get("ESTOQUE_DB", "estoque.db"),
        help="arquivo SQLite de origem (padrão: estoque.db)",
    )
    parser.add_argument(
        "--limpar", action="store_true",
        help="apaga os dados do destino antes de copiar (refaz a carga do zero)",
    )
    args = parser.parse_args()

    if not database.url_do_postgres():
        sys.exit(
            "Nenhum Postgres configurado.\n"
            'Rode com: DATABASE_URL="postgresql://..." python migrar_para_nuvem.py'
        )

    origem = Path(args.de)
    print(f"Lendo {origem}...")
    dados = _ler_sqlite(origem)
    for tabela in TABELAS:
        if dados[tabela]:
            print(f"  {tabela}: {len(dados[tabela])} linha(s)")

    print("\nPreparando o destino...")
    database.criar_tabelas()

    conn = database.get_connection()
    ocupadas = {t: n for t, n in _contar_destino(conn).items() if n}

    if ocupadas and not args.limpar:
        print("\nO banco de destino já tem dados:")
        for tabela, n in ocupadas.items():
            print(f"  {tabela}: {n} linha(s)")
        sys.exit(
            "\nParei para não misturar dados. Se quiser refazer a carga do zero,\n"
            "rode de novo com --limpar (isso apaga o que está na nuvem)."
        )

    if ocupadas and args.limpar:
        print("Apagando os dados do destino (--limpar)...")
        _limpar_destino(conn)

    print("\nCopiando...")
    for tabela in TABELAS:
        copiadas = _copiar(conn, tabela, dados[tabela])
        if copiadas:
            print(f"  {tabela}: {copiadas} linha(s)")
    conn.commit()

    _ajustar_sequencias(conn)

    print("\nConferindo o destino...")
    final = _contar_destino(conn)
    problemas = [
        f"  {t}: origem {len(dados[t])}, destino {final[t]}"
        for t in TABELAS
        if len(dados[t]) != final[t]
    ]
    if problemas:
        print("Divergências encontradas:")
        print("\n".join(problemas))
        sys.exit(1)

    for tabela in TABELAS:
        if final[tabela]:
            print(f"  {tabela}: {final[tabela]} ✓")
    print("\nMigração concluída.")


if __name__ == "__main__":
    main()
