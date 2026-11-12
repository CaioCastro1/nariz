# Tipologias 3 e 4: servidor ativo representando entidade privada e quarentena

## O que procuram

- **Tipologia 3.** Servidor federal ativo que se reúne com o Executivo federal representando uma entidade privada.
- **Tipologia 4.** Ex-ocupante de cargo de alto escalão que se reúne com o órgão de origem, representando pessoa jurídica privada, antes de completar 6 meses da saída do cargo.

## Base legal

- Lei 8.112/1990, art. 117, XI: é vedado ao servidor atuar como procurador ou intermediário junto a repartições públicas, salvo benefícios previdenciários ou assistenciais de parentes e cônjuge.
- Lei 12.813/2013, art. 5º: durante o exercício do cargo, é conflito de interesses atuar, ainda que informalmente, como procurador, consultor, assessor ou intermediário de interesses privados em órgãos da administração.
- Lei 12.813/2013, art. 2º: define os cargos sujeitos à quarentena (ministro de Estado, natureza especial ou equivalente, presidente, vice-presidente e diretor de autarquia, fundação, empresa pública e sociedade de economia mista, DAS 5 e 6 ou equivalente).
- Lei 12.813/2013, art. 6º, II: por 6 meses depois da saída do cargo, salvo autorização da Comissão de Ética Pública ou da CGU, é vedado, entre outras condutas, intervir em favor de interesse privado perante o órgão em que ocupou o cargo. Os dados usados aqui só mostram essa conduta.

Os incisos e alíneas devem ser conferidos no texto da lei antes de qualquer encaminhamento.

## Fontes de dados

| base | quem publica | download |
|---|---|---|
| e-Agendas (agendas de autoridades do Executivo federal) | CGU | zip mensal do e-Agendas |
| Cadastro mensal de servidores do SIAPE | CGU, Portal da Transparência | dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/servidores/ |
| Cadastro mensal de servidores do Banco Central | CGU, Portal da Transparência | mesmo endereço, arquivo do BACEN |

## Base comum: casamento agenda e cadastro

1. **Participantes.** O campo de participantes do e-Agendas é quebrado por pessoa: nome, 6 dígitos visíveis do CPF, cargo declarado, entidade e CNPJ, data e órgão anfitrião. Só reuniões e audiências. Eventos, audiências públicas e reuniões canceladas ficam fora. O marcador de CPF zerado é tratado como ausente.
2. **Casamento.** Sempre pelas duas chaves juntas. Nível exato: nome normalizado igual e CPF6 igual. Nível abreviado: mesmo CPF6, mesmo primeiro e último nome e o nome da agenda contido em ordem no nome do cadastro, só com candidato único.
3. **Situação na data.** Ativo se a pessoa consta do cadastro do mês da reunião. Ex-servidor se constou antes e não consta mais. A linha do tempo é por pessoa, então quem passou do SIAPE para o Banco Central não conta como saída.
4. **Mesmo órgão.** O anfitrião é comparado com os órgãos de lotação e de exercício, tolerando abreviações do SIAPE. "Mesma pasta" usa o ministério supervisor. "Pasta sucessora" usa uma tabela de ministérios renomeados.
5. **Entidade privada.** Ficam fora "interesse próprio", órgãos públicos, registros genéricos, organismos internacionais e estatais.

## Tipologia 3: regras

**Força alta.** Sem explicação legítima, entidade empresarial (empresa, associação empresarial ou setorial, escritório de advocacia ou consultoria), vínculo estatutário ou comissionado, e anfitrião igual ao órgão de lotação ou exercício do servidor no mês, à pasta supervisora ou à pasta sucessora.

**Força média.** Sem explicação e (a) entidade empresarial com outro órgão, ou com vínculo celetista ou temporário, ou (b) entidade não empresarial que não bate com nenhuma explicação, em reunião com o próprio órgão.

**Força baixa.** Demais casos sem explicação.

A pessoa entra na maior força entre as reuniões dela que não têm explicação. A força mede quanto o indício se sustenta nos dados públicos, não a chance de haver infração.

**Explicações que derrubam o indício** (a primeira que casa vale):

- sindicato, associação de servidores ou central sindical;
- entidade pública do próprio órgão registrada como privada (registro provável errado);
- professor ou pesquisador representando entidade acadêmica ou científica;
- servidor cedido ou requisitado na data da reunião;
- entidade pública que o painel classificou como privada;
- conselho ou colegiado, ou cargo declarado de conselheiro;
- conselheiro de órgão colegiado com vínculo de representação;
- interesse próprio declarado.

