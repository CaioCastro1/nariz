# Tipologia 9: emenda parlamentar paga a empresa cujo sócio doou à campanha do autor

## O que procura

Pagamentos de emenda individual a uma pessoa jurídica que tem, entre os sócios, alguém que doou à campanha do parlamentar autor da emenda antes do pagamento. É um indício de proximidade entre autor e beneficiário, não de irregularidade.

## Base legal

- Doar para campanha é legal. Pessoa física pode doar dentro dos limites da Lei 9.504/1997 (art. 23). Pessoa jurídica não pode doar desde 2015 (STF, ADI 4650, e Lei 13.165/2015), por isso o elo é o sócio pessoa física.
- Emendas individuais ao orçamento: Constituição, art. 166, §§ 9º a 11.
- A pergunta de fundo é de impessoalidade e moralidade na destinação do recurso (Constituição, art. 37, caput). A tipologia não aponta infração específica: aponta onde vale conferir se a emenda seguiu critério técnico.

## Fontes de dados

| base | quem publica | download |
|---|---|---|
| Emendas parlamentares por favorecido (pagamentos, com CNPJ) | CGU, Portal da Transparência | https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO |
| Prestação de contas de candidatos, receitas (2018 e 2022) | TSE | https://cdn.tse.jus.br/estatistica/sead/odsele/ |
| Candidatos (consulta_cand, 2018 e 2022) | TSE | mesmo endereço |
| Sócios dos Dados Abertos do CNPJ | Receita Federal | compartilhamento público do Nextcloud da Receita (arquivos.receitafederal.gov.br, lido por WebDAV sem login) |

## Regras do cruzamento

- **Universo.** Só emenda individual paga a favorecido pessoa jurídica, de jan/2019 em diante. Emendas de bancada, de comissão e de relator ficam de fora, porque não têm um autor.
- **Autor e candidato.** Pelo nome normalizado (nome de urna ou nome civil), entre os candidatos a deputado federal e senador de 2018 e 2022. Eleitos têm preferência. Nome que segue ambíguo fica de fora.
- **Sócio e doador.** Nome normalizado mais os 6 dígitos do meio do CPF, comparando o nome da Receita com o declarado ao TSE.
- **Favorecido.** Pela raiz do CNPJ (8 dígitos). Pagamentos idênticos (mesma emenda, empresa, mês e valor) contam uma vez.
- **Doação antes do pagamento.** A eleição de 2018 vale para pagamentos até out/2022; a de 2022, para pagamentos de nov/2022 em diante (as duas valem depois disso).
- **Sócio na data.** Entrada na sociedade anterior ou igual ao mês do pagamento. Quando o QSA não traz a data, o par entra.
- **Fora.** Doação do autor a si mesmo (autofinanciamento) e dinheiro que chegou ao candidato via partido (doador originário).

**Força do indício.**

- Forte: o sócio doou ao próprio autor da emenda antes do pagamento, e já era sócio na data.
- Forte sem data de sociedade: mesma regra, sem exigir a data de entrada. Serve de teto de sensibilidade.
- Fraco: o sócio não doou ao autor, mas doou a outro candidato do mesmo partido e da mesma UF. É aproximação de "doação ao partido do autor" e é mais ruidoso.
- Dentro do forte, sociedades empresárias são separadas de associações privadas, em que o "sócio" do QSA é diretor ou presidente, não dono.

## Explicações legítimas que tiram força do indício

- O empresário da cidade apoia o candidato da cidade, e a emenda vai para a cidade. Doação e emenda podem coincidir por geografia.
- Associação privada cujo dirigente doou. O elo é de dirigente, não de dono.
- Emenda com critério técnico documentado, ou com outros beneficiários possíveis tratados da mesma forma.
- Doação a outro candidato do mesmo partido pode ter motivo local e partidário sem elo com o autor.

## Como medimos falso positivo

- **Homônimo pelo CPF parcial.** Os 6 dígitos de cada doador são sorteados de novo dentro da mesma região fiscal (9º dígito do CPF) e o casamento é refeito, em 20 simulações. A média dá o número esperado de pessoas e de pares autor × empresa que casariam por acaso.
- **Linha de base de acaso.** O autor de cada pagamento é trocado por outro autor de pagamentos da mesma UF, mantendo empresa, valor e mês, e o casamento é refeito, em 20 simulações. Compara-se o observado com o esperado. A troca dentro da UF não elimina a coincidência geográfica dentro do município, então o excesso sobre o acaso não prova nada sobre a emenda.
- **Linha de base de propensão a doar.** Mede-se quantos sócios de favorecidos doam a qualquer parlamentar, para saber quão raro é o elo.

## Limites conhecidos

- Só doação direta de pessoa física. Fundo Eleitoral, Fundo Partidário e repasses do partido ao candidato não aparecem.
- Só eleições de 2018 e 2022 e só deputado federal e senador. Autores sem candidatura nessas eleições (senadores eleitos antes, suplentes que assumiram, nomes que mudaram) não entram. O alcance é um piso.
- Pagamentos antes de 2019 ficam fora.
- O QSA mostra a composição atual. Sócio que saiu antes não aparece.
- O casamento de autor por nome pode falhar ou ficar ambíguo.
- "Mesmo partido e mesma UF" é aproximação. As contas dos diretórios não são abertas aqui.
- A raiz do CNPJ agrupa matriz e filiais.
- Um achado é só o primeiro filtro. Antes de encaminhar, é preciso ver o critério técnico da emenda, a existência de outros beneficiários e o objeto entregue.

## Como rodar

```bash
uv run scripts/qsa.py                        # sócios do CNPJ, se ainda não baixados
uv run scripts/emendas_doadores.py --baixar  # só baixa e reduz as bases de emendas e do TSE
uv run scripts/emendas_doadores.py           # baixa o que faltar e cruza
```

Os zips do TSE são lidos em streaming e apagados. As bases reduzidas e o resultado do cruzamento ficam fora do git.
