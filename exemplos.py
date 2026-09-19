"""
exemplos.py
Gera os arquivos de exemplo que a demonstração oferece para download.

Quem abre "Importar Nota Fiscal" ou "Importar Vendas (PDV)" na vitrine não
tem um XML de NF-e nem um relatório do PDV à mão, e as duas telas são
metade do projeto. Aqui saem um de cada, fictícios, casando com os pratos
e insumos que o `seed_demo.py` cria.

As datas são sempre relativas a hoje. Um arquivo com data fixa guardado no
repositório envelheceria: meses depois, a venda importada cairia fora da
janela de análise do dashboard e o visitante concluiria que não funcionou.

Para gravar uma cópia em `docs/exemplos/` (que é o que aparece para quem
navega o repositório no GitHub):

    python exemplos.py
"""

import datetime
import io
from pathlib import Path
from xml.sax.saxutils import escape

import openpyxl

PASTA = Path(__file__).parent / "docs" / "exemplos"

FORNECEDOR_NOME = "Hortifruti São João Comércio de Alimentos LTDA"
FORNECEDOR_CNPJ = "12345678000199"  # fictício
NUMERO_NOTA = "004512"

# Os quatro primeiros casam com insumos que a demonstração já tem, e o
# último não — de propósito, para a tela mostrar o que faz com produto
# desconhecido, que é o ponto interessante dela.
ITENS_DA_NOTA = [
    ("7891000100103", "BATATA INGLESA LAVADA SACO 25KG", "SC", 4, 62.90),
    ("7891000100110", "TOMATE ITALIANO CAIXA 20KG", "CX", 2, 84.50),
    ("7891000100127", "CEBOLA NACIONAL SACO 20KG", "SC", 1, 71.00),
    ("7891000100134", "ALHO DESCASCADO POTE 1KG", "UN", 6, 38.20),
    ("7891000100141", "SALSINHA MACO", "MC", 10, 3.50),
]

# Uma linha por produto em cada comanda, que é como o relatório do PDV sai.
# Inclui um estorno e dois itens que não consomem estoque, porque é
# justamente disso que a tela de importação tem que dar conta.
COMANDAS = [
    # (dias atrás, mesa, [(sku, produto, categoria, preço, quantidade, tipo, praça)])
    (2, "Mesa 12", [
        ("A1", "Picanha na chapa", "Carnes", 89.90, 2, "Normal", "COZINHA QUENTE"),
        ("B7", "Porção de batata frita", "Porções", 32.00, 1, "Normal", "COZINHA QUENTE"),
        ("Z1", "Cerveja long neck", "Bebidas", 12.00, 4, "Normal", "BAR"),
        ("CV", "Couvert artístico", "Couvert", 15.00, 2, "Normal", "NÃO IMPRIMIR"),
    ]),
    (2, "Mesa 5", [
        ("C3", "Executivo do dia", "Pratos executivos", 42.00, 3, "Normal", "COZINHA QUENTE"),
        ("Z2", "Refrigerante", "Bebidas", 9.00, 3, "Normal", "BAR"),
    ]),
    (2, "Mesa 21", [
        ("D9", "Risoto de camarão", "Massas e risotos", 78.00, 1, "Normal", "COZINHA QUENTE"),
        ("A1", "Picanha na chapa", "Carnes", 89.90, 1, "Cancelado", "COZINHA QUENTE"),
        ("E4", "Pizza margherita", "Pizzas", 58.00, 1, "Normal", "COZINHA QUENTE"),
    ]),
    (1, "Mesa 3", [
        ("F6", "Hambúrguer artesanal", "Lanches", 46.00, 2, "Normal", "COZINHA QUENTE"),
        ("B7", "Porção de batata frita", "Porções", 32.00, 2, "Normal", "COZINHA QUENTE"),
        ("Z1", "Cerveja long neck", "Bebidas", 12.00, 6, "Normal", "BAR"),
    ]),
    (1, "Mesa 18", [
        ("G2", "Frango grelhado", "Carnes", 52.00, 4, "Normal", "COZINHA QUENTE"),
        ("C3", "Executivo do dia", "Pratos executivos", 42.00, 2, "Normal", "COZINHA QUENTE"),
        ("Z2", "Refrigerante", "Bebidas", 9.00, 5, "Normal", "BAR"),
    ]),
    (1, "Mesa 7", [
        ("E4", "Pizza margherita", "Pizzas", 58.00, 3, "Normal", "COZINHA QUENTE"),
        ("D9", "Risoto de camarão", "Massas e risotos", 78.00, 2, "Normal", "COZINHA QUENTE"),
    ]),
]