## Tipologia 4: regras

Uma reunião entra se todas as condições valem:

1. A entidade representada é privada.
2. A pessoa teve, em algum mês do cadastro, cargo de alto escalão: DAS 101/102 níveis 5 e 6, CCE/FCE de nível 1.15 ou mais, natureza especial, diretoria de agência, ministro de Estado ou diretoria do Banco Central.
3. No mês da reunião ela não ocupa mais cargo de alto escalão. Quem ainda ocupa é caso da tipologia 3.
4. A saída é o último dia do último mês com o cargo no cadastro. Como a saída real cai dentro desse mês, os dias medidos podem subestimar o tempo real em até 30. Por isso há dois patamares: até 153 dias está dentro dos 6 meses mesmo no pior caso; de 154 a 183 dias está na borda.
5. O anfitrião é o órgão onde a pessoa teve o cargo.

**Força alta.** Ex-servidor (fora do cadastro), mesmo órgão, até 153 dias.
**Força média.** Mesmo órgão e a pessoa ainda no cadastro em cargo menor, ou de 154 a 183 dias depois da saída.
**Força baixa.** Mesma pasta ou pasta sucessora, até 183 dias.

Reunião declarada como interesse próprio fica fora: a tipologia mira a atuação em nome de pessoa jurídica privada.

## Explicações legítimas que tiram força do indício

- Licença para tratar de interesses particulares (Lei 8.112, art. 91), que não aparece nos campos do cadastro usados.
- Exceções do art. 117, XI (benefício de parentes), participação em associação de classe, cooperativa e conselho.
- Convite como especialista, reunião aberta ou assunto da própria carreira, que a agenda registra do mesmo jeito.
- Professores com autorização para atividade externa.
- Autorização da Comissão de Ética Pública ou da CGU para a atuação na quarentena.
- Reunião convocada pelo próprio órgão, que não configura intervenção em favor do ex-dirigente.

## Como medimos falso positivo

- **Colisão no cadastro.** Conta quantas chaves nome + CPF6 apontam para mais de um identificador de servidor, e confere se são a mesma pessoa em dois cadastros.
- **Homônimo por acaso.** Os CPF6 dos servidores são sorteados de novo dentro da mesma região fiscal (9º dígito) e o casamento é refeito: 20 simulações no nível exato e 10 no abreviado. A média de casamentos nas simulações estima os falsos positivos. A estimativa supõe CPF uniforme dentro da região, e a taxa real pode ser algumas vezes maior.
- **Regras de entidade.** As regras que classificam a entidade (sindicato, ente público, acadêmica) foram revisadas sobre as entidades mais frequentes.
- **Registro na agenda.** A principal fonte de falso positivo é o registro errado no e-Agendas. A verificação prevista é perguntar ao órgão anfitrião quem informou o participante, o papel declarado e a pauta.

## Limites conhecidos

- O CPF só aparece na agenda de forma consistente a partir de 2025. Os resultados descrevem 2025 em diante.
- O cadastro de servidores é mensal. A data que decide a quarentena é a do ato de exoneração, publicada no Diário Oficial e não usada aqui. Por isso a folga de 30 dias.
- Saída no mesmo mês da reunião não aparece: o mês da saída ainda mostra o cargo.
- Quando o cadastro do mês da reunião ainda não foi publicado, vale o do mês anterior.
- Cargos de alto escalão listados sem função no cadastro podem ficar de fora. A contagem é um piso.
- As regras de entidade são por nome. A cauda pode ter sindicatos classificados como empresa e o contrário.
- Cobertura do cadastro: Executivo civil federal (SIAPE) e Banco Central. Ficam fora militares, estatais com quadro próprio, Legislativo, Judiciário e estados.
- Agendas não registradas, ou registradas sem CPF, ficam fora.
- O e-Agendas não mostra quem convocou nem se a pessoa falou em nome da entidade.
- Com poucos casos por órgão, publicar órgão e setor juntos pode identificar a pessoa. A divulgação pública da tipologia 4 deve trazer só totais e faixa de dias.

## Como rodar

```bash
uv run scripts/extract.py                          # participantes do e-Agendas
uv run scripts/servidores.py 2019-01:2026-08       # cadastro do SIAPE, mês a mês
uv run scripts/servidores.py --bacen 2019-01:2026-08
uv run scripts/porta_giratoria.py                  # casamento agenda e cadastro
uv run scripts/tipologias_3_4.py                   # regras das tipologias 3 e 4
```

Os arquivos intermediários e de casos têm nomes de pessoas. Ficam só no disco local, fora do git.
