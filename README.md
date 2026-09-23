# 📦 Controle de Estoque para Restaurante

Substitui a contagem manual semanal de estoque por um cálculo automático
a partir de compras e vendas. A contagem física deixa de ser a rotina de
toda segunda-feira e vira uma conferência mensal.

Projeto pessoal, criado para um problema real do restaurante onde
trabalho como comprador. **Entra em uso de verdade em setembro de 2026**,
com 511 insumos entre cozinha e bebidas, 87 pratos, 546 linhas de ficha
técnica vindas das planilhas da cozinha e 576 linhas de contagem vindas
da planilha de estoque.

**▶️ Demonstração, sem cadastro:**
https://estoque-restaurante-4nhzp9k8m6illpc2cjkg3l.streamlit.app

Entra direto e dá para mexer em tudo — lançar venda, importar nota,
fazer contagem. As telas de importação têm um botão para baixar um
arquivo de exemplo e subir ali mesmo. Os dados são fictícios e voltam ao
começo quando o app reinicia.

**O sistema de verdade:**
https://estoque-restaurante-2zcsdq2cje4ayn4hyvrtdw.streamlit.app

Esse link é público, o sistema não — o acesso continua por login, e os
dados são os do restaurante.

![Dashboard do sistema](docs/dashboard.png)

> As telas deste README são da demonstração pública, com os dados
> fictícios gerados pelo `seed_demo.py`.

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

Não houve integração com a Zig, o PDV do restaurante — não há API pública
documentada. Então **as vendas são lançadas à mão, todo dia**. Isso deixou
de ser um detalhe de implementação e virou a restrição que desenhou o
sistema: uma tela de lançamento que não caiba na rotina de fechamento
simplesmente não é usada, e um dia não lançado não dá erro nenhum — só faz
o consumo sair menor que o real e o estoque teórico ficar alto. Daí as
telas em lote, o padrão de substituir em vez de somar, e o aviso de dias
sem lançamento.

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
- Lançamento manual de compras, um insumo por vez
- **Nota fiscal digitada à mão**: para a nota que chega em papel ou em PDF,
  sem XML. Fornecedor, número, data e a lista de itens numa tabela só —
  todos lançados de uma vez, ou nenhum, se algum item estiver errado. O
  número da nota serve de trava: se ela já foi lançada, o sistema avisa
  antes de somar tudo de novo no estoque
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
- Lançamento do **dia inteiro numa tabela só**: todos os pratos de uma vez,
  com filtro por nome, já preenchida com o que está gravado naquela data.
  Em branco não mexe no prato; zero apaga o lançamento dele no dia. É a
  tela do dia a dia — prato a prato seriam dezenas de envios por noite, e
  o que não cabe na rotina acaba não sendo lançado
- **Lembrete de dia sem venda lançada**, na barra lateral de qualquer tela,
  a partir do dia seguinte. O dia em que o restaurante não abriu é marcado
  como fechado e sai do lembrete — senão uma folga acusaria falta para
  sempre, e aviso que nunca some é aviso que ninguém lê
- Lançamento avulso por prato, para corrigir ou completar um só. O padrão
  é **substituir** o total do dia, não somar: relançar o mesmo prato
  corrige o dia em vez de duplicá-lo, e clicar duas vezes no botão dá o
  mesmo resultado que clicar uma. A tela mostra o que o prato tira do
  estoque pela ficha técnica, e avisa quando o prato não tem ficha — caso
  em que a venda não desconta nada

**Conferência**
- **Saída de Estoque no Período**: as vendas lançadas dia a dia somadas
  num intervalo, para responder a pergunta da segunda-feira — quanto saiu
  do estoque na semana. Quanto de cada insumo saiu, quais pratos geraram
  essa saída, quanto cada dia pesou, e quais dias do período **não têm
  venda lançada**, que é a falha que o lançamento manual produz sem dar
  erro nenhum
