"""
zig_import.py
Lê a planilha de vendas exportada da Zig (PDV) e lança as vendas diárias
automaticamente, no lugar da digitação manual prato a prato.

Como funciona:
1. A planilha vem item a item (uma linha por produto vendido em cada comanda).
   Aqui as linhas são somadas por produto e por dia.
2. Cada produto é identificado pelo SKU da Zig. Na primeira importação o SKU é
   mapeado uma vez para um prato do sistema (ou marcado como ignorado, no caso
   de couvert, itens de loja etc.); nas próximas ele é reconhecido sozinho.
3. As vendas são lançadas substituindo o que já existia naquele dia, então
   reimportar o mesmo relatório corrige o dia em vez de duplicar o lançamento.

Uso: python zig_import.py caminho/da/planilha.xlsx
"""

import sys

import pandas as pd

import crud

COLUNAS_OBRIGATORIAS = ["SKU", "Nome do Produto", "Quantidade"]

# A Zig traz dois campos de data: "Data" é o horário da transação e
# "Data do Evento" é o dia operacional — uma venda às 2h da manhã pertence ao
# movimento da noite anterior, então o dia operacional é o que vale pro estoque.
COLUNA_DATA_PREFERIDA = "Data do Evento"
COLUNA_DATA_ALTERNATIVA = "Data"

COLUNA_DESCONTO = "Valor de Desconto"
COLUNA_TOTAL = "Valor total"


def extrair_vendas_zig(arquivo) -> dict:
    """Lê a planilha e devolve as vendas somadas por produto e por dia."""
    df = pd.read_excel(arquivo, dtype={"SKU": str})
    df.columns = [str(coluna).strip() for coluna in df.columns]

    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise ValueError(
            "A planilha não tem as colunas esperadas da Zig: " + ", ".join(faltando)
        )

    total_linhas = len(df)

    # Cancelamentos e estornos aparecem com outro tipo de transação e não
    # podem entrar na conta de consumo.
    descartadas = 0
    if "Tipo da Transação" in df.columns:
        normais = df["Tipo da Transação"].astype(str).str.strip().str.lower() == "normal"
        descartadas = int((~normais).sum())
        df = df[normais]

    coluna_data = (
        COLUNA_DATA_PREFERIDA if COLUNA_DATA_PREFERIDA in df.columns
        else COLUNA_DATA_ALTERNATIVA
    )
    if coluna_data not in df.columns:
        raise ValueError("A planilha não tem nenhuma coluna de data reconhecível.")

    # Na Zig, prato cancelado nem sempre vira outro tipo de transação: muitas
    # vezes ele fica como "Normal", com desconto igual ao preço e valor total
    # zero. Contado como venda, desconta do estoque um prato que não saiu da
    # cozinha, e a diferença aparece depois como sobra na contagem.
    #
    # O critério é desconto maior que zero E total zero. Só "total zero" não
    # serve: o fondue de chocolate da sequência vem com preço zero e sem
    # desconto, porque está incluído no combo — esse é servido e consome.
    # Desconto parcial também continua contando: é venda com abatimento.
    cancelados = []
    if COLUNA_DESCONTO in df.columns and COLUNA_TOTAL in df.columns:
        desconto = pd.to_numeric(df[COLUNA_DESCONTO], errors="coerce").fillna(0)
        total = pd.to_numeric(df[COLUNA_TOTAL], errors="coerce")
        zerados = (desconto > 0) & (total.abs() < 0.005)
        for _, linha in df[zerados].iterrows():
            data = pd.to_datetime(linha[coluna_data], dayfirst=True, errors="coerce")
            cancelados.append({
                "data": data.strftime("%Y-%m-%d") if pd.notna(data) else "",
                "nome": linha["Nome do Produto"],
                "quantidade": linha["Quantidade"],
                "cliente": linha.get("Cliente", ""),
            })
        df = df[~zerados]

    df = df.assign(
        _data=pd.to_datetime(df[coluna_data], dayfirst=True, errors="coerce"),
        _quantidade=pd.to_numeric(df["Quantidade"], errors="coerce"),
        _sku=df["SKU"].astype(str).str.strip(),
    )
    df = df[df["_data"].notna() & df["_quantidade"].notna() & df["_sku"].ne("")]
    df["_data"] = df["_data"].dt.strftime("%Y-%m-%d")

    agrupado = (
        df.groupby(["_data", "_sku", "Nome do Produto"], as_index=False)["_quantidade"]
        .sum()
        .sort_values(["_data", "_quantidade"], ascending=[True, False])
    )

    linhas = [
        {
            "data": linha["_data"],
            "sku": linha["_sku"],
            "nome": linha["Nome do Produto"],
            "quantidade": int(linha["_quantidade"]),
        }
        for _, linha in agrupado.iterrows()
    ]

    return {
        "linhas": linhas,
        "datas": sorted({linha["data"] for linha in linhas}),
        "total_linhas": total_linhas,
        "descartadas": descartadas,
        "cancelados": cancelados,
        "coluna_data": coluna_data,
    }


