"""
Importação da NF-e (compras) e da planilha da Zig (vendas).
"""

import openpyxl
import pytest

import crud
import nfe_import
import zig_import

CNPJ = "12345678000199"

NOTA = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe versao="4.00" Id="NFe0">
      <ide>
        <nNF>4512</nNF>
        <dhEmi>2026-10-05T09:14:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>{cnpj}</CNPJ>
        <xNome>Hortifruti Teste</xNome>
      </emit>
      <det nItem="1">
        <prod>
          <cProd>TOM01</cProd><xProd>TOMATE ITALIANO CX 20KG</xProd>
          <uCom>CX</uCom><qCom>2.0000</qCom><vUnCom>90.0000</vUnCom>
        </prod>
      </det>
      <det nItem="2">
        <prod>
          <cProd>CEB01</cProd><xProd>CEBOLA KG</xProd>
          <uCom>KG</uCom><qCom>5.5000</qCom><vUnCom>4.0000</vUnCom>
        </prod>
      </det>
    </infNFe>
  </NFe>
</nfeProc>
""".format(cnpj=CNPJ)


@pytest.fixture
def nota(tmp_path):
    caminho = tmp_path / "nota.xml"
    caminho.write_text(NOTA, encoding="utf-8")
    return caminho


def test_nfe_extrai_fornecedor_data_e_itens(nota):
    dados = nfe_import.extrair_dados_nfe(str(nota))

    assert dados["fornecedor_cnpj"] == CNPJ
    assert dados["numero_nota"] == "4512"
    assert dados["data_emissao"] == "2026-10-05"
    assert [(i["codigo_produto"], i["quantidade"]) for i in dados["itens"]] == [
        ("TOM01", 2.0), ("CEB01", 5.5),
    ]


def test_nfe_lanca_o_mapeado_com_fator_e_devolve_o_resto(banco, nota):
    crud.cadastrar_insumo("Tomate", "kg")
    crud.cadastrar_insumo("Cebola", "kg")
    crud.mapear_produto_nfe(CNPJ, "TOM01", "TOMATE ITALIANO CX 20KG", "Tomate",
                            fator_conversao=20)

    dados = nfe_import.extrair_dados_nfe(str(nota))
    lancados, nao_mapeados = nfe_import.processar_itens_nfe(dados, CNPJ)

    assert lancados == [("TOMATE ITALIANO CX 20KG", "Tomate", 40.0)]
    assert [i["codigo_produto"] for i in nao_mapeados] == ["CEB01"]
    assert crud.calcular_estoque_teorico("Tomate")["estoque_atual"] == 40
    assert crud.calcular_estoque_teorico("Cebola")["estoque_atual"] == 0
    # O número da nota é gravado: é ele que avisa quando a mesma nota volta.
    assert crud.nota_ja_lancada("4512", "Hortifruti Teste")


def test_nfe_codigo_igual_de_outro_fornecedor_nao_e_reconhecido(banco, nota):
    """Código de produto só vale dentro do fornecedor."""
    crud.cadastrar_insumo("Tomate", "kg")
    crud.mapear_produto_nfe("99999999000100", "TOM01", "OUTRA COISA", "Tomate")

    dados = nfe_import.extrair_dados_nfe(str(nota))
    lancados, nao_mapeados = nfe_import.processar_itens_nfe(dados, CNPJ)

    assert lancados == []
    assert len(nao_mapeados) == 2


COLUNAS_ZIG = ["SKU", "Tipo da Transação", "Nome do Produto", "Quantidade",
               "Valor de Desconto", "Valor total", "Data", "Data do Evento"]


def planilha_zig(tmp_path, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(COLUNAS_ZIG)
    for linha in linhas:
        ws.append(linha)
    caminho = tmp_path / "vendas.xlsx"
    wb.save(caminho)
    return caminho


def test_zig_soma_por_produto_e_dia_e_descarta_o_que_nao_e_venda(tmp_path):
    caminho = planilha_zig(tmp_path, [
        # SKU, tipo, produto, qtd, desconto, total, data, data do evento
        ["PARM", "Normal", "Parmegiana", 1, 0, 89, "05/10/2026 21:00:00", "05/10/2026 03:00:00"],
        ["PARM", "Normal", "Parmegiana", 2, 0, 178, "06/10/2026 01:30:00", "05/10/2026 03:00:00"],
        ["PARM", "Cancelamento", "Parmegiana", 1, 0, 89, "05/10/2026 22:00:00", "05/10/2026 03:00:00"],
        # Cancelado como "Normal": desconto igual ao preço e total zero.
        ["PARM", "Normal", "Parmegiana", 1, 89, 0, "05/10/2026 22:10:00", "05/10/2026 03:00:00"],
        # O fondue da sequência vem com preço zero e sem desconto, e é servido.
        ["FOND", "Normal", "Fondue sequência", 2, 0, 0, "05/10/2026 22:20:00", "05/10/2026 03:00:00"],
        # Fe e FE são produtos diferentes na Zig.
        ["Fe", "Normal", "Feijoada", 1, 0, 59, "05/10/2026 13:00:00", "05/10/2026 03:00:00"],
        ["FE", "Normal", "Fanta", 3, 0, 21, "05/10/2026 13:00:00", "05/10/2026 03:00:00"],
    ])

    dados = zig_import.extrair_vendas_zig(caminho)
    vendas = {(l["data"], l["sku"]): l["quantidade"] for l in dados["linhas"]}

    # A venda da 1h30 do dia 6 pertence ao movimento da noite do dia 5.
    assert dados["coluna_data"] == "Data do Evento"
    assert dados["datas"] == ["2026-10-05"]
    assert vendas == {
        ("2026-10-05", "PARM"): 3,
        ("2026-10-05", "FOND"): 2,
        ("2026-10-05", "Fe"): 1,
        ("2026-10-05", "FE"): 3,
    }
    assert dados["descartadas"] == 1
    assert [c["nome"] for c in dados["cancelados"]] == ["Parmegiana"]


def test_zig_reimportar_o_mesmo_relatorio_nao_duplica(banco, tmp_path):
    crud.cadastrar_insumo("Molho ao sugo", "kg")
    crud.cadastrar_prato("Parmegiana")
    crud.definir_ficha_tecnica("Parmegiana", "Molho ao sugo", 0.22)
    crud.registrar_contagem_fisica("Molho ao sugo", 10, "2026-10-05")
    crud.mapear_produto_zig("PARM", "Parmegiana", "Parmegiana")
    crud.mapear_produto_zig("COUV", "Couvert", ignorar=True)
    caminho = planilha_zig(tmp_path, [
        ["PARM", "Normal", "Parmegiana", 5, 0, 445, "05/10/2026 21:00:00", "05/10/2026 03:00:00"],
        ["COUV", "Normal", "Couvert", 4, 0, 40, "05/10/2026 21:00:00", "05/10/2026 03:00:00"],
        ["NOVO", "Normal", "Prato novo", 1, 0, 50, "05/10/2026 21:00:00", "05/10/2026 03:00:00"],
    ])

    dados = zig_import.extrair_vendas_zig(caminho)
    for _ in range(2):
        lancadas, ignoradas, nao_mapeadas = zig_import.processar_vendas_zig(dados)

    assert lancadas == [("Parmegiana", "2026-10-05", 5)]
    assert [l["sku"] for l in ignoradas] == ["COUV"]
    assert [l["sku"] for l in nao_mapeadas] == ["NOVO"]
    assert crud.total_vendido_no_dia("Parmegiana", "2026-10-05") == 5
    assert crud.calcular_estoque_teorico("Molho ao sugo")["estoque_atual"] == pytest.approx(8.9)


def test_zig_recusa_planilha_sem_as_colunas(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.append(["Produto", "Qtd"])
    caminho = tmp_path / "errada.xlsx"
    wb.save(caminho)

    with pytest.raises(ValueError, match="colunas esperadas"):
        zig_import.extrair_vendas_zig(caminho)
