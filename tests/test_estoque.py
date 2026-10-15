"""
O cálculo do estoque teórico, que é o que substitui a contagem semanal:

    estoque = última contagem + compras e produções − vendas × ficha
              − gasto das produções − baixas, tudo a partir da contagem (>=)
"""

import pytest

import crud

DIA_DA_CONTAGEM = "2026-10-05"
ANTES = "2026-10-04"
DEPOIS = "2026-10-06"


def estoque(nome):
    return crud.calcular_estoque_teorico(nome)["estoque_atual"]


@pytest.fixture
def parmegiana(banco):
    """Parmegiana leva molho ao sugo; o molho leva tomate.

    Os números são os da cozinha: 0,22 kg de molho por prato, e uma panela
    de 80 kg de tomate que rende 75 kg de molho.
    """
    crud.cadastrar_insumo("Tomate", "kg")
    crud.cadastrar_insumo("Molho ao sugo", "kg", tipo="producao", rendimento=75)
    crud.salvar_ficha_da_producao("Molho ao sugo", [{"insumo": "Tomate", "quantidade": 80}],
                                  rendimento=75)
    crud.cadastrar_prato("Parmegiana")
    crud.salvar_ficha_do_prato("Parmegiana", [{"insumo": "Molho ao sugo", "quantidade": 0.22}])


def test_sem_contagem_parte_do_zero(banco):
    crud.cadastrar_insumo("Arroz", "kg")
    crud.cadastrar_prato("Risoto")
    crud.definir_ficha_tecnica("Risoto", "Arroz", 0.5)
    crud.registrar_compra("Arroz", 10, ANTES)
    crud.registrar_venda_diaria("Risoto", 4, DEPOIS)

    resultado = crud.calcular_estoque_teorico("Arroz")
    assert resultado["estoque_atual"] == 8
    assert resultado["baseline_usada"] == crud.SEM_CONTAGEM


def test_venda_no_dia_da_contagem_e_descontada(banco):
    """O bug do `>`: a venda do próprio dia da contagem não era descontada."""
    crud.cadastrar_insumo("Arroz", "kg")
    crud.cadastrar_prato("Risoto")
    crud.definir_ficha_tecnica("Risoto", "Arroz", 0.5)
    crud.registrar_contagem_fisica("Arroz", 10, DIA_DA_CONTAGEM)
    crud.registrar_venda_diaria("Risoto", 2, DIA_DA_CONTAGEM)

    assert estoque("Arroz") == 9


def test_movimento_anterior_a_contagem_ja_esta_nela(banco):
    crud.cadastrar_insumo("Arroz", "kg")
    crud.registrar_compra("Arroz", 100, ANTES)
    crud.registrar_contagem_fisica("Arroz", 10, DIA_DA_CONTAGEM)
    crud.registrar_compra("Arroz", 5, DEPOIS)

    assert estoque("Arroz") == 15


def test_a_ultima_contagem_e_a_base(banco):
    crud.cadastrar_insumo("Arroz", "kg")
    crud.registrar_contagem_fisica("Arroz", 10, "2026-10-01")
    crud.registrar_compra("Arroz", 3, "2026-10-03")
    crud.registrar_contagem_fisica("Arroz", 7, DIA_DA_CONTAGEM)
    crud.registrar_compra("Arroz", 2, DEPOIS)

    resultado = crud.calcular_estoque_teorico("Arroz")
    assert resultado["estoque_atual"] == 9
    assert resultado["baseline_usada"] == DIA_DA_CONTAGEM


def test_venda_desconta_so_o_primeiro_nivel(parmegiana):
    """Vender a parmegiana tira o molho; o tomate só sai quando o molho é feito."""
    crud.registrar_contagem_fisica("Tomate", 100, DIA_DA_CONTAGEM)
    crud.registrar_contagem_fisica("Molho ao sugo", 10, DIA_DA_CONTAGEM)
    crud.registrar_venda_diaria("Parmegiana", 10, DIA_DA_CONTAGEM)

    assert estoque("Molho ao sugo") == pytest.approx(7.8)
    assert estoque("Tomate") == 100