COLUNAS_ZIG = [
    "id", "SKU", "Tipo da Transação", "Nome do Produto", "Categoria",
    "Valor Unitário", "Quantidade", "Valor de Desconto", "Vendedor",
    "Cliente", "Data", "Origem", "Tipo", "Valor total", "Bar",
    "Data do Evento",
]


def nota_fiscal_xml(hoje: datetime.date | None = None) -> bytes:
    """XML de NF-e fictício, emitido ontem."""
    hoje = hoje or datetime.date.today()
    emissao = hoje - datetime.timedelta(days=1)

    detalhes = []
    for posicao, (codigo, descricao, unidade, quantidade, preco) in enumerate(ITENS_DA_NOTA, 1):
        detalhes.append(f"""    <det nItem="{posicao}">
      <prod>
        <cProd>{codigo}</cProd>
        <xProd>{escape(descricao)}</xProd>
        <uCom>{unidade}</uCom>
        <qCom>{quantidade:.4f}</qCom>
        <vUnCom>{preco:.4f}</vUnCom>
        <vProd>{quantidade * preco:.2f}</vProd>
      </prod>
    </det>""")

    total = sum(q * p for _, _, _, q, p in ITENS_DA_NOTA)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Nota fiscal FICTÍCIA, só para experimentar a importação do sistema. -->
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe versao="4.00" Id="NFe00000000000000000000000000000000000000000000">
      <ide>
        <nNF>{NUMERO_NOTA}</nNF>
        <dhEmi>{emissao.isoformat()}T09:14:00-03:00</dhEmi>
        <natOp>VENDA DE MERCADORIA</natOp>
      </ide>
      <emit>
        <CNPJ>{FORNECEDOR_CNPJ}</CNPJ>
        <xNome>{escape(FORNECEDOR_NOME)}</xNome>
      </emit>
{chr(10).join(detalhes)}
      <total>
        <ICMSTot>
          <vNF>{total:.2f}</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>
"""
    return xml.encode("utf-8")


def vendas_pdv_xlsx(hoje: datetime.date | None = None) -> bytes:
    """Relatório de vendas fictício no formato que o PDV exporta."""
    hoje = hoje or datetime.date.today()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Worksheet"
    ws.append(COLUNAS_ZIG)

    identificador = 0
    for dias_atras, mesa, itens in COMANDAS:
        dia = hoje - datetime.timedelta(days=dias_atras)
        identificador += 1
        # O horário da transação é de madrugada de propósito: é o caso em
        # que "Data" e "Data do Evento" divergem, e só a segunda vale.
        hora = f"{dia + datetime.timedelta(days=1):%d/%m/%Y} 01:2{identificador % 10}:00"
        for sku, produto, categoria, preco, quantidade, tipo, praca in itens:
            ws.append([
                f"c940eb5d3{identificador:03d}", sku, tipo, produto, categoria,
                preco, quantidade, 0, "Lucas", mesa, hora, "table",
                "Alimentos" if praca != "BAR" else "Bebidas",
                preco * quantidade, praca, f"{dia:%d/%m/%Y} 03:01:26",
            ])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def gravar_em_disco():
    PASTA.mkdir(parents=True, exist_ok=True)
    (PASTA / "nota-fiscal-exemplo.xml").write_bytes(nota_fiscal_xml())
    (PASTA / "vendas-pdv-exemplo.xlsx").write_bytes(vendas_pdv_xlsx())
    print(f"Exemplos gravados em {PASTA}")


if __name__ == "__main__":
    gravar_em_disco()
