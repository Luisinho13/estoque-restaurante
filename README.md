# 📦 Controle de Estoque para Restaurante

Sistema que substitui a contagem manual semanal de estoque por um
cálculo automático, baseado em compras e vendas — a contagem física
vira apenas uma conferência mensal, não mais a rotina inteira.

## O problema

Em muitos restaurantes, o controle de estoque ainda é feito em planilha,
com contagem física manual toda semana (geralmente às segundas-feiras).
É um processo demorado, repetitivo e sujeito a erro humano.

## A solução

Em vez de contar o estoque físico toda semana, o sistema calcula o
**estoque teórico automaticamente**:

```
estoque atual = última contagem física
              + compras registradas a partir dessa data (inclusive)
              − consumo estimado (vendas × ficha técnica), também a
                partir dessa data (inclusive)
```

A ficha técnica (receita) de cada prato define quanto de cada insumo é
consumido por unidade vendida. Assim, ao lançar as vendas do dia, o
sistema já sabe quanto foi consumido de cada ingrediente — sem precisar
contar nada fisicamente.

A contagem física manual passa a ser necessária **apenas 1x por mês**,
para reconciliar o teórico com o real e identificar perdas, quebras ou
desperdício.

> Importante: a última contagem física é sempre o ponto de partida do
> cálculo. Se uma venda ou compra tiver data anterior à contagem mais
> recente, ela é considerada "já refletida" nessa contagem e não entra
> de novo na conta — por isso a contagem física deve ser lançada com a
> data real em que foi feita, não uma data retroativa.

## Funcionalidades

- Cadastro de insumos (com unidade de medida e estoque mínimo)
- Cadastro de pratos e ficha técnica (receita), com suporte a vários
  insumos por prato numa única tela (de 1 a 10 de uma vez)
- Lançamento manual de compras (entradas de estoque)
- Importação automática de compras via XML de NF-e — produtos do
  fornecedor são mapeados uma vez para um insumo (com fator de
  conversão de unidade), e reconhecidos sozinhos nas próximas notas
- Lançamento de vendas diárias por prato, com aviso e confirmação antes
  de duplicar um lançamento do mesmo prato no mesmo dia
- Painel com estoque teórico atualizado e alerta visual para itens
  abaixo do estoque mínimo
- Registro de contagem física mensal, que vira a nova base do cálculo
- Exclusão de insumo com confirmação (remove em cascata ficha técnica,
  compras e contagens ligadas a ele)

## Tecnologias

- **Python**
- **SQLite** — banco de dados local, sem necessidade de servidor
- **Streamlit** — interface web

## Como rodar

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. Rode o app
streamlit run app.py
```

O app abre automaticamente em `http://localhost:8501`.

## Estrutura do projeto

```
estoque-restaurante/
├── database.py       # criação das tabelas do banco
├── crud.py           # cadastros, lançamentos e cálculo do estoque teórico
├── app.py            # interface Streamlit
├── nfe_import.py      # leitura de XML de NF-e e lançamento automático de compras
├── diagnostico.py     # script auxiliar para inspecionar dados de um prato/insumo
└── requirements.txt  # dependências
```

## Próximos passos (v2)

- Integração com exportação de vendas do PDV (Zig), eliminando o
  lançamento manual das vendas diárias — pendente, sem API pública
  documentada até o momento
- Histórico de perdas por reconciliação (diferença entre teórico e
  contagem física)
- Exportação de relatórios mensais

---

Projeto criado para resolver um problema real de controle de estoque
em um restaurante, com o objetivo de reduzir a contagem física de
semanal para mensal.
