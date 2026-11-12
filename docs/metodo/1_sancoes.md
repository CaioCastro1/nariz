# Tipologia 1: empresa sancionada contratada pelo poder público

## O que procura

Contratos assinados enquanto a empresa contratada estava impedida de contratar com aquele órgão, segundo os cadastros de sanções da CGU.

## Base legal

- Lei 14.133/2021, art. 91, §4º: antes de formalizar ou prorrogar um contrato, a Administração deve consultar o CEIS e o CNEP.
- Lei 14.133/2021, art. 156: impedimento de licitar e contratar (inciso III) vale no ente que aplicou a sanção (§4º). Declaração de inidoneidade (inciso IV) vale em toda a Administração, de todos os entes (§5º).
- Sanções aplicadas com base nas leis anteriores (Lei 8.666/1993, Lei 10.520/2002, Lei 12.462/2011) seguem registradas no CEIS e entram pelas mesmas regras.

## Fontes de dados

| base | quem publica | download |
|---|---|---|
| CEIS (Cadastro de Empresas Inidôneas e Suspensas) | CGU, Portal da Transparência | portaldatransparencia.gov.br/download-de-dados/ceis |
| CNEP (Cadastro Nacional de Empresas Punidas) | CGU, Portal da Transparência | portaldatransparencia.gov.br/download-de-dados/cnep |
| Contratos do SIASG (federal) | CGU, Portal da Transparência | portaldatransparencia.gov.br/download-de-dados/compras |
| Contratos do PNCP (todas as esferas) | Ministério da Gestão, API pública de consulta | https://pncp.gov.br/api/consulta/v1/contratos |

## Regras do cruzamento

**Que sanções contam.** Só as que impedem contratar: impedimento, suspensão e inidoneidade. Multa e publicação extraordinária ficam fora.

**Quando o contrato conta.** A data de assinatura cai entre o início e o fim da sanção. Fim vazio quer dizer sanção ainda vigente. Quando o fim está vazio mas as observações do cadastro dizem o prazo ("pelo período de 1 mês"), o fim é calculado a partir delas.

**Casamento.** Pelo CNPJ completo, 14 dígitos. Sanção da matriz que atinge contrato de filial (mesma raiz de 8 dígitos) é contada à parte e não entra no caso forte.

**Onde a sanção vale (abrangência).**

- Nível A: inidoneidade marcada "todas as esferas" ou com base em lei federal. Vale em qualquer contrato.
- Nível B: impedimento ou suspensão "em todos os poderes da esfera". Vale só no ente do sancionador: contratos da União, se federal; contratos estaduais da mesma UF, se estadual ou distrital; contratos do mesmo município, se municipal (o município é lido no nome do órgão sancionador).
- Nível C: "no órgão sancionador" ou "na esfera e no poder do órgão sancionador". Vale só se o contratante for o mesmo órgão, por casamento aproximado de nome. O CEIS não informa o poder do sancionador, por isso "esfera e poder" não pode ser tratado como a esfera inteira.
- Nível D: abrangência ambígua, "sem informação", medida cautelar do Código de Processo Penal, ou impedimento e suspensão marcados "todas as esferas". Não entra no caso forte. Impedimento e suspensão não valem em todo o país, mesmo quando o cadastro diz que sim.

**Duplicidade entre fontes.** O mesmo contrato federal aparece no SIASG e no PNCP. O do PNCP é descartado quando o SIASG já tem o mesmo CNPJ, a mesma UASG e a mesma data de assinatura ou o mesmo número de contrato. Dentro do PNCP vale o identificador do próprio PNCP.

**Força do indício.**

- Forte: CNPJ exato, sanção válida naquele contrato pelas regras de abrangência e já registrada no CEIS antes da assinatura. O órgão tinha como ver a sanção.
- Registro tardio: CNPJ exato e sanção válida, mas registrada no CEIS só depois da assinatura. A empresa já estava impedida, mas o órgão não tinha como saber. Aponta para atraso do cadastro, não para falha do contratante.
- Fora do forte: casamento só por raiz de CNPJ e sanções de nível D.

## Explicações legítimas que tiram força do indício

- Decisão judicial que suspendeu a sanção na data do contrato, com restabelecimento depois e data de início retroativa.
- Ata de registro de preços homologada antes da sanção, com contrato formalizado depois.
- Sanção revista, anulada ou já encerrada, mas ainda presente no cadastro sem data de fim.
- Erro de cadastro na abrangência ou nas datas.
- Sanção aplicada por conselho profissional, cuja validade em toda a esfera federal precisa ser conferida.
- Microempreendedor individual cujo CNPJ é, na prática, uma pessoa física. Esses casos são tratados à parte.

## Como medimos falso positivo

- Conferência manual dos casos fortes: leitura do texto da sanção (fundamento legal, abrangência declarada, observações) e comparação com o órgão contratante. Cada padrão de erro encontrado vira regra no script (por exemplo, impedimento municipal marcado "todas as esferas" e o tratamento de "esfera e poder"), e o cruzamento é refeito.
- Casamento de órgão por nome (nível C) é sempre conferido à mão antes de qualquer uso.
- Nenhum caso é encaminhado sem consulta ao processo ou pedido via LAI.

## Limites conhecidos

- O CEIS guarda só o que ainda está cadastrado. Sanção expirada e removida não aparece. A contagem é um piso.
- O PNCP filtra por data de publicação, não de assinatura. Um contrato assinado num mês pode aparecer em meses seguintes.
- Cobertura: SIASG de jan/2022 a jan/2025. PNCP com meses faltando quando a API fica indisponível. A comparação entre períodos só vale na janela em que as duas fontes cobrem todos os meses (assinatura de jan/2023 a jan/2025). Fora dela, a contagem é um piso com cobertura irregular.
- O PNCP traz contratos, não empenhos nem termos aditivos de prorrogação, que também exigem consulta ao CEIS.
- O casamento de órgão por nome é aproximado.
- Contrato assinado durante a sanção é indício, não prova de irregularidade.

## Como rodar

```bash
uv run scripts/pncp.py        # contratos do PNCP, mês a mês; retoma de onde parou
uv run scripts/sancoes.py     # cruzamento
```

O `sancoes.py` espera os CSVs do CEIS e do CNEP e os zips mensais de contratos do SIASG em `data/`. Os arquivos gerados ficam fora do git.