- **Dashboard** com indicadores do período, consumo por insumo, curva de
  vendas por dia, ranking de pratos e movimentações recentes
- **"O que acaba primeiro"**: estimativa de em quantos dias cada insumo
  acaba (estoque ÷ consumo médio diário), com semáforo de status. É a
  tela que responde o que precisa ser comprado antes de faltar
- **Contagem física pela planilha do restaurante**: a tela segue a mesma
  planilha que a equipe já usava, seção por seção e na unidade de cada
  prateleira — parmesão em peça, alecrim em maço, cerveja em garrafa. Cada
  linha tem um fator que a converte para o insumo (1 peça = 7,5 kg), e
  várias linhas somam no mesmo insumo (alcatra em peça, porcionada na
  câmara e porcionada na cozinha). Antes de gravar, a tela mostra o total
  de cada insumo ao lado do estoque teórico; ao gravar, quais divergiram e
  em quanto. Regravar corrige o dia em vez de empilhar contagens
- **Itens da Contagem**: importa a planilha de contagem (só alimentos e
  bebidas — limpeza, descartáveis, escritório e utensílios ficam de fora)
  e é onde se preenche o fator das linhas cujo peso a planilha não diz
- **Estoque mínimo em lote**, na tela de Insumos: é o mínimo que liga o
  semáforo do painel e o alerta de reposição. Definido um a um, em mais de
  cem insumos, não é definido nunca — e sem ele o sistema só conta o
  passado, em vez de avisar antes de faltar
- **Perdas e Reconciliação**: entre duas contagens, quanto de cada insumo
  virou venda, quanto sobrou e quanto se perdeu — em quantidade e em
  percentual do que estava disponível

![Tela "O que acaba primeiro"](docs/o-que-acaba-primeiro.png)

![Tela de Perdas e Reconciliação](docs/perdas.png)

## Acesso e usuários

O sistema tem login. A primeira tela pede usuário e senha, e nenhuma
página é montada antes disso — quem não entrou não chega a lugar nenhum.

**O cadastro é aberto, a entrada não.** Qualquer pessoa pode pedir acesso
pela aba "Criar cadastro", mas o pedido nasce *pendente*: a senha até
confere no login, só que a entrada fica barrada até um administrador
aprovar. Isso mantém o controle de quem usa o sistema sem obrigar o
administrador a criar conta para cada pessoa na mão.

**Cada um enxerga só o que é dele.** Ao aprovar um cadastro, o
administrador marca quais das quatorze áreas aquela pessoa vai acessar —
Dashboard, Painel de Estoque, Saída de Estoque no Período, Perdas e
Reconciliação, Insumos, Pratos, Ficha Técnica, Importar Ficha Técnica,
Lançar Compra, Lançar Nota Fiscal (manual), Importar Nota Fiscal,
Importar Vendas (PDV), Lançar Venda do Dia e Contagem Física. A sugestão
inicial é só as três de consulta, que não mexem no estoque.

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

**Quase nenhum deles deu mensagem de erro.** Essa é a única coisa que
todos têm em comum, e é o resumo honesto do projeto: num sistema que
existe para dizer quanto sobrou, o defeito perigoso não é o que derruba a
tela — é o que devolve um número errado com cara de certo. O índice
abaixo é a lista completa do que foi encontrado até aqui.

