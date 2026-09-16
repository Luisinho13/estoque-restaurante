# 📦 Controle de Estoque para Restaurante

Sistema que substitui a contagem manual semanal de estoque por um
cálculo automático, baseado em compras e vendas — a contagem física
física vira apenas uma conferência mensal, não mais a rotina inteira.

## O problema

Em muitos restaurantes, o controle de estoque ainda é feito em planilha,
com contagem física manual toda semana (geralmente às segundas-feiras).
É um processo demorado, repetitivo e sujeito a erro humano.

## A solução

Em vez de contar o estoque físico toda semana, o sistema calcula o
**estoque teórico automaticamente**:

```
estoque atual = última contagem física
              + compras registradas depois dela
              − consumo estimado (vendas × ficha técnica)
```

A ficha técnica (receita) de cada prato define quanto de cada insumo é
consumido por unidade vendida. Assim, ao lançar as vendas do dia, o
sistema já sabe quanto foi consumido de cada ingrediente — sem precisar
contar nada fisicamente.

A contagem física manual passa a ser necessária **apenas 1x por mês**,
para reconciliar o teórico com o real e identificar perdas, quebras ou
desperdício.

## Funcionalidades

- Cadastro de insumos (com unidade de medida e estoque mínimo)
- Cadastro de pratos e ficha técnica (receita)
- Lançamento de compras (entradas de estoque)
- Lançamento de vendas diárias por prato
- Painel com estoque teórico atualizado e alerta visual para itens
  abaixo do estoque mínimo
- Registro de contagem física mensal, que vira a nova base do cálculo

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
└── requirements.txt  # dependências
```

## Próximos passos (v2)

- Integração com exportação de vendas do PDV, eliminando o lançamento
  manual das vendas diárias
- Histórico de perdas por reconciliação (diferença entre teórico e
  contagem física)
- Exportação de relatórios mensais

---

Projeto criado para resolver um problema real de controle de estoque
em um restaurante, com o objetivo de reduzir a contagem física de
semanal para mensal.
