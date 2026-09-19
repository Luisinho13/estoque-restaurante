# 📦 Controle de Estoque para Restaurante

Substitui a contagem manual semanal de estoque por um cálculo automático
a partir de compras e vendas. A contagem física deixa de ser a rotina de
toda segunda-feira e vira uma conferência mensal.

Projeto pessoal, criado para um problema real do restaurante onde
trabalho como comprador.

**O sistema está no ar:**
https://estoque-restaurante-2zcsdq2cje4ayn4hyvrtdw.streamlit.app

O link é público, o sistema não — o acesso continua por login.

![Dashboard do sistema](docs/dashboard.png)

> As telas deste README usam o banco de demonstração gerado por
> `seed_demo.py`, com dados fictícios.

## O problema

O controle era uma planilha e uma contagem física toda semana: alguém
percorria o estoque item por item, anotava tudo e digitava. Demorado,
repetitivo e fácil de errar — e, no fim, respondia "quanto eu tenho",
quando a pergunta que importa para comprar é **"o que vai acabar
primeiro"**.

## A ideia

Se eu sei o que entrou e o que saiu, eu sei o que sobrou. Não preciso
contar toda semana.

```
estoque atual = última contagem física
              + compras registradas a partir dessa data (inclusive)
              − consumo (vendas × ficha técnica), também a partir
                dessa data (inclusive)
```

A ficha técnica de cada prato diz quanto de cada insumo é consumido por
unidade vendida. Com as vendas do dia lançadas, o sistema já sabe quanto
saiu de cada ingrediente.

A contagem física continua existindo, **1x por mês**, com outro papel:
ela é o ponto de partida do cálculo e a forma de medir perda, quebra e
desperdício — a diferença entre o teórico e o real.

> A última contagem é sempre a base. Uma venda ou compra anterior a ela
> é considerada já refletida naquela contagem e não entra na conta de
> novo. Por isso a contagem precisa ser lançada com a data real em que
> foi feita, nunca retroativa.

## O que a contagem mensal revela

O cálculo automático diz quanto *deveria* haver. A contagem física diz
quanto há. A diferença entre os dois é a informação mais cara do
estoque, e ela não aparece em nenhum dos dois números isolados.

Entre duas contagens, tudo que estava disponível teve um de três
destinos, e os três somam exatamente 100%:

```
disponível  =  estoque da contagem anterior + compras do período
disponível  =  usado (vendas × ficha técnica)
             + sobra (contagem atual)
             + perda (o que falta para fechar)
```

A perda é o que não se explica por venda nem por sobra: quebra, produto
estragado, porção servida maior que a da ficha técnica, furo. Um
restaurante bem tocado perde de 1% a 4%; acima de 5% há o que investigar.

Ver isso **por insumo e em percentual** muda a conversa. "Perdemos 12 kg
de tomate" é um número solto. "11% do tomate que entrou foi para o lixo,
contra 1,5% da batata" aponta direto para onde olhar — e quanto custa
não olhar.

## O que o sistema faz

**Entradas de estoque**
- Lançamento manual de compras
- Importação por **XML de NF-e**: cada produto do fornecedor é mapeado
  uma vez para um insumo, com fator de conversão quando a unidade da
  nota não bate com a unidade controlada (caixa → unidade, por exemplo).
  Nas próximas notas do mesmo fornecedor, o produto é reconhecido sozinho

**Cadastros**
- Insumo, prato e ficha técnica um a um, pelo formulário
- Importação das **planilhas de ficha técnica** da cozinha (a de pratos
  finais e a de produção): cada aba vira um prato, e as receitas de
  produção — molhos, bases, bolinhos — são abertas nos ingredientes de
  compra, para o consumo cair em cima do que entra pela nota fiscal.
  Nada é gravado antes da prévia, que mostra o que vai ser criado e cada
  ponto em que a planilha estava ambígua

