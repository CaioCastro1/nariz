# Tipologia 6: indícios de empresa de fachada

## O que procura

Contratos públicos com empresas privadas que mostram sinais de terem sido criadas ou usadas só para contratar: empresa muito nova, capital incompatível com o valor, atividade sem relação com o objeto, situação cadastral irregular ou vínculo com outra fornecedora do mesmo órgão.

## Base legal

- Lei 12.846/2013 (Lei Anticorrupção), art. 5º, IV, "e": é ato lesivo criar, de modo fraudulento ou irregular, pessoa jurídica para participar de licitação ou celebrar contrato administrativo.
- Lei 14.133/2021: exigências de habilitação jurídica, fiscal e econômico-financeira do fornecedor (arts. 62 a 69).

Nenhum indicador, sozinho ou combinado, prova a fraude. A tipologia faz triagem para revisão humana.

## Fontes de dados

| base | quem publica | download |
|---|---|---|
| Contratos do SIASG (federal) | CGU, Portal da Transparência | portaldatransparencia.gov.br/download-de-dados/compras |
| Contratos do PNCP (todas as esferas) | API pública do PNCP | https://pncp.gov.br/api/consulta/v1/contratos |
| Empresas, Estabelecimentos e Sócios dos Dados Abertos do CNPJ | Receita Federal | compartilhamento público do Nextcloud da Receita (arquivos.receitafederal.gov.br, lido por WebDAV sem login) |

São os mesmos contratos da tipologia 1. Dos Estabelecimentos, só são guardados os CNPJs que aparecem nos contratos.

## Universo

Contratos com CNPJ e valor maior que zero. Ficam fora, por não serem o alvo (empresa privada criada para contratar):

- entidades sem fins lucrativos (natureza jurídica 3xxx);
- empresa pública e sociedade de economia mista;
- administração pública (1xxx);
- pessoa física, produtor rural e organização internacional (4xxx, 5xxx);
- CNPJ sem cadastro na Receita.

Cooperativas e empresários individuais (inclusive MEI) ficam no universo, mas são lidos como segmentos à parte.

## Regras do cruzamento

| indicador | regra |
|---|---|
| (a) empresa nova | matriz aberta de 0 a 182 dias antes da assinatura |
| (b) capital baixo | valor do contrato mais de 100 vezes o capital social, com capital maior que zero e contrato de R$ 50 mil ou mais |
| (c) CNAE sem relação | CNAE principal fora do conjunto plausível para a categoria do objeto |
| (d) situação irregular | suspensa, inapta ou baixada na data da assinatura ou até 180 dias depois |
| (e) vínculo entre fornecedoras | no mesmo órgão, empresas de raízes diferentes com o mesmo endereço ou com sócio pessoa física em comum |

Detalhes:

- **(a)** só vale para matriz, porque o início de atividade publicado é do estabelecimento. Uma filial nova de empresa antiga daria falso alarme. Início de atividade posterior à assinatura é dado inconsistente e fica fora.
- **(b)** o piso de valor evita marcar toda compra pequena de empresa de capital baixo. Capital zero fica fora, porque dividir por zero não diz nada.
- **(c)** sete categorias de objeto por palavras-chave (obras, TI, saúde, alimentos, apoio/limpeza/vigilância, combustível, veículos), cada uma com uma lista de divisões CNAE 2.0 plausíveis. O comércio atacadista e varejista (divisões 46 e 47) conta como plausível em todas, porque quem vende o produto não precisa ter o CNAE do serviço. Só conta quando uma única categoria casa. Objeto ambíguo fica de fora.
- **(d)** baixa até 180 dias depois da assinatura entra; baixa depois disso é tratada como encerramento normal.
- **(e)** endereço idêntico é CEP, logradouro, número e complemento iguais. Sócio em comum é mesmo nome e mesmos 6 dígitos do CPF. Só grupos de 2 a 8 empresas: acima disso, o padrão é prédio comercial, escritório de contabilidade ou holding. O órgão é o nome do órgão mais a esfera. Este indicador é insumo da tipologia de conluio, não a conclusão dela.

**Grau do indício** (soma dos indicadores): alto com 3 ou mais, médio com 2, baixo com 1.

Valores acima de R$ 1 bilhão por contrato são tratados como erro de digitação na fonte e ficam fora das somas. O valor usado é o declarado no contrato, não o pago.

## Explicações legítimas que tiram força do indício

- Empresa nova é rotina entre MEIs e microempresas, sobretudo em compras pequenas. O sinal (a) só ganha peso em contrato grande e combinado com outro indicador.
- Empresas grandes com capital social baixo, ou com capital reduzido depois do contrato.
- CNAE principal desatualizado. A empresa pode vender legalmente fora dele. Por isso (c) sozinho fica sempre no grau baixo.
- MEI que encerrou a atividade por motivo alheio ao contrato.
- Grupo econômico com empresas irmãs que vendem produtos complementares, coworking e contador no mesmo endereço.
- Startup, empresa reaberta com novo CNPJ ou empresa que mudou de ramo.

## Como medimos falso positivo

- **Linha de base por segmento.** A frequência de cada indicador e de grau médio ou alto é calculada por natureza jurídica (Ltda/EIRELI/SLU, MEI, sociedade anônima, cooperativa, outras) e por faixa de valor do contrato. Um indicador que aparece em proporção parecida em todo um segmento é rotina daquele segmento, não sinal.
- **Distribuição no tempo.** A abertura da empresa é contada por trimestre antes da contratação, para ver se há concentração logo depois da abertura ou só crescimento suave.
- **Concentração por órgão.** Órgãos com muitos contratos em (a) são comparados com o total de contratos do órgão, para separar volume de compras pequenas de padrão que merece olhar.
- **Revisão humana de amostra** dos contratos de grau alto e das combinações que cruzam capital com idade ou com vínculo, com consulta ao processo de contratação.

## Limites conhecidos

- O cadastro da Receita é do mês mais recente publicado, não da data de cada contrato. Capital, CNAE, endereço, sócios e situação podem ter mudado.
- A Receita só guarda a data da situação atual. Empresa que ficou inapta e foi reativada não aparece em (d).
- Cobertura de contratos igual à da tipologia 1: SIASG de jan/2022 a jan/2025 e PNCP com meses faltando. Comparação entre períodos só na janela de assinatura de jan/2023 a jan/2025.
- (e) não compara entre órgãos nem dentro da mesma licitação, e ignora sócios pessoa jurídica.
- O CNAE secundário não é usado em (c).
- A tipologia não olha pagamento, entrega do objeto, sobrepreço nem direcionamento.
- O grau não mede probabilidade de irregularidade.

## Como rodar

```bash
uv run scripts/qsa.py           # Sócios e Empresas do mês mais recente
uv run scripts/qsa.py --estab   # Estabelecimentos, só dos CNPJs que aparecem nos contratos
uv run scripts/fachada.py       # indicadores e grau
```

Para um mês novo da Receita: `uv run scripts/qsa.py AAAA-MM && uv run scripts/qsa.py --estab && uv run scripts/fachada.py`. A tabela de contratos com indicador fica fora do git, porque a razão social de MEI pode ser o nome de uma pessoa.
