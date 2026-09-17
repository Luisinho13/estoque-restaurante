"""
seed_demo.py
Gera um banco de demonstração com dados realistas de um restaurante:
60 dias de vendas, compras, ficha técnica e contagens físicas.

Serve para ver o dashboard cheio (e tirar print para divulgação) sem
encostar no banco real. Rodar com:

    python seed_demo.py
    ESTOQUE_DB=estoque_demo.db streamlit run app.py

O banco de demonstração é recriado do zero a cada execução.
"""

import datetime
import os
import random
from pathlib import Path

CAMINHO_DEMO = Path(__file__).parent / "estoque_demo.db"
os.environ["ESTOQUE_DB"] = str(CAMINHO_DEMO)

import crud  # noqa: E402  (precisa enxergar o ESTOQUE_DB definido acima)
import database  # noqa: E402

random.seed(42)

HOJE = datetime.date.today()
DIAS_HISTORICO = 60
DIA_CONTAGEM = HOJE - datetime.timedelta(days=30)
DIA_CONTAGEM_ANTERIOR = HOJE - datetime.timedelta(days=DIAS_HISTORICO)

# Quantos dias de consumo o estoque mínimo representa, e quanto sobrou na
# última contagem. É daqui que sai o "semáforo" do dashboard.
DIAS_DE_MINIMO = 5
DIAS_NA_CONTAGEM = 12

INSUMOS = [
    ("Contrafilé", "kg"),
    ("Peito de frango", "kg"),
    ("Camarão", "kg"),
    ("Arroz", "kg"),
    ("Feijão preto", "kg"),
    ("Batata", "kg"),
    ("Queijo mussarela", "kg"),
    ("Tomate", "kg"),
    ("Cebola", "kg"),
    ("Alho", "kg"),
    ("Azeite", "l"),
    ("Óleo de soja", "l"),
    ("Farinha de trigo", "kg"),
    ("Manteiga", "kg"),
    ("Cerveja long neck", "un"),
    ("Refrigerante lata", "un"),
]

FICHAS = {
    "Picanha na chapa": {
        "Contrafilé": 0.35, "Batata": 0.25, "Alho": 0.005, "Óleo de soja": 0.02,
    },
    "Frango grelhado": {
        "Peito de frango": 0.25, "Arroz": 0.15, "Feijão preto": 0.10,
        "Óleo de soja": 0.02, "Alho": 0.004,
    },
    "Risoto de camarão": {
        "Camarão": 0.18, "Arroz": 0.12, "Manteiga": 0.03, "Queijo mussarela": 0.04,
        "Azeite": 0.01, "Alho": 0.006,
    },
    "Executivo do dia": {
        "Peito de frango": 0.20, "Arroz": 0.15, "Feijão preto": 0.10,
        "Batata": 0.15, "Cebola": 0.03, "Alho": 0.003,
    },
    "Porção de batata frita": {"Batata": 0.40, "Óleo de soja": 0.05},
    "Pizza margherita": {
        "Farinha de trigo": 0.30, "Queijo mussarela": 0.20, "Tomate": 0.15, "Azeite": 0.02,
    },
    "Hambúrguer artesanal": {
        "Contrafilé": 0.18, "Queijo mussarela": 0.04, "Farinha de trigo": 0.08,
        "Tomate": 0.03, "Cebola": 0.02, "Alho": 0.003,
    },
    "Cerveja long neck": {"Cerveja long neck": 1},
    "Refrigerante": {"Refrigerante lata": 1},
}

# Média de vendas por dia em dia de semana comum.
VOLUME_BASE = {
    "Picanha na chapa": 14,
    "Frango grelhado": 18,
    "Risoto de camarão": 9,
    "Executivo do dia": 32,
    "Porção de batata frita": 22,
    "Pizza margherita": 16,
    "Hambúrguer artesanal": 20,
    "Cerveja long neck": 70,
    "Refrigerante": 45,
}

# Segunda a domingo: movimento sobe na sexta e no sábado.
FATOR_DIA_SEMANA = [0.90, 0.95, 1.00, 1.10, 1.45, 1.60, 1.15]

# Insumos comprados abaixo do consumo no período — são os que acendem
# alerta no dashboard, que é justamente o que o sistema serve para pegar.
COMPRA_ABAIXO_DO_CONSUMO = {
    "Camarão": 0.75,
    "Alho": 0.72,
    "Queijo mussarela": 0.78,
    "Manteiga": 0.80,
}