**Saídas de estoque**
- Importação das vendas do **PDV (Zig)** a partir da planilha exportada:
  as linhas item a item são somadas por produto e por dia, e cada SKU é
  ligado uma vez a um prato — ou marcado como "não controlar", no caso de
  couvert, bebida e itens de loja
- Lançamento manual por prato, com confirmação antes de somar um segundo
  lançamento do mesmo prato no mesmo dia

**Conferência**
- **Dashboard** com indicadores do período, consumo por insumo, curva de
  vendas por dia, ranking de pratos e movimentações recentes
- **"O que acaba primeiro"**: estimativa de em quantos dias cada insumo
  acaba (estoque ÷ consumo médio diário), com semáforo de status. É a
  tela que responde o que precisa ser comprado antes de faltar
- Registro da contagem física mensal, que vira a nova base do cálculo
- **Perdas e Reconciliação**: entre duas contagens, quanto de cada insumo
  virou venda, quanto sobrou e quanto se perdeu — em quantidade e em
  percentual do que estava disponível

![Tela "O que acaba primeiro"](docs/o-que-acaba-primeiro.png)

## Acesso e usuários

O sistema tem login. A primeira tela pede usuário e senha, e nenhuma
página é montada antes disso — quem não entrou não chega a lugar nenhum.

**O cadastro é aberto, a entrada não.** Qualquer pessoa pode pedir acesso
pela aba "Criar cadastro", mas o pedido nasce *pendente*: a senha até
confere no login, só que a entrada fica barrada até um administrador
aprovar. Isso mantém o controle de quem usa o sistema sem obrigar o
administrador a criar conta para cada pessoa na mão.

**Cada um enxerga só o que é dele.** Ao aprovar um cadastro, o
administrador marca quais das onze áreas aquela pessoa vai acessar —
Dashboard, Painel de Estoque, Perdas e Reconciliação, Insumos, Pratos,
Ficha Técnica, Lançar Compra, Importar Nota Fiscal, Importar Vendas
(PDV), Lançar Venda do Dia e Contagem Física. A sugestão inicial é só as duas primeiras: consulta,
sem mexer no estoque.

O filtro não é cosmético. As páginas de áreas não liberadas nem chegam a
ser registradas na navegação, então não adianta digitar a URL — a rota
não existe para aquele usuário. Esconder apenas o item do menu seria
fachada.

**Telas de administração** (só para quem é admin):

- *Aprovação de cadastros* — a fila de pendentes, com as áreas já
  escolhidas antes de liberar. Dá para recusar, e reconsiderar depois
- *Usuários e acessos* — cada usuário em um cartão, com suas áreas em
  caixas de seleção, além de promover a administrador, redefinir senha e
  excluir. Tem também um atalho para criar um usuário já aprovado

**Telas de usuário** (todos): *Minha conta* mostra o perfil, as áreas
liberadas e permite trocar a própria senha.

> As senhas nunca são gravadas em texto puro. Cada usuário tem um salt
> aleatório e o que fica no banco é o PBKDF2-SHA256 da senha com esse
> salt, conferido com `compare_digest`. Um vazamento do arquivo do banco
> não entrega as senhas.

Uma trava vale nota: **não é possível remover o último administrador.** O
botão de rebaixar fica desabilitado quando só existe um admin aprovado.
Sem isso, um clique deixaria o sistema sem ninguém capaz de aprovar
cadastros ou liberar acessos, e não haveria como voltar pela interface.

## Onde os dados ficam

O sistema roda sobre dois bancos e escolhe sozinho qual usar:

- **SQLite**, um arquivo local, quando não há nada configurado. É o modo
  de quem está desenvolvendo ou rodando tudo na própria máquina.
- **PostgreSQL**, quando existe uma URL de conexão nos secrets. É o modo
  da nuvem.

O resto do código não sabe qual dos dois está embaixo. `get_connection()`
devolve nos dois casos um objeto com a mesma interface, e as diferenças de
dialeto — inclusive a tradução dos `?` para `%s` — ficam todas dentro do
`database.py`. As consultas continuam escritas uma vez só.

