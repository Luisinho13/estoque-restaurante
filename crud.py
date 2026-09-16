"""
crud.py
Funções de negócio do sistema: cadastros, lançamentos e cálculo do
estoque teórico (o coração do projeto — é o que elimina a contagem semanal).

Lógica do cálculo de estoque teórico para um insumo:
    1. Pega a última contagem física registrada (se houver) como ponto de partida.
    2. Soma todas as compras feitas depois dessa contagem.
    3. Subtrai o consumo calculado a partir das vendas diárias x ficha técnica,
       também depois dessa contagem.
    4. Resultado = estoque teórico atual, sem precisar contar nada fisicamente.
"""

from database import get_connection


# ---------- Cadastros ----------

def cadastrar_insumo(nome: str, unidade_medida: str, estoque_minimo: float = 0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO insumos (nome, unidade_medida, estoque_minimo) VALUES (?, ?, ?)",
        (nome, unidade_medida, estoque_minimo),
    )
    conn.commit()
    conn.close()


def cadastrar_prato(nome: str):
    conn = get_connection()
    conn.execute("INSERT INTO pratos (nome) VALUES (?)", (nome,))
    conn.commit()
    conn.close()


def definir_ficha_tecnica(prato_nome: str, insumo_nome: str, quantidade_por_prato: float):
    """Define quanto de um insumo é usado para preparar 1 unidade de um prato."""
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not prato or not insumo:
        conn.close()
        raise ValueError("Prato ou insumo não encontrado.")

    conn.execute(
        """
        INSERT INTO ficha_tecnica (prato_id, insumo_id, quantidade_por_prato)
        VALUES (?, ?, ?)
        ON CONFLICT(prato_id, insumo_id)
        DO UPDATE SET quantidade_por_prato = excluded.quantidade_por_prato
        """,
        (prato["id"], insumo["id"], quantidade_por_prato),
    )
    conn.commit()
    conn.close()


# ---------- Lançamentos ----------

def registrar_compra(insumo_nome: str, quantidade: float, data: str,
                      fornecedor: str = None, observacao: str = None):
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """INSERT INTO compras (insumo_id, quantidade, data, fornecedor, observacao)
           VALUES (?, ?, ?, ?, ?)""",
        (insumo["id"], quantidade, data, fornecedor, observacao),
    )
    conn.commit()
    conn.close()


def registrar_venda_diaria(prato_nome: str, quantidade: int, data: str):
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{prato_nome}' não encontrado.")

    conn.execute(
        "INSERT INTO vendas_diarias (prato_id, quantidade, data) VALUES (?, ?, ?)",
        (prato["id"], quantidade, data),
    )
    conn.commit()
    conn.close()


def registrar_contagem_fisica(insumo_nome: str, quantidade_contada: float, data: str,
                               observacao: str = None):
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """INSERT INTO contagens_fisicas (insumo_id, quantidade_contada, data, observacao)
           VALUES (?, ?, ?, ?)""",
        (insumo["id"], quantidade_contada, data, observacao),
    )
    conn.commit()
    conn.close()


# ---------- O cálculo principal ----------

def calcular_estoque_teorico(insumo_nome: str) -> dict:
    """
    Calcula o estoque teórico atual de um insumo:
    última contagem física + compras - consumo, desde a data dessa contagem.
    """
    conn = get_connection()
    insumo = conn.execute("SELECT * FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    insumo_id = insumo["id"]

    # 1. Última contagem física (ponto de partida)
    ultima_contagem = conn.execute(
        """SELECT quantidade_contada, data FROM contagens_fisicas
           WHERE insumo_id = ? ORDER BY data DESC LIMIT 1""",
        (insumo_id,),
    ).fetchone()

    if ultima_contagem:
        baseline = ultima_contagem["quantidade_contada"]
        data_baseline = ultima_contagem["data"]
    else:
        baseline = 0
        data_baseline = "0000-00-00"  # sem contagem ainda: considera tudo desde o início

    # 2. Compras a partir da baseline (inclui o próprio dia da contagem)
    total_compras = conn.execute(
        """SELECT COALESCE(SUM(quantidade), 0) AS total FROM compras
           WHERE insumo_id = ? AND data >= ?""",
        (insumo_id, data_baseline),
    ).fetchone()["total"]

    # 3. Consumo a partir da baseline (vendas x ficha técnica, inclui o mesmo dia)
    total_consumo = conn.execute(
        """
        SELECT COALESCE(SUM(v.quantidade * ft.quantidade_por_prato), 0) AS total
        FROM vendas_diarias v
        JOIN ficha_tecnica ft ON ft.prato_id = v.prato_id
        WHERE ft.insumo_id = ? AND v.data >= ?
        """,
        (insumo_id, data_baseline),
    ).fetchone()["total"]

    conn.close()

    estoque_atual = baseline + total_compras - total_consumo

    return {
        "insumo": insumo_nome,
        "unidade_medida": insumo["unidade_medida"],
        "estoque_minimo": insumo["estoque_minimo"],
        "estoque_atual": round(estoque_atual, 1),
        "abaixo_do_minimo": estoque_atual < insumo["estoque_minimo"],
        "baseline_usada": data_baseline if ultima_contagem else "sem contagem física ainda",
    }


def calcular_estoque_todos_insumos() -> list[dict]:
    conn = get_connection()
    nomes = [row["nome"] for row in conn.execute("SELECT nome FROM insumos").fetchall()]
    conn.close()
    return [calcular_estoque_teorico(nome) for nome in nomes]
