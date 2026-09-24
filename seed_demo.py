"""
seed_demo.py
Gera um banco de demonstração com dados realistas de um restaurante:
60 dias de vendas, compras, produções, ficha técnica e contagens físicas.

Serve para ver o dashboard cheio (e tirar print para divulgação) sem
encostar no banco real. Rodar com:

    python seed_demo.py
    ESTOQUE_DB=estoque_demo.db streamlit run app.py

O banco de demonstração é recriado do zero a cada execução, e junto com
ele um usuário admin de demonstração (demo / demo1234) para conseguir
entrar no app.
"""

import datetime
import os
import random
import pathlib
from pathlib import Path

CAMINHO_DEMO = Path(__file__).parent / "estoque_demo.db"

# O banco é recriado do zero a cada execução, o que apaga também os
# usuários. Sem recriar um admin aqui, ninguém consegue entrar na
# demonstração depois de gerá-la. Credencial fictícia, banco fictício.
USUARIO_DEMO = "demo"
SENHA_DEMO = "demo1234"
os.environ["ESTOQUE_DB"] = str(CAMINHO_DEMO)

# ESTOQUE_DB sozinho NÃO basta: ele só escolhe o *arquivo* do SQLite. Se
# houver credencial de Postgres no ambiente ou nos secrets — e na máquina
# de quem desenvolve o app real, há —, o database.py escolhe o Postgres e
# ignora o caminho acima. Este script já chegou a inserir insumos
# fictícios no banco do restaurante por causa disso.
#
# MODO_DEMO é o cinto de segurança que existe justamente para isso: com
# ele ligado, url_do_postgres() devolve None aconteça o que acontecer.
# Precisa vir antes do import do database, porque a escolha do banco é
# congelada na primeira vez que é feita.
os.environ["MODO_DEMO"] = "1"

import auth  # noqa: E402
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
    ("Molho de tomate", "kg"),
]

# Itens feitos na cozinha. Entram pela produção, não pela compra, e a
# produção é que tira o tomate e a cebola do estoque — a pizza desconta só
# o molho.
PRODUCOES = {
    "Molho de tomate": {
        "rendimento": 5.0,
        "receita": {"Tomate": 6.0, "Cebola": 1.0, "Alho": 0.1, "Azeite": 0.2},
    },
}
# De quantos em quantos dias a cozinha faz o molho.
INTERVALO_DE_PRODUCAO = 3

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
        "Farinha de trigo": 0.30, "Queijo mussarela": 0.20, "Molho de tomate": 0.12,
        "Azeite": 0.02,
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

# Quanto some entre uma contagem e a outra, como fração do que estava
# disponível. Quebra, desperdício, porção maior que a ficha. Os três
# primeiros são os problemáticos — hortifruti e laticínio estragam, e
# proteína cara costuma sair da porção. O resto fica na faixa saudável de
# 1% a 4%, que é o que um restaurante bem tocado costuma perder.
PERDA_NO_PERIODO = {
    "Tomate": 0.11,
    "Alface": 0.14,
    "Queijo mussarela": 0.08,
    "Camarão": 0.07,
}
PERDA_PADRAO = (0.01, 0.04)

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


def _no_intervalo(data, inicio, fim):
    return data >= inicio and (fim is None or data < fim)


def gerar_producoes(vendas):
    """Levas de cada produção, feitas a cada poucos dias no volume que as
    vendas dos dias seguintes vão pedir, arredondado para meia receita."""
    levas = []
    for producao, dados in PRODUCOES.items():
        inicio = DIA_CONTAGEM_ANTERIOR
        while inicio <= HOJE:
            fim = inicio + datetime.timedelta(days=INTERVALO_DE_PRODUCAO)
            pedido = sum(
                quantidade * FICHAS[prato].get(producao, 0)
                for prato, quantidade, data in vendas
                if _no_intervalo(data, inicio, fim)
            )
            receitas = max(round(pedido / dados["rendimento"] * 2) / 2, 0.5)
            rendeu = round(receitas * dados["rendimento"] * random.uniform(0.95, 1.03), 2)
            levas.append((producao, receitas, rendeu, inicio))
            inicio = fim
    return levas


def consumo_entre(vendas, inicio, fim=None, levas=()):
    """Consumo de cada insumo no intervalo [inicio, fim).

    Soma o que as vendas tiram (pela ficha do prato) e o que as produções
    gastam dos ingredientes. O fim é exclusivo de propósito: uma contagem
    mede o estoque antes dos movimentos do próprio dia, então as vendas do
    dia da contagem final já pertencem ao período seguinte. É a mesma
    convenção do crud.py.
    """
    total = {}
    for prato, quantidade, data in vendas:
        if not _no_intervalo(data, inicio, fim):
            continue
        for insumo, por_prato in FICHAS[prato].items():
            total[insumo] = total.get(insumo, 0) + quantidade * por_prato
    for producao, receitas, _, data in levas:
        if not _no_intervalo(data, inicio, fim):
            continue
        for insumo, por_receita in PRODUCOES[producao]["receita"].items():
            total[insumo] = total.get(insumo, 0) + receitas * por_receita
    return total


def produzido_entre(levas, producao, inicio, fim=None):
    return sum(r for p, _, r, d in levas if p == producao and _no_intervalo(d, inicio, fim))


def consumo_desde(vendas, inicio, levas=()):
    """Atalho para o consumo de uma data em diante."""
    return consumo_entre(vendas, inicio, levas=levas)


def arredondar(valor, unidade):
    return float(round(valor / 10) * 10) if unidade == "un" else round(valor, 1)


