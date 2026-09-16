"""
diagnostico.py
Script temporário para investigar por que o desconto de estoque
não bate com o esperado. Mostra tudo que está registrado pra um
prato e um insumo específicos.

Uso: python diagnostico.py "Nome do Prato" "Nome do Insumo"
"""

import sys
from database import get_connection

if len(sys.argv) != 3:
    print('Uso: python diagnostico.py "Nome do Prato" "Nome do Insumo"')
    sys.exit(1)

nome_prato = sys.argv[1]
nome_insumo = sys.argv[2]

conn = get_connection()

prato = conn.execute("SELECT * FROM pratos WHERE nome = ?", (nome_prato,)).fetchone()
insumo = conn.execute("SELECT * FROM insumos WHERE nome = ?", (nome_insumo,)).fetchone()

if not prato:
    print(f"Prato '{nome_prato}' não encontrado.")
    sys.exit(1)
if not insumo:
    print(f"Insumo '{nome_insumo}' não encontrado.")
    sys.exit(1)

print(f"\n=== Ficha técnica de '{nome_prato}' para '{nome_insumo}' ===")
fichas = conn.execute(
    "SELECT * FROM ficha_tecnica WHERE prato_id = ? AND insumo_id = ?",
    (prato["id"], insumo["id"]),
).fetchall()
for f in fichas:
    print(dict(f))
if not fichas:
    print("(nenhuma ficha técnica encontrada)")

print(f"\n=== Todas as vendas registradas de '{nome_prato}' ===")
vendas = conn.execute(
    "SELECT * FROM vendas_diarias WHERE prato_id = ? ORDER BY data",
    (prato["id"],),
).fetchall()
for v in vendas:
    print(dict(v))
if not vendas:
    print("(nenhuma venda encontrada)")

print(f"\n=== Todas as contagens físicas de '{nome_insumo}' ===")
contagens = conn.execute(
    "SELECT * FROM contagens_fisicas WHERE insumo_id = ? ORDER BY data",
    (insumo["id"],),
).fetchall()
for c in contagens:
    print(dict(c))
if not contagens:
    print("(nenhuma contagem física encontrada)")

print(f"\n=== Todas as compras de '{nome_insumo}' ===")
compras = conn.execute(
    "SELECT * FROM compras WHERE insumo_id = ? ORDER BY data",
    (insumo["id"],),
).fetchall()
for c in compras:
    print(dict(c))
if not compras:
    print("(nenhuma compra encontrada)")

conn.close()