**Por que sair do arquivo.** O disco do Streamlit Community Cloud é
efêmero: a documentação avisa que arquivos locais podem ser apagados a
qualquer momento, e o container é reconstruído a partir do repositório
quando o app reinicia. Um `estoque.db` lá dentro sumiria levando junto
tudo o que o restaurante tivesse lançado. Um sistema de estoque que
esquece o estoque não é um sistema de estoque.

O `migrar_para_nuvem.py` copia o arquivo local para o Postgres. Ele
preserva os ids — a ficha técnica aponta para prato e insumo por id, e
renumerar quebraria as ligações — ajusta as sequências do Postgres para
não colidirem com os ids já usados, e se recusa a rodar sobre um destino
que já tenha dados, para não misturar duas cargas.

## Problemas que enfrentamos

Esta é a parte que normalmente não aparece num README, e é a que mais
ensinou. Cada item traz o sintoma, a causa real e o que resolveu.

### No cálculo do estoque

**O estoque ignorava as vendas do dia da contagem.** Logo depois de
registrar uma contagem física, o estoque aparecia maior do que era. A
causa estava numa única letra: a consulta somava compras e descontava
consumo com `data > contagem`, e não `>=`. As vendas feitas no mesmo dia
da contagem caíam fora da conta e simplesmente sumiam. Trocar `>` por
`>=` resolveu. É um erro que não dá erro — o sistema segue rodando e
entregando um número errado com toda a confiança.

**Um prato descontava 3 em vez de 1.** O sintoma era o estoque caindo o
triplo do esperado depois de lançar uma venda. A ficha técnica estava
certa (a tabela tem `UNIQUE(prato_id, insumo_id)`, o que descarta ficha
duplicada), e a conta também. O problema estava nos dados: reenviar o
formulário — um clique duplo, um F5 — inseria várias linhas idênticas em
`vendas_diarias`, e cada uma descontava do estoque. Hoje o app checa se
já existe lançamento para aquele prato naquele dia e pede confirmação
explícita antes de somar por cima. A importação do PDV segue a mesma
ideia por outro caminho: ela **substitui** as vendas do dia em vez de
somar, então reimportar o mesmo relatório corrige o dia sem duplicar
nada.

> Vale o registro honesto: o caso nunca foi reproduzido em condições
> controladas. Quando o banco foi inspecionado, já estava consistente. A
> correção ataca a causa mais provável, e o sintoma não voltou — mas se
> voltar, o primeiro lugar a olhar é se há várias linhas em
> `vendas_diarias` para o mesmo prato e a mesma data.

**O dashboard acusava erro onde não havia.** Todo insumo sem nenhuma
contagem física parte do zero, então a primeira venda já o deixa
negativo. Isso é o comportamento esperado, não um defeito. Só que o
alerta era o mesmo do negativo de verdade, e mandava procurar compra não
lançada ou ficha técnica errada quando faltava apenas registrar a
contagem inicial. Os dois casos agora são contados e exibidos separados.

### Na importação de dados

**`Fe` e `FE` são produtos diferentes.** Os códigos de produto do PDV
diferenciam maiúsculas de minúsculas: um é Arroz Extra, o outro é Pão
Extra. O instinto de normalizar tudo para maiúscula ao comparar faria um
sobrescrever o outro em silêncio, sem erro nenhum — o sistema continuaria
funcionando, descontando pão toda vez que alguém pedisse arroz. O SKU é
tratado como identificador, não como texto.

**A coluna de data óbvia é a errada.** A planilha do PDV traz o horário
da transação e também o dia operacional. Uma venda às 2h da manhã
pertence ao movimento da noite anterior. Usar a data da transação jogaria
esse consumo para o dia seguinte, desalinhando o estoque de todas as
madrugadas. Vale o dia operacional.