FORNECEDOR = {
    "Contrafilé": "Frigorífico Boi Bom",
    "Peito de frango": "Frigorífico Boi Bom",
    "Camarão": "Pescados Litoral",
    "Arroz": "Distribuidora Central",
    "Feijão preto": "Distribuidora Central",
    "Batata": "Hortifruti São João",
    "Queijo mussarela": "Laticínios Serra Azul",
    "Tomate": "Hortifruti São João",
    "Cebola": "Hortifruti São João",
    "Alho": "Hortifruti São João",
    "Azeite": "Distribuidora Central",
    "Óleo de soja": "Distribuidora Central",
    "Farinha de trigo": "Distribuidora Central",
    "Manteiga": "Laticínios Serra Azul",
    "Cerveja long neck": "Atacadão Bebidas",
    "Refrigerante lata": "Atacadão Bebidas",
}


def gerar_vendas():
    """Vendas diárias dos últimos 60 dias, com variação por dia da semana."""
    vendas = []
    for offset in range(DIAS_HISTORICO):
        data = HOJE - datetime.timedelta(days=DIAS_HISTORICO - 1 - offset)
        fator = FATOR_DIA_SEMANA[data.weekday()]
        for prato, base in VOLUME_BASE.items():
            quantidade = round(random.gauss(base * fator, base * 0.18))
            if quantidade > 0:
                vendas.append((prato, quantidade, data))
    return vendas


def consumo_desde(vendas, inicio):
    """Quanto de cada insumo as vendas consomem a partir de uma data."""
    total = {}
    for prato, quantidade, data in vendas:
        if data < inicio:
            continue
        for insumo, por_prato in FICHAS[prato].items():
            total[insumo] = total.get(insumo, 0) + quantidade * por_prato
    return total


def arredondar(valor, unidade):
    return float(round(valor / 10) * 10) if unidade == "un" else round(valor, 1)


def gerar_compras(insumo, unidade, alvo):
    """Divide o total comprado em 3 a 5 entregas espalhadas pelo período."""
    entregas = random.randint(3, 5)
    dias = sorted(random.sample(range(1, 30), entregas))
    por_entrega = alvo / entregas
    for dia in dias:
        quantidade = arredondar(por_entrega * random.uniform(0.85, 1.15), unidade)
        if quantidade > 0:
            crud.registrar_compra(
                insumo,
                quantidade,
                str(DIA_CONTAGEM + datetime.timedelta(days=dia)),
                FORNECEDOR[insumo],
            )


def main():
    if CAMINHO_DEMO.name != "estoque_demo.db":
        raise SystemExit("Este script só recria o banco de demonstração.")
    CAMINHO_DEMO.unlink(missing_ok=True)
    database.criar_tabelas()

    vendas = gerar_vendas()
    consumo_periodo = consumo_desde(vendas, DIA_CONTAGEM)

    for nome, unidade in INSUMOS:
        media_diaria = consumo_periodo.get(nome, 0) / 30
        crud.cadastrar_insumo(nome, unidade, arredondar(media_diaria * DIAS_DE_MINIMO, unidade))

    for prato, ficha in FICHAS.items():
        crud.cadastrar_prato(prato)
        for insumo, quantidade in ficha.items():
            crud.definir_ficha_tecnica(prato, insumo, quantidade)

    for prato, quantidade, data in vendas:
        crud.registrar_venda_diaria(prato, quantidade, str(data))

    for nome, unidade in INSUMOS:
        media_diaria = consumo_periodo.get(nome, 0) / 30
        contado = arredondar(media_diaria * DIAS_NA_CONTAGEM, unidade)
        crud.registrar_contagem_fisica(
            nome, contado, str(DIA_CONTAGEM_ANTERIOR), "Contagem mensal"
        )
        crud.registrar_contagem_fisica(nome, contado, str(DIA_CONTAGEM), "Contagem mensal")

        proporcao = COMPRA_ABAIXO_DO_CONSUMO.get(nome, random.uniform(1.0, 1.25))
        gerar_compras(nome, unidade, consumo_periodo.get(nome, 0) * proporcao)

    print(f"Banco de demonstração criado em: {CAMINHO_DEMO}")
    print(f"{len(INSUMOS)} insumos, {len(FICHAS)} pratos, {len(vendas)} lançamentos de venda\n")
    print(f"{'Insumo':<20} {'Estoque':>9} {'Mínimo':>9} {'Dias':>7}  Status")
    for linha in sorted(
        crud.cobertura_estoque(30),
        key=lambda linha: linha["dias_restantes"] if linha["dias_restantes"] is not None else 1e6,
    ):
        dias = linha["dias_restantes"]
        status = "ABAIXO DO MINIMO" if linha["abaixo_do_minimo"] else "ok"
        print(
            f"{linha['insumo']:<20} {linha['estoque_atual']:>9.1f} "
            f"{linha['estoque_minimo']:>9.1f} {dias if dias is not None else '-':>7}  {status}"
        )


if __name__ == "__main__":
    main()