def test_producao_entra_o_produzido_e_sai_a_receita(parmegiana):
    """O rendimento informado (70, e não os 75 da ficha) não muda o tomate que sai."""
    crud.registrar_contagem_fisica("Tomate", 100, DIA_DA_CONTAGEM)
    crud.registrar_contagem_fisica("Molho ao sugo", 10, DIA_DA_CONTAGEM)
    crud.registrar_producao("Molho ao sugo", receitas=1, quantidade_produzida=70,
                            data=DIA_DA_CONTAGEM)

    assert estoque("Molho ao sugo") == 80
    assert estoque("Tomate") == 20


def test_gasto_da_producao_fica_congelado(parmegiana):
    """Mudar a receita depois não reescreve o que uma leva já gastou."""
    crud.registrar_contagem_fisica("Tomate", 100, DIA_DA_CONTAGEM)
    crud.registrar_producao("Molho ao sugo", receitas=1, quantidade_produzida=75,
                            data=DIA_DA_CONTAGEM)
    crud.salvar_ficha_da_producao("Molho ao sugo", [{"insumo": "Tomate", "quantidade": 90}],
                                  rendimento=75)

    assert estoque("Tomate") == 20


def test_venda_usa_a_ficha_atual(parmegiana):
    """Ao contrário da produção, a venda é recalculada pela ficha de agora."""
    crud.registrar_contagem_fisica("Molho ao sugo", 10, DIA_DA_CONTAGEM)
    crud.registrar_venda_diaria("Parmegiana", 10, DIA_DA_CONTAGEM)
    crud.salvar_ficha_do_prato("Parmegiana", [{"insumo": "Molho ao sugo", "quantidade": 0.3}])

    assert estoque("Molho ao sugo") == 7


def test_producao_sem_ficha_e_recusada(banco):
    crud.cadastrar_insumo("Bechamel", "kg", tipo="producao", rendimento=10)
    with pytest.raises(ValueError, match="ficha de produção"):
        crud.registrar_producao("Bechamel", receitas=1, quantidade_produzida=10,
                                data=DIA_DA_CONTAGEM)


def test_baixa_tira_do_estoque(banco):
    crud.cadastrar_insumo("Vinho", "garrafa")
    crud.registrar_contagem_fisica("Vinho", 12, DIA_DA_CONTAGEM)
    crud.registrar_baixas_em_lote([{"insumo": "Vinho", "quantidade": 1}], DEPOIS,
                                  motivo="Quebra ou derramamento")

    assert estoque("Vinho") == 11


def test_relancar_a_venda_do_dia_substitui(banco):
    """Clicar duas vezes tem que dar o mesmo que clicar uma."""
    crud.cadastrar_insumo("Arroz", "kg")
    crud.cadastrar_prato("Risoto")
    crud.definir_ficha_tecnica("Risoto", "Arroz", 0.5)
    crud.registrar_contagem_fisica("Arroz", 10, DIA_DA_CONTAGEM)
    crud.substituir_venda_diaria("Risoto", 4, DIA_DA_CONTAGEM)
    crud.substituir_venda_diaria("Risoto", 4, DIA_DA_CONTAGEM)

    assert estoque("Arroz") == 8
    assert crud.total_vendido_no_dia("Risoto", DIA_DA_CONTAGEM) == 4


def test_compra_em_lote_e_tudo_ou_nada(banco):
    crud.cadastrar_insumo("Arroz", "kg")
    with pytest.raises(ValueError, match="não encontrado"):
        crud.registrar_compras_em_lote(
            [{"insumo": "Arroz", "quantidade": 5}, {"insumo": "Feijão", "quantidade": 2}],
            DEPOIS,
        )

    assert estoque("Arroz") == 0


def test_abaixo_do_minimo(banco):
    crud.cadastrar_insumo("Arroz", "kg", estoque_minimo=5)
    crud.registrar_contagem_fisica("Arroz", 4, DIA_DA_CONTAGEM)

    assert crud.calcular_estoque_teorico("Arroz")["abaixo_do_minimo"] is True