**A coluna "Unidade" da ficha técnica mente.** A planilha da cozinha
escreve "Gr" em linhas cujo valor é 0,18 e cujo custo bate com o preço
por quilo. A quantidade está sempre na unidade base, qualquer que seja o
rótulo — ler a coluna ao pé da letra deixaria toda ficha mil vezes
errada. O importador ignora o rótulo e avisa quando ele discorda do
insumo.

**Ficha que cita a si mesma.** Várias abas de "extra" do cardápio
consomem um ingrediente com o nome da própria aba: "Bombom de Alcatra"
gasta 0,18 kg de "Bombom de Alcatra". Tratar isso como subreceita entra
em laço infinito — e, na primeira versão, com a proteção ingênua de
comparar nomes, fazia a alcatra do prato cair de 0,18 kg para 0,032 kg,
porque a quantidade era multiplicada por si mesma. Hoje só receita de
produção serve de subreceita, e a identidade na pilha é o objeto da
receita, não o nome: "Brownie" existe nas duas planilhas, e o prato
Brownie de fato consome a produção Brownie.

**Rendimento digitado errado infla o consumo.** A receita da farofa
declara render 0,03 kg a partir de 1,53 kg de ingredientes. Como a
explosão da subreceita divide pelo rendimento, esse campo multiplicaria
o consumo por cinquenta. Quando o rendimento declarado é menor que 60%
da soma dos ingredientes, vale a soma — e o caso aparece na prévia para
ser corrigido na planilha.

**Um mapeamento errado era definitivo.** A tela de importação mostrava
apenas os produtos ainda não mapeados. Quem ligasse um produto ao prato
errado não tinha como voltar atrás pela interface — só apagando o prato
inteiro. Hoje a tela lista também os mapeamentos já salvos e permite
trocar o prato, marcar o item como não controlado ou remover o
mapeamento, devolvendo o produto à fila de pendentes.

### Na ida para a nuvem

**O banco escolhido primeiro não instalava.** A escolha inicial foi um
SQLite hospedado, pela vantagem de manter o mesmo dialeto e não mexer nas
consultas. Só que o cliente Python não tem pacote pronto para a versão de
Python da máquina e exige compilar com a toolchain do Rust. Testar
localmente antes de publicar ficaria impossível, e os erros apareceriam
em produção, com o restaurante usando. A escolha mudou para PostgreSQL,
que instalou de primeira. O argumento original — preservar os `?` das
consultas — foi resolvido de outro jeito: uma tradução automática dentro
do `database.py`, que deixou as consultas e o `crud.py` intactos.

**O tradutor engoliu um caractere especial.** A primeira versão trocava
`?` por `%s` mas não escapava o `%`. Como o driver do Postgres varre a
consulta inteira procurando marcador, sem saber o que é literal, qualquer
texto com `%` quebraria a consulta. Pego antes de ir para produção, com
um teste que passava justamente uma string dessas.

**Uma tela levava 27 segundos para abrir.** Esse foi o susto da migração.
O cálculo do estoque de todos os insumos chamava, para cada insumo, a
função que calcula um só: quatro consultas por insumo, 109 no total. Num
arquivo local cada consulta custa microssegundos e ninguém percebe.
Contra um banco remoto, a 246 ms por ida e volta, a mesma tela virou meio
minuto de espera. **O problema sempre esteve no código — foi a rede que o
tornou visível.** Reescrito para uma consulta só, o Dashboard caiu para
2,1s e o Painel para 0,9s. A conta é a mesma; foi conferida insumo a
insumo, nos cinco campos de cada um, contra a versão antiga.

**Os dois bancos discordavam entre si.** Ao comparar o SQLite e o
Postgres lado a lado, tudo batia menos o feed de movimentações recentes.
A ordenação era por data e tipo, sem desempate. Como todas as vendas de
um dia têm a mesma data e o mesmo tipo, o `LIMIT` cortava linhas
diferentes em cada banco. Era um defeito latente também no SQLite — o
feed podia mudar de ordem sem motivo visível. Um terceiro critério na
ordenação resolveu.

### Na reconciliação de perdas