| # | Sintoma | Causa real |
|---|---------|------------|
| 1 | Estoque errado depois da contagem | Comparação de data com `>` em vez de `>=`: a venda do próprio dia da contagem não era descontada |
| 2 | Uma venda descontava o triplo | Linhas repetidas em `vendas_diarias`, vindas de envios repetidos do formulário |
| 3 | Produto do fornecedor virava o insumo errado | Código de produto tratado como único entre fornecedores diferentes |
| 4 | Produtos do PDV sumiam na importação | SKU comparado sem diferenciar maiúsculas: `Fe` e `FE` são produtos diferentes na Zig |
| 5 | Venda de madrugada caía no dia errado | A planilha da Zig tem duas datas; a que vale é a do *evento*, o dia operacional |
| 6 | Banco hospedado não instalava | Cliente Python exigia compilar com a toolchain do Rust; a escolha mudou para PostgreSQL |
| 7 | Consulta quebrava com texto contendo `%` | O tradutor de dialeto trocava `?` por `%s` sem escapar o `%` |
| 8 | Uma tela levava 27 segundos para abrir | Quatro consultas por insumo, 109 no total: irrelevante em arquivo local, fatal contra banco remoto |
| 9 | Os dois bancos discordavam entre si | Ordenação sem critério de desempate fazia o `LIMIT` cortar linhas diferentes em cada banco |
| 10 | Tela de perdas acusava "usado 226%" | O dado de demonstração era fisicamente impossível; o gerador não fechava a conta |
| 11 | **Lançamento sumia sem dar erro** | O app podia trocar de banco no meio da sessão, calado, e gravar num SQLite efêmero em vez do Postgres |
| 12 | **Lançamento manual duplicava o dia** | Somar era o padrão; um clique a mais criava uma segunda linha de venda |
| 13 | **O servidor achava que já era amanhã** | Streamlit Cloud roda em UTC; às 23h de Brasília a noite inteira caía no dia seguinte |
| 14 | **Script de demonstração escreveu em produção** | `ESTOQUE_DB` só escolhe o *arquivo* do SQLite, não impede a escolha do Postgres |
| 15 | **A camada de alerta estava morta** | 127 de 128 insumos com estoque mínimo zero: o semáforo nunca saía do verde |
| 16 | **Lançar o dia levaria dezenas de envios** | Formulário de um item por vez, com 87 pratos e 128 insumos |
| 17 | **O app estourava ao abrir depois de um tempo parado** | O banco na nuvem hiberna, e a conexão era tentada uma única vez, sem timeout nem repetição |

Os dez primeiros foram resolvidos durante a construção; os de 11 a 17
apareceram na preparação para o sistema entrar em uso de verdade, e estão
contados em detalhe abaixo.

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

**A planilha de contagem conta em peça, a ficha técnica desconta em
quilo.** A contagem semanal do restaurante é feita numa planilha com
quase mil linhas, na unidade em que cada coisa está na prateleira: o
parmesão em peça de 7,5 kg, o alecrim em maço, o leite em caixinha. A
ficha técnica, que é de onde sai o consumo, trabalha em kg e litro. Pedir
para quem conta converter de cabeça seria trazer o erro para dentro do
número que serve de base para todo o resto. Cada linha da planilha
ganhou um fator de conversão, e o insumo recebe a soma das suas linhas.

Duas armadilhas vieram junto. Quando a descrição não diz o peso (uma
"unidade" de alface, um "maço" de salsinha), o fator fica **a definir**
em vez de chutado: um peso médio inventado entraria calado em toda
contagem. E quando um insumo tem várias linhas e só parte delas é
preenchida, as outras contam como zero e a tela lista quais são. Gravar
só a alcatra em peça como estoque total da alcatra seria uma contagem
pela metade, com cara de contagem inteira.

A conversão ainda expôs um erro antigo. Com o pacote de croqueta
pesando 300 g, a ficha técnica dizia que cada porção vendida consumia
1 kg. A planilha da cozinha escreve "1", querendo dizer uma unidade, e o
importador lê toda quantidade em kg, porque é assim que o resto da
planilha está escrito. Nenhuma tela reclamaria: o estoque de croqueta
só cairia três vezes mais rápido que o real, e a perda apareceria
negativa na reconciliação. Pôr lado a lado o peso de quem conta e o
consumo de quem cozinha foi o que mostrou.