def gerar_compras(insumo, unidade, alvo, inicio=None, duracao=30):
    """Divide o total comprado em 3 a 5 entregas espalhadas pelo período.

    Devolve quanto foi efetivamente comprado — o arredondamento faz o total
    entregue diferir do alvo, e quem fecha a conta da contagem precisa do
    número real, não do pretendido.
    """
    inicio = inicio or DIA_CONTAGEM
    entregas = random.randint(3, 5)
    dias = sorted(random.sample(range(1, duracao), entregas))
    por_entrega = alvo / entregas
    comprado = 0.0
    for dia in dias:
        quantidade = arredondar(por_entrega * random.uniform(0.85, 1.15), unidade)
        if quantidade > 0:
            crud.registrar_compra(
                insumo,
                quantidade,
                str(inicio + datetime.timedelta(days=dia)),
                FORNECEDOR[insumo],
            )
            comprado += quantidade
    return comprado


def main():
    if CAMINHO_DEMO.name != "estoque_demo.db":
        raise SystemExit("Este script só recria o banco de demonstração.")

    # Segunda tranca, conferindo o que o database.py realmente decidiu.
    # A primeira (MODO_DEMO, lá em cima) deve bastar; esta existe porque o
    # estrago aqui é apagar e reescrever um banco, e o preço de conferir é
    # nenhum.
    if database.backend() != "sqlite":
        raise SystemExit(
            f"Abortado: o banco configurado é '{database.backend()}', não SQLite. "
            "Este script apaga e recria o banco de demonstração e nunca deve "
            "tocar no banco real."
        )
    if pathlib.Path(database.DB_PATH).resolve() != CAMINHO_DEMO.resolve():
        raise SystemExit(
            f"Abortado: o SQLite apontado é '{database.DB_PATH}', e não o "
            f"banco de demonstração '{CAMINHO_DEMO}'."
        )

    CAMINHO_DEMO.unlink(missing_ok=True)
    database.criar_tabelas()

    vendas = gerar_vendas()
    levas = gerar_producoes(vendas)
    consumo_periodo = consumo_desde(vendas, DIA_CONTAGEM, levas)
    # O primeiro período é o que a tela de perdas reconcilia, então ele
    # precisa fechar de verdade: estoque inicial, compras e vendas que se
    # combinam, e uma perda plausível explicando o que falta.
    consumo_anterior = consumo_entre(vendas, DIA_CONTAGEM_ANTERIOR, DIA_CONTAGEM, levas)

    for nome, unidade in INSUMOS:
        media_diaria = consumo_periodo.get(nome, 0) / 30
        crud.cadastrar_insumo(
            nome, unidade, arredondar(media_diaria * DIAS_DE_MINIMO, unidade),
            tipo="producao" if nome in PRODUCOES else "cru",
        )
    for producao, dados in PRODUCOES.items():
        crud.salvar_ficha_da_producao(
            producao,
            [{"insumo": i, "quantidade": q} for i, q in dados["receita"].items()],
            dados["rendimento"],
        )

    for prato, ficha in FICHAS.items():
        crud.cadastrar_prato(prato)
        for insumo, quantidade in ficha.items():
            crud.definir_ficha_tecnica(prato, insumo, quantidade)

    for prato, quantidade, data in vendas:
        crud.registrar_venda_diaria(prato, quantidade, str(data))
    for producao, receitas, rendeu, data in levas:
        crud.registrar_producao(producao, receitas, rendeu, str(data))

    for nome, unidade in INSUMOS:
        media_diaria = consumo_periodo.get(nome, 0) / 30
        inicial = arredondar(media_diaria * DIAS_NA_CONTAGEM, unidade)
        crud.registrar_contagem_fisica(
            nome, inicial, str(DIA_CONTAGEM_ANTERIOR), "Contagem mensal"
        )

        # Primeiro período: compra para repor o que foi consumido, e o que
        # sobra na contagem seguinte é o que restou depois da perda.
        gasto = consumo_anterior.get(nome, 0)
        if nome in PRODUCOES:
            # O que é feito na cozinha não se compra: entrou pelas levas.
            comprado = produzido_entre(levas, nome, DIA_CONTAGEM_ANTERIOR, DIA_CONTAGEM)
        else:
            comprado = gerar_compras(
                nome, unidade, gasto * random.uniform(0.95, 1.15),
                inicio=DIA_CONTAGEM_ANTERIOR,
                duracao=(DIA_CONTAGEM - DIA_CONTAGEM_ANTERIOR).days,
            )
        disponivel = inicial + comprado
        taxa = PERDA_NO_PERIODO.get(nome, random.uniform(*PERDA_PADRAO))
        sobra = max(disponivel - gasto - disponivel * taxa, 0)
        crud.registrar_contagem_fisica(
            nome, arredondar(sobra, unidade), str(DIA_CONTAGEM), "Contagem mensal"
        )

        # Segundo período: em aberto, é o que alimenta o "o que acaba primeiro".
        if nome in PRODUCOES:
            continue
        proporcao = COMPRA_ABAIXO_DO_CONSUMO.get(nome, random.uniform(1.0, 1.25))
        gerar_compras(nome, unidade, consumo_periodo.get(nome, 0) * proporcao)

    auth.cadastrar_usuario(
        USUARIO_DEMO, SENHA_DEMO, nome="Usuário de demonstração",
        papel="admin", status="aprovado", areas=list(auth.AREAS),
    )

    print(f"Banco de demonstração criado em: {CAMINHO_DEMO}")
    print(f"Entre no app com  usuário: {USUARIO_DEMO}  senha: {SENHA_DEMO}")
    print(f"{len(INSUMOS)} insumos, {len(FICHAS)} pratos, {len(vendas)} lançamentos de venda, "
          f"{len(levas)} produções\n")
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