**O dado de demonstração era fisicamente impossível.** Assim que a tela
de perdas ficou pronta, ela acusou coisas como "usado 226%, sobra 100%,
perda −226%". A conta estava certa — as identidades fechavam e um
cálculo independente confirmava cada número. O problema era a entrada: o
gerador do banco de demonstração escrevia a **mesma quantidade** nas duas
contagens e só criava compras depois da segunda. Traduzindo: o tomate
tinha 42,6 kg, vendia 99 kg e continuava com 42,6 kg. Nenhuma tela
anterior reconciliava dois pontos no tempo, então a incoerência nunca
tinha sido cobrada. O gerador passou a simular o fluxo de verdade —
estoque inicial, compras que repõem o consumo, e uma perda plausível
explicando o que falta.

**Gerar a demonstração trancava a porta.** O script recria o banco do
zero, o que apagava junto a tabela de usuários criada na v0.2. Quem
rodasse o gerador ficava sem conseguir entrar no próprio app de
demonstração — e o erro só apareceria na tela de login, sem explicar a
causa. O script agora cria também um admin de demonstração e imprime a
credencial ao terminar.

### O fio que liga todos

Quase nenhum desses problemas deu mensagem de erro. O estoque errado, o
desconto triplicado, o produto trocado, o feed instável: em todos, o
sistema seguiu rodando e entregando um resultado — só que o resultado
errado. Num sistema que existe para dizer quanto sobrou, um número errado
com cara de certo é pior do que uma tela de erro.

Por isso a conferência virou rotina: comparar a versão nova com a antiga
linha a linha, comparar os dois bancos campo a campo, e desconfiar
especialmente do que funciona sem reclamar.

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

O app abre em `http://localhost:8501`.

### Ver com dados de exemplo

Para conhecer o sistema sem cadastrar nada, e sem tocar em nenhum dado
real, gere um banco de demonstração com 60 dias de vendas, compras e
contagens:

```bash
python seed_demo.py
ESTOQUE_DB=estoque_demo.db streamlit run app.py
```

Entre com **usuário `demo`, senha `demo1234`** — o gerador cria esse admin
junto com os dados. O banco vem com duas contagens físicas já registradas,
então a tela de Perdas e Reconciliação aparece preenchida.

A variável `ESTOQUE_DB` aponta o app para outro arquivo de banco. Sem
ela, o app usa o `estoque.db` padrão.

### Rodar sobre o banco na nuvem

Basta existir um arquivo `.streamlit/secrets.toml` com a URL do Postgres:

```toml
[postgres]
url = "postgresql://usuario:senha@host/banco?sslmode=require"
```

Com ele presente, o app usa a nuvem em vez do arquivo local, sem nenhuma
outra mudança. Há um modelo em `.streamlit/secrets.toml.example`. O
arquivo real está no `.gitignore` e nunca deve ser commitado — a URL
contém a senha do banco.

Para levar os dados do arquivo local para a nuvem, uma vez:

```bash
python migrar_para_nuvem.py
```

### Publicar no Streamlit Community Cloud

Já publicado, em
https://estoque-restaurante-2zcsdq2cje4ayn4hyvrtdw.streamlit.app — o que
segue serve para republicar ou subir uma segunda instância:

1. Suba o repositório para o GitHub
2. Em share.streamlit.io, conecte o repositório e aponte para `app.py`
3. Em *Settings → Secrets*, cole o mesmo conteúdo do `secrets.toml`

O app tem um endereço fixo, acessível de qualquer aparelho pelo
navegador — sem instalar nada. O login continua valendo: o link é
público, o sistema não.

### Publicar uma demonstração pública

O app real fica atrás de login e guarda dado de verdade do restaurante,
então ele não serve de vitrine. Para mostrar o projeto sem expor nada,
o mesmo repositório sobe uma segunda vez no Streamlit Community Cloud
com a variável `MODO_DEMO` ligada. Nesse modo o app:

- roda sobre `estoque_demo.db`, com 60 dias de movimento fictício
  gerado pelo `seed_demo.py` no primeiro acesso;