Uma terceira quase passou. Cachaça 51 e conhaque Domec aparecem na
planilha como bebida do bar, mas a ficha técnica usa os dois como
ingrediente. Cadastrados como bebida, virariam insumos que ninguém
consome, e os da ficha, insumos que ninguém conta. As duas linhas caem
nos insumos da cozinha, convertidas de garrafa para litro.

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

**Um lançamento sumiu sem dar erro.** Uma venda lançada no app não
aparecia em tela nenhuma depois. Não havia mensagem de erro, a tela dizia
"Venda registrada!", e o banco simplesmente não tinha a linha. A causa
estava na escolha do banco: a cada consulta, o `database.py` refazia a
pergunta "existe credencial de Postgres?", e a resposta vinha de uma
leitura dos secrets do Streamlit dentro de um `try/except` genérico.
Qualquer tropeço momentâneo nessa leitura devolvia `None`, e o app caía
**calado** no SQLite — gravando num arquivo local e efêmero do Streamlit
Cloud, enquanto a tela seguinte lia do Postgres de novo. O dado ia para o
lugar errado sem ninguém ser avisado. Agora o banco é escolhido uma vez
por processo e essa escolha é congelada: se a credencial sumir depois, o
app quebra na cara em vez de escrever no lugar errado. E a tela **Minha
conta** passou a dizer, por escrito, em qual banco os lançamentos estão
caindo — a pergunta que custou essa investigação inteira.

**O lançamento manual duplicava o dia.** Um clique a mais no botão
"Registrar" criava uma segunda linha de venda para o mesmo prato no mesmo
dia, e o consumo saía dobrado. A proteção anterior era uma pergunta
("já existem 4 unidades, confirma somar mais?"), que resolvia o clique
duplo mas atrapalhava o uso normal: quem quisesse só corrigir o número do
dia tinha que apagar antes. A troca foi mudar o padrão. Lançar passou a
**substituir** o total do dia em vez de somar, como a importação da Zig já
fazia: o número digitado é o total, relançar corrige, e clicar duas vezes
dá o mesmo resultado que clicar uma. Somar continua existindo, mas como
escolha explícita.

**O app estourava ao ser aberto depois de um tempo parado.** Uma tela de
erro do Streamlit, com a mensagem censurada, logo no primeiro acesso do
dia. O banco fica no Neon, cujo plano gratuito **suspende a máquina**
depois de alguns minutos sem uso — e a primeira conexão depois disso
precisa acordá-la, o que leva alguns segundos e pode falhar de primeira.
O código chamava `psycopg.connect()` uma única vez, sem timeout e sem
repetir: bastava o banco estar dormindo para o app inteiro cair.

O detalhe que fez isso valer a pena consertar não é técnico. Num
restaurante, às onze da noite, uma tela de exceção não é "um erro de
conexão" — é o sistema não estar funcionando, e o lançamento do dia não
acontece. Agora a conexão é tentada três vezes, com timeout e espera
crescente entre elas, e quando mesmo assim não vai, a tela mostra o que
houve e um botão de tentar de novo, em vez de um traceback.

**Um script de demonstração escreveu no banco de produção.** O
`seed_demo.py` gera um banco fictício e, para isso, apaga e recria tudo.
Ele se protegia definindo `ESTOQUE_DB`, apontando para o arquivo de
demonstração — só que essa variável escolhe apenas *qual arquivo SQLite*
usar, e não se o banco é SQLite. Numa máquina com a credencial do
Postgres configurada, o `database.py` escolhia o Postgres e ignorava o
caminho inteiro. O script chegou a inserir insumos fictícios no banco do
restaurante antes de parar sozinho, por esbarrar num nome repetido. A
proteção parecia existir e não existia — foi o nome repetido que segurou,
não o desenho. Agora o script liga o modo demonstração antes de importar
o `database.py` e, como segunda tranca, confere qual banco foi escolhido
antes de apagar o que quer que seja.