def processar_vendas_zig(dados: dict, substituir: bool = True) -> tuple:
    """
    Lança as vendas dos produtos já mapeados e devolve
    (lancadas, ignoradas, nao_mapeadas) para quem chamou decidir o que exibir.
    """
    ignoradas = []
    nao_mapeadas = []
    por_prato = {}  # (prato, data) -> quantidade; SKUs diferentes podem virar o mesmo prato

    for linha in dados["linhas"]:
        mapeamento = crud.buscar_mapeamento_zig(linha["sku"])
        if mapeamento is None:
            nao_mapeadas.append(linha)
        elif mapeamento["ignorar"] or not mapeamento["prato_nome"]:
            ignoradas.append(linha)
        else:
            chave = (mapeamento["prato_nome"], linha["data"])
            por_prato[chave] = por_prato.get(chave, 0) + linha["quantidade"]

    lancadas = []
    for (prato, data), quantidade in sorted(por_prato.items()):
        if substituir:
            crud.substituir_venda_diaria(prato, quantidade, data)
        else:
            crud.registrar_venda_diaria(prato, quantidade, data)
        lancadas.append((prato, data, quantidade))

    return lancadas, ignoradas, nao_mapeadas


def importar_zig(caminho_planilha: str):
    """Lê a planilha e lança as vendas já mapeadas (uso via terminal)."""
    dados = extrair_vendas_zig(caminho_planilha)

    periodo = (
        f"{dados['datas'][0]} a {dados['datas'][-1]}" if len(dados["datas"]) > 1
        else (dados["datas"][0] if dados["datas"] else "sem datas válidas")
    )
    print(f"{dados['total_linhas']} linha(s) na planilha — período: {periodo}")
    if dados["descartadas"]:
        print(f"{dados['descartadas']} linha(s) descartada(s) por não serem transações normais.")
    if dados["cancelados"]:
        print(f"{len(dados['cancelados'])} linha(s) com desconto total ficaram de fora (cancelamento):")
        for c in dados["cancelados"]:
            print(f"  - {c['data']}  {c['nome']} ({c['quantidade']}) · {c['cliente']}")

    lancadas, ignoradas, nao_mapeadas = processar_vendas_zig(dados)

    print("\n✅ Vendas lançadas:")
    for prato, data, quantidade in lancadas:
        print(f"  - {data}  {prato}: {quantidade}")
    if not lancadas:
        print("  (nenhuma)")

    if ignoradas:
        print(f"\n➖ {len(ignoradas)} produto(s) marcados como ignorados (não consomem estoque).")

    print("\n⚠️  Produtos ainda sem mapeamento (não foram lançados):")
    if nao_mapeadas:
        for linha in nao_mapeadas:
            print(f"  - SKU '{linha['sku']}': {linha['nome']} ({linha['quantidade']})")
        print(
            "\nPra lançar esses automaticamente da próxima vez, mapeie-os uma vez com:\n"
            "  crud.mapear_produto_zig(sku, nome_produto, prato_nome=..., ignorar=...)"
        )
    else:
        print("  (nenhum — todos os produtos foram reconhecidos!)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python zig_import.py caminho/da/planilha.xlsx")
        sys.exit(1)
    importar_zig(sys.argv[1])