- dispensa o login e entra como um usuário de demonstração;
- mostra uma faixa avisando que ali nada é real.

Duas proteções fazem esse modo ser seguro. A primeira é que
`url_do_postgres()` devolve `None` de saída quando `MODO_DEMO` está
ligado: mesmo que a credencial do banco real acabe nos secrets do app de
demonstração, ele não alcança os dados do restaurante. A segunda é o
disco efêmero do Streamlit Cloud — o que os visitantes mexerem se desfaz
sozinho quando o app dorme e acorda.

No painel do Streamlit Cloud, o app de demonstração aponta para o mesmo
repositório e o mesmo `app.py`, com **Secrets vazios** e, em *Advanced
settings*, a variável de ambiente:

```
MODO_DEMO = "1"
```

Localmente dá para ver o mesmo com:

```bash
MODO_DEMO=1 streamlit run app.py
```

### Primeiros passos num banco vazio

A ordem importa, porque cada etapa depende da anterior:

1. Cadastre os **insumos** que você controla, com unidade e estoque mínimo
2. Cadastre os **pratos** e monte a **ficha técnica** de cada um
3. Registre uma **contagem física** — sem ela o cálculo parte do zero e
   o estoque fica negativo
4. A partir daí, lance compras e vendas normalmente

## Estrutura

```
estoque-restaurante/
├── app.py            # interface Streamlit (dashboard e telas)
├── crud.py           # regras de negócio e cálculo do estoque teórico
├── database.py       # esquema e conexão (SQLite ou PostgreSQL)
├── auth.py           # login, aprovação de cadastros e permissões
├── ficha_import.py   # leitura das planilhas de ficha técnica → cadastros
├── nfe_import.py     # leitura de XML de NF-e → compras
├── zig_import.py     # leitura da planilha do PDV → vendas
├── seed_demo.py      # gera um banco de demonstração
├── migrar_para_nuvem.py   # copia o banco local para o Postgres
├── diagnostico.py    # inspeção de dados de um prato ou insumo
└── requirements.txt
```

Python, Streamlit e SQLite ou PostgreSQL — o mesmo código roda nos dois.

## Patch notes

### v0.7 — Ficha técnica por planilha

- Tela **Importar Ficha Técnica**: as duas planilhas da cozinha (pratos
  finais e produção) viram insumo, prato e receita de uma vez só, com
  prévia antes de gravar
- As receitas de produção são **abertas nos ingredientes de compra**: o
  prato que usa 0,06 kg de molho de queijo passa a descontar o leite, o
  requeijão e o parmesão que aquele molho consome, na proporção do lote.
  É o que faz o consumo bater com o que entra pela nota fiscal
- Mais de duzentas grafias de ingrediente (com erro de digitação e com o
  mesmo item escrito de dois jeitos) consolidadas numa lista curada de
  insumos genéricos
- A ficha do prato importado é substituída, não somada: insumo que saiu
  da receita para de ser descontado
- Primeira carga: 101 insumos, 64 pratos e 536 linhas de ficha técnica

### v0.6.1 — Modo demonstração

- `MODO_DEMO` publica o mesmo código como vitrine: dados fictícios,
  sem login e com faixa avisando que nada ali é real
- O modo demonstração recusa a credencial do Postgres por construção,
  para que uma configuração errada não alcance o banco do restaurante
- Os dados são semeados no primeiro acesso e se desfazem quando o app
  reinicia, então o visitante pode lançar venda e importar nota à vontade

### v0.6 — App no ar

- Sistema publicado no Streamlit Community Cloud, em
  https://estoque-restaurante-2zcsdq2cje4ayn4hyvrtdw.streamlit.app
- Acessível de qualquer aparelho pelo navegador, sem instalar nada —
  o celular no salão e o computador do escritório veem o mesmo estoque
- Roda sobre o banco na nuvem preparado na v0.4; a URL do Postgres fica
  nos secrets do Streamlit, não no repositório

### v0.5 — Perdas e reconciliação