**O servidor achava que já era amanhã.** O Streamlit Cloud roda em UTC e
o restaurante fecha de madrugada. Às 23h de Brasília, o `date.today()` do
servidor já tinha virado o dia seguinte — quem lançasse o movimento no fim
do expediente veria a data de amanhã preenchida no formulário, e a noite
inteira cairia no dia errado. Errado por um dia é o pior tipo de erro
aqui: não chama atenção, passa na conferência, e só aparece quando a
contagem do mês não fecha. A data do sistema passou a ser sempre a de
Brasília, num único lugar (`crud.hoje()`), e a base de fusos entrou no
`requirements.txt` para o container não cair num palpite.

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

### Nas telas em lote

**A confirmação aparecia e sumia.** Depois de gravar a venda do dia ou a
contagem, a mensagem de sucesso e o relatório de divergências piscavam
na tela e desapareciam. O dado estava gravado — a tela seguinte mostrava
—, mas quem gravou ficava sem confirmação e, na contagem, sem a lista do
que divergiu do calculado, que é justamente o que a contagem existe para
mostrar.

A causa é um detalhe do `st.data_editor`. As tabelas em lote são
remontadas a cada execução a partir do que já foi digitado; na execução
do botão, os valores digitados passam a vir embutidos nos dados. O
editor percebe que os dados mudaram, descarta as edições pendentes e
dispara mais uma execução — que redesenhava a página sem a mensagem,
porque ela só existia na execução do clique. Hoje o resultado da
gravação fica guardado na sessão e é mostrado até a tabela ser editada
de novo.

O teste automatizado das telas não pegava isso: ele não dirige o
`data_editor` e não reproduz a execução extra que o navegador dispara.
Foi preciso clicar e digitar numa tabela de verdade.

### O fio que liga todos

Nenhum desses problemas deu mensagem de erro. O estoque errado, o
desconto triplicado, o produto trocado, o feed instável, o lançamento que
sumiu, a noite que caiu no dia seguinte: em todos, o sistema seguiu
rodando e entregando um resultado — só que o resultado errado. Num
sistema que existe para dizer quanto sobrou, um número errado com cara de
certo é pior do que uma tela de erro.

Por isso a conferência virou rotina: comparar a versão nova com a antiga
linha a linha, comparar os dois bancos campo a campo, e desconfiar
especialmente do que funciona sem reclamar.

Três padrões saíram disso e hoje valem como regra no projeto:

- **Proteção que não foi testada não é proteção.** O `seed_demo.py`
  parecia protegido por uma variável de ambiente que não protegia nada; o
  que segurou o estrago foi um nome repetido no banco, por acaso. Toda
  tranca nova aqui ganha uma segunda, que confere o que de fato aconteceu
  em vez do que deveria ter acontecido.
- **Gravar duas vezes tem que dar no mesmo que gravar uma.** Quase todo
  lançamento em dobro deste projeto nasceu de somar onde deveria
  substituir. Hoje venda, contagem e importação substituem por padrão, e
  somar é escolha explícita.
- **O que a tela mostra depois de gravar vem lido de volta do banco**, e
  não repetido do formulário. Foi assim que o lançamento sumido teria
  aparecido no mesmo instante, em vez de na conferência da semana
  seguinte.

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

A demonstração está no ar em
https://estoque-restaurante-4nhzp9k8m6illpc2cjkg3l.streamlit.app

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
repositório, mas com **`demo.py` em "Main file path"** e os **Secrets
vazios**. O `demo.py` liga o modo demonstração e chama o `app.py`, então
não há configuração nenhuma para acertar no painel — e, mais importante,
não há campo onde a credencial do banco real possa ser colada por engano.

Localmente é o mesmo comando:

```bash
streamlit run demo.py
```

