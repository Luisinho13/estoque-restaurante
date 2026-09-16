"""
database.py
Cria e conecta ao banco de dados SQLite do sistema de estoque.

Estrutura:
- insumos: cada ingrediente/produto controlado no estoque
- pratos: itens do cardápio
- ficha_tecnica: quanto de cada insumo um prato consome
- compras: entradas de estoque (o que foi comprado)
- vendas_diarias: quantos de cada prato foram vendidos em um dia
- contagens_fisicas: contagem manual mensal, para reconciliar com o teórico
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "estoque.db"


def get_connection():
    """Retorna uma conexão com o banco, com chaves estrangeiras ativadas."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript(
        """
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
    )

    conn.commit()
    conn.close()
    print(f"Banco de dados criado/atualizado em: {DB_PATH}")


if __name__ == "__main__":
    criar_tabelas()