- Tela **Perdas e Reconciliação**: entre duas contagens físicas, quanto de
  cada insumo foi usado, quanto sobrou e quanto se perdeu, em quantidade e
  em percentual do disponível. As três fatias somam 100%
- Destaque para os insumos acima de 5% de perda, e aviso separado para o
  caso inverso — encontrar **mais** do que o esperado, que costuma ser
  venda não lançada ou erro de contagem, não sorte
- A tela orienta quando ainda não há o que reconciliar: com uma contagem
  só não existe período fechado, e ela diz exatamente o que falta
- Nova área de permissão, liberável por usuário como as demais
- `seed_demo.py` passa a simular um fluxo de estoque coerente, com perda
  plausível por insumo, e a criar um admin de demonstração (`demo` /
  `demo1234`) — antes o gerador apagava os usuários e trancava o app

### v0.4 — Banco na nuvem

- `database.py` escolhe o banco sozinho: **PostgreSQL** quando há uma URL
  configurada, **SQLite** local caso contrário. O restante do código não
  mudou — as consultas continuam escritas uma vez só, no dialeto do
  SQLite, e são traduzidas na hora
- Conexão reaproveitada por thread, em vez de uma nova a cada consulta:
  num banco remoto, cada conexão refazia o TLS
- `migrar_para_nuvem.py`, que copia o banco local para o Postgres
  preservando os ids, ajustando as sequências e se recusando a rodar
  sobre um destino que já tenha dados
- Estoque de todos os insumos calculado em **uma consulta** no lugar de
  109: o Dashboard caiu de ~27s para 2,1s e o Painel para 0,9s
- Desempate na ordenação das movimentações recentes, que saíam em ordem
  arbitrária e diferente em cada banco
- Migração conferida comparando os dois bancos lado a lado: resumo,
  estoque, consumo, cobertura, vendas, pratos, movimentações, mapeamentos
  e usuários, todos idênticos
- README com a seção "Problemas que enfrentamos", reunindo os bugs e
  armadilhas de todas as etapas do projeto

### v0.3 — Cadastro de usuários com aprovação

- Aba **"Criar cadastro"** na tela de login. O pedido nasce pendente e
  não dá acesso a nada até um administrador aprovar
- Tela **Aprovação de cadastros**: fila de pendentes, com escolha das
  áreas na hora de aprovar, recusa e reconsideração
- Tela **Usuários e acessos**: áreas liberadas por usuário, promoção a
  administrador, redefinição de senha, exclusão e cadastro direto já
  aprovado
- Tela **Minha conta**, para qualquer usuário ver seu perfil e trocar a
  própria senha
- Navegação montada a partir das permissões: a rota de uma área não
  liberada não é registrada, então a URL direta também não abre
- Trava impedindo remover o último administrador
- Alterações de acesso valem na interação seguinte, sem precisar sair e
  entrar de novo

### v0.2 — Login

- Tela de login antes do sistema, com `st.stop()` barrando tudo que vem
  depois
- Senhas guardadas como PBKDF2-SHA256 com salt aleatório por usuário
- Identificação de quem está conectado e botão de sair na barra lateral

### v0.1 — O sistema

- Cálculo do estoque teórico a partir de contagem física, compras e
  vendas, eliminando a contagem semanal
- Cadastros de insumos, pratos e ficha técnica
- Compras manuais e por importação de XML de NF-e, com mapeamento de
  produto do fornecedor para insumo e fator de conversão
- Vendas manuais e por importação da planilha do PDV (Zig), somando as
  linhas item a item por produto e por dia
- Dashboard com indicadores, consumo por insumo, curva de vendas e
  ranking de pratos
- Tela "O que acaba primeiro", com estimativa de dias restantes por
  insumo
- Registro da contagem física mensal como nova base do cálculo

## Próximos passos

- Custo da perda em reais, cruzando com o preço de compra
- Exportação de relatórios mensais
- Sugestão de compra a partir dos dias de estoque restantes