`MODO_DEMO=1` como variável de ambiente, ou nos secrets, continua
funcionando para quem preferir configurar por fora.

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
├── contagem_import.py # leitura da planilha de contagem → itens da contagem
├── nfe_import.py     # leitura de XML de NF-e → compras
├── zig_import.py     # leitura da planilha do PDV → vendas
├── demo.py           # entrada da vitrine (roda o app em modo demonstração)
├── exemplos.py       # gera a nota fiscal e o relatório de PDV fictícios
├── seed_demo.py      # gera um banco de demonstração
├── migrar_para_nuvem.py   # copia o banco local para o Postgres
├── diagnostico.py    # inspeção de dados de um prato ou insumo
└── requirements.txt
```

Python, Streamlit e SQLite ou PostgreSQL — o mesmo código roda nos dois.

## Patch notes

### v0.10 — A contagem da planilha

- **Corrigido: a confirmação sumia depois de gravar.** Nas telas em lote
  (venda do dia e contagem), a mensagem de gravado e o relatório de
  divergências da contagem apareciam e desapareciam no mesmo instante. O
  dado era gravado, mas quem gravou não via nada — nem a divergência, que
  é o motivo de a contagem existir. Encontrado testando no navegador; o
  teste automatizado não enxerga esse efeito

- **Contagem física pela planilha do restaurante.** A tela passou a
  seguir a planilha de contagem que a equipe já usava: mesmas seções,
  mesma ordem, cada linha na unidade da prateleira. O sistema converte
  cada linha para o insumo com um fator (1 peça de parmesão = 7,5 kg) e
  soma as linhas de um mesmo insumo. Linha preenchida sem fator trava só
  o insumo dela, e linha irmã em branco conta como zero, com aviso antes
  de gravar
- **Itens da Contagem**, em Cadastros: importa a planilha e é onde se
  preenchem os fatores que faltam. Reimportar atualiza em vez de duplicar
  e não apaga fator já preenchido
- **Bebidas entram no estoque.** Primeira carga: 576 linhas de alimentos
  e bebidas e 383 insumos novos (237 bebidas, cada uma com o nome limpo
  da descrição). Limpeza, descartáveis, escritório e utensílios ficaram
  de fora
- **Todas as linhas com conversão.** 41 linhas não diziam o peso (maço,
  unidade, bandeja, pacote). Em vez de um peso médio chutado, cada uma
  ficou a definir até a cozinha informar: maço de erva 200 g, alface
  100 g, bandeja de morango 500 g, pacote de isca de frango 300 g, e
  assim por diante. Algumas linhas passaram a ser contadas como a equipe
  conta de verdade, e não como a planilha dizia (morango em bandeja, não
  em caixa; isca de frango em pacote, não em unidade)
- **Corrigido: cada porção de croqueta tirava 1 kg do estoque.** A
  planilha de ficha técnica escreve "1" para a croqueta do prato, e o
  importador lê tudo em kg. O erro só apareceu quando a contagem mostrou
  que o pacote inteiro pesa 300 g. A quantidade certa (300 g) está
  gravada no importador, para que reimportar a planilha não traga o
  erro de volta
- **Lembrete de dia sem venda lançada**, na barra lateral e na tela de
  venda, a partir do dia seguinte e só depois do início do uso. Dia em
  que o restaurante não abriu é marcado como fechado e sai do lembrete
  (e também da lista de dias sem venda da tela de Saída)
- Excluir um insumo passa a levar junto as linhas de contagem e os
  mapeamentos de nota fiscal ligados a ele — antes, um mapeamento de NF-e
  impedia a exclusão no Postgres

### v0.9.1 — O banco que dormia

- **Corrigido: o app estourava ao abrir depois de um tempo parado.** O
  Postgres no Neon hiberna sem uso e a conexão era tentada uma única vez,
  sem timeout nem repetição. Agora são três tentativas com espera
  crescente, e a falha final vira um aviso com botão de tentar de novo —
  não uma tela de exceção

### v0.9 — A operação em lote

Preparação para o sistema entrar em uso de verdade. O tema é o mesmo em
tudo: **o que não cabe na rotina não é feito**, e um cadastro que não é
feito vira um número errado com cara de certo.

- **Corrigido: o servidor achava que já era amanhã.** O Streamlit Cloud
  roda em UTC; às 23h de Brasília o lançamento da noite cairia no dia
  seguinte. A data do sistema passou a ser a de Brasília, num lugar só
- **Venda do dia inteiro numa tabela**: todos os pratos de uma vez, com
  filtro, pré-preenchida com o que já está gravado. Em branco não mexe,
  zero apaga. Lançar prato a prato eram dezenas de envios por noite
- **Contagem física numa tabela**, com o estoque teórico ao lado de cada
  insumo, e o relatório de divergências mostrado no mesmo instante em que
  a contagem é gravada
- **Estoque mínimo em lote** na tela de Insumos, com o consumo médio
  diário ao lado para calibrar o número
- Tudo em lote é **tudo ou nada** e **idempotente**: item errado não deixa
  meio lançamento entrar, e gravar duas vezes dá o mesmo resultado que
  gravar uma
- **Corrigido: o gerador do banco de demonstração escrevia no banco real.**
  Ele definia `ESTOQUE_DB`, que só escolhe o *arquivo* do SQLite — com
  credencial de Postgres no ambiente, o app escolhia o Postgres e ignorava
  o caminho. Agora ele liga o modo demonstração antes de tudo e confere o
  banco escolhido antes de apagar qualquer coisa

### v0.8 — Lançamento diário confiável

- **Corrigido: lançamento que sumia sem dar erro.** O app podia trocar de
  banco no meio da sessão, calado, e gravar num SQLite efêmero em vez do
  Postgres. A escolha do banco passou a ser feita uma vez e congelada; se
  a credencial sumir, o app falha em vez de escrever no lugar errado
- **Lançar Venda do Dia** refeita: o padrão é substituir o total do dia,
  não somar — relançar corrige em vez de duplicar, e clique duplo no botão
  não conta duas vezes. O total exibido depois de gravar é **lido de volta
  do banco**, não repetido do formulário. A tela mostra o que a venda tira
  do estoque pela ficha técnica, lista tudo que já está lançado no dia e
  avisa quando o prato não tem ficha (venda que não desconta nada).
  Quantidade zero deixou de ser aceita
- **Lançar Nota Fiscal (manual)**: nota digitada em tabela, vários itens de
  uma vez, para quando não há XML. É tudo ou nada — item errado não deixa
  meia nota entrar no estoque — e o número da nota avisa se ela já foi
  lançada antes
- **Saída de Estoque no Período**: as vendas do dia a dia somadas por
  semana (ou por qualquer intervalo), com quanto saiu de cada insumo,
  quais pratos geraram a saída, o peso de cada dia e a lista dos **dias
  sem venda lançada** — a falha silenciosa do lançamento manual. Exporta
  em CSV
- **Minha conta** passou a mostrar ao administrador em qual banco os dados
  estão sendo gravados

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

- Demonstração pública no ar, sem cadastro, em
  https://estoque-restaurante-4nhzp9k8m6illpc2cjkg3l.streamlit.app
- `demo.py` é a entrada da vitrine: liga o modo demonstração e chama o
  `app.py`, para que publicar não dependa de acertar campo no painel
- As telas de importação oferecem, só na vitrine, uma nota fiscal e um
  relatório de PDV fictícios para baixar e subir ali mesmo — sem eles,
  duas das telas mais interessantes ficavam sem o que demonstrar
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

- Venda de bebida descontando do estoque: hoje as bebidas se movem só
  pela contagem e pelas compras, porque não há prato ligado a elas
- Custo da perda em reais, cruzando com o preço de compra
- Exportação de relatórios mensais
- Sugestão de compra a partir dos dias de estoque restantes
