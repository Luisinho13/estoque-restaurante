"""
nfe_import.py
Lê um arquivo XML de NF-e (nota fiscal eletrônica) e lança as compras
automaticamente no sistema de estoque.

Como funciona:
1. Extrai os itens da nota (código do produto, descrição, quantidade, unidade).
2. Pra cada item, verifica se já existe um mapeamento salvo (produto do
   fornecedor -> insumo do sistema).
3. Se existe: lança a compra automaticamente.
4. Se não existe: avisa que esse item precisa ser mapeado uma vez (veja
   mapear_novo_produto.py).

Uso: python nfe_import.py caminho/da/nota.xml
"""

import sys
import xml.etree.ElementTree as ET

import crud

# Namespace padrão dos XMLs de NF-e
NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def extrair_dados_nfe(caminho_xml: str) -> dict:
    """Extrai fornecedor, data e itens de um XML de NF-e."""
    tree = ET.parse(caminho_xml)
    root = tree.getroot()

    inf_nfe = root.find(".//nfe:infNFe", NS)
    if inf_nfe is None:
        raise ValueError("XML não parece ser uma NF-e válida (tag infNFe não encontrada).")

    # Dados do emitente (fornecedor)
    emit = inf_nfe.find("nfe:emit", NS)
    fornecedor_cnpj = emit.findtext("nfe:CNPJ", default="", namespaces=NS)
    fornecedor_nome = emit.findtext("nfe:xNome", default="", namespaces=NS)

    # Data de emissão
    ide = inf_nfe.find("nfe:ide", NS)
    data_emissao_raw = ide.findtext("nfe:dhEmi", default="", namespaces=NS) or \
        ide.findtext("nfe:dEmi", default="", namespaces=NS)
    data_emissao = data_emissao_raw[:10] if data_emissao_raw else None

    numero_nota = ide.findtext("nfe:nNF", default="", namespaces=NS)

    # Itens
    itens = []
    for det in inf_nfe.findall("nfe:det", NS):
        prod = det.find("nfe:prod", NS)
        itens.append({
            "codigo_produto": prod.findtext("nfe:cProd", default="", namespaces=NS),
            "descricao": prod.findtext("nfe:xProd", default="", namespaces=NS),
            "unidade": prod.findtext("nfe:uCom", default="", namespaces=NS),
            "quantidade": float(prod.findtext("nfe:qCom", default="0", namespaces=NS)),
            "valor_unitario": float(prod.findtext("nfe:vUnCom", default="0", namespaces=NS)),
        })

    return {
        "fornecedor_cnpj": fornecedor_cnpj,
        "fornecedor_nome": fornecedor_nome,
        "numero_nota": numero_nota,
        "data_emissao": data_emissao,
        "itens": itens,
    }


def processar_itens_nfe(dados: dict, fornecedor_cnpj: str) -> tuple:
    """
    Lança as compras dos itens que já têm mapeamento e retorna
    (lancados, nao_mapeados) para quem chamou decidir o que exibir.
    """
    lancados = []
    nao_mapeados = []

    for item in dados["itens"]:
        mapeamento = crud.buscar_mapeamento_nfe(fornecedor_cnpj, item["codigo_produto"])

        if mapeamento:
            quantidade_convertida = item["quantidade"] * mapeamento["fator_conversao"]
            crud.registrar_compra(
                insumo_nome=mapeamento["insumo_nome"],
                quantidade=quantidade_convertida,
                data=dados["data_emissao"],
                fornecedor=dados["fornecedor_nome"],
                observacao=f"Importado da NF-e nº {dados['numero_nota']}",
            )
            lancados.append((item["descricao"], mapeamento["insumo_nome"], quantidade_convertida))
        else:
            nao_mapeados.append(item)

    return lancados, nao_mapeados


def importar_nfe(caminho_xml: str):
    """Lê a nota e lança automaticamente os itens que já têm mapeamento (uso via terminal)."""
    dados = extrair_dados_nfe(caminho_xml)

    print(f"Nota nº {dados['numero_nota']} — {dados['fornecedor_nome']} "
          f"({dados['fornecedor_cnpj']}) — emitida em {dados['data_emissao']}")
    print(f"{len(dados['itens'])} item(ns) encontrado(s) na nota.\n")

    lancados, nao_mapeados = processar_itens_nfe(dados, dados["fornecedor_cnpj"])

    print("✅ Itens lançados automaticamente:")
    if lancados:
        for descricao, insumo_nome, qtd in lancados:
            print(f"  - {descricao}  ->  {insumo_nome}  (+{qtd})")
    else:
        print("  (nenhum)")

    print("\n⚠️  Itens que ainda não têm mapeamento (não foram lançados):")
    if nao_mapeados:
        for item in nao_mapeados:
            print(f"  - código '{item['codigo_produto']}': {item['descricao']} "
                  f"({item['quantidade']} {item['unidade']})")
        print(
            "\nPra lançar esses automaticamente da próxima vez, mapeie-os uma vez com:\n"
            "  crud.mapear_produto_nfe(fornecedor_cnpj, codigo_produto, descricao, "
            "insumo_nome, fator_conversao)\n"
            f"  (fornecedor_cnpj desta nota: {dados['fornecedor_cnpj']})"
        )
    else:
        print("  (nenhum — todos os itens foram reconhecidos!)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python nfe_import.py caminho/da/nota.xml")
        sys.exit(1)
    importar_nfe(sys.argv[1])
