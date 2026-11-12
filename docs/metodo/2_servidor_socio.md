# Tipologia 2: servidor sócio de empresa contratada pelo próprio órgão

## O que procura

Servidores federais que eram sócios de uma empresa privada na data em que o órgão onde trabalham assinou contrato com ela. Em paralelo, servidores que administram empresa privada contratada por qualquer órgão federal.

## Base legal

- Lei 14.133/2021, art. 9º, §1º: o agente público do órgão licitante ou contratante não pode participar, direta ou indiretamente, da licitação ou da execução do contrato. Alcança o sócio comum quando o agente atua no processo.
- Lei 8.112/1990, art. 117, X: o servidor não pode participar de gerência ou administração de sociedade privada. Pode ser só cotista ou acionista. O parágrafo único traz exceções.

## Fontes de dados

| base | quem publica | download |
|---|---|---|
| Sócios e Empresas dos Dados Abertos do CNPJ | Receita Federal | compartilhamento público do Nextcloud da Receita (arquivos.receitafederal.gov.br, lido por WebDAV sem login) |
| Cadastro de servidores do SIAPE | CGU, Portal da Transparência | dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/servidores/ |
| Cadastro de servidores do Banco Central | CGU, Portal da Transparência | mesmo endereço, arquivo do BACEN |
| Contratos do SIASG | CGU, Portal da Transparência | portaldatransparencia.gov.br/download-de-dados/compras |
| Contratos do PNCP, esfera federal | API pública do PNCP | https://pncp.gov.br/api/consulta/v1/contratos |

## Regras do cruzamento

1. **Sócios.** Só sócios pessoa física, com nome, os 6 dígitos visíveis do CPF, qualificação e data de entrada na sociedade.
2. **Servidores.** Retratos semestrais do cadastro, com nome, CPF parcial, cargo, função, situação do vínculo e órgãos de lotação e de exercício.
3. **Servidor e sócio.** Nome normalizado (sem acento nem pontuação) igual e os 6 dígitos do CPF iguais. Os dois cadastros mascaram os mesmos dígitos, do 4º ao 9º.
4. **Sócio e contrato.** Pela raiz do CNPJ (8 dígitos), que junta matriz e filiais.
5. **Servidor na data.** O servidor consta do retrato mais próximo da assinatura, a no máximo 12 meses dela. Sem retrato nessa janela, o contrato fica fora das contagens principais.
6. **Sócio na data.** Data de entrada na sociedade anterior ou igual à assinatura. Entrada posterior fica em grupo separado, para revisão.
7. **Mesmo órgão.** O órgão ou a unidade gestora contratante tem o mesmo nome que o órgão de lotação ou de exercício do servidor, tolerando as abreviações do SIAPE. Toda palavra distintiva de cada lado precisa ter par no outro, e o tipo de instituição precisa bater (universidade, instituto, centro, universidade tecnológica, rural e hospital são tipos diferentes). Os pares de órgão casados são conferidos à mão.
8. **Papel na sociedade.** Administrador é sócio-administrador, administrador, diretor, presidente, sócio-gerente, empresário ou titular de empresa individual. Os demais são sócios comuns.
9. **Empresa privada.** Natureza jurídica do grupo 2 (entidades empresariais), exceto empresa pública e sociedade de economia mista.

**Níveis do indício.**

- Principal: empresa privada, servidor e sócio na data da assinatura, e contratante igual ao órgão do servidor. Separado em sócio comum (Lei 14.133) e administrador (Lei 14.133 e Lei 8.112).
- Secundário: mesmo ministério supervisor, órgão diferente.
- Administrador de empresa privada contratada por qualquer órgão federal (Lei 8.112), com recorte só de estatutários.
- Fora do indício: fundações e associações sem fins lucrativos e estatais, contadas à parte.

## Explicações legítimas que tiram força do indício

- Fundação de apoio da própria universidade ou instituto, dirigida por servidor, como prevê a Lei 8.958/1994.
- Conselheiro ou diretor indicado para estatal.
- Sócio comum que não atuou na licitação nem no contrato.
- Licença para tratar de interesses particulares (Lei 8.112, art. 117, parágrafo único, II), participação em conselho de empresa de que a União é sócia, e cooperativas.
- Regras próprias da dedicação exclusiva de professores.
- Empregados celetistas de empresas públicas não estão sob a Lei 8.112, mas seguem agentes públicos para a Lei 14.133.

## Como medimos falso positivo

- **Colisão dentro do cadastro.** Conta quantas chaves nome + CPF6 apontam para mais de um servidor.
- **Homônimo por acaso.** Os 6 dígitos do CPF dos servidores são embaralhados dentro da mesma região fiscal (9º dígito do CPF) e o casamento é refeito, em 20 simulações. A média de casamentos nas simulações estima quantos pares reais são homônimos. A estimativa supõe CPF uniforme dentro da região. CPFs reais se agrupam por lote de emissão e por família, então a taxa real pode ser maior.
- **Casamento de órgão.** Conferência manual de cada par de órgãos casado nos casos principais.

## Limites conhecidos

- O QSA mostra a composição atual. Quem saiu da sociedade antes não aparece, e a data de entrada é a da última alteração registrada. A contagem é um piso.
- O casamento é exato: nome de casada, abreviação e erro de grafia fazem o par se perder.
- O cadastro não diz se o servidor atuou na licitação ou no contrato.
- Unidades de vínculo direto de um ministério podem aparecer como um órgão só.
- Cobertura de servidores: Executivo civil federal (SIAPE) e Banco Central. Ficam fora militares, estatais com quadro próprio, Legislativo, Judiciário, estados e municípios. Registros "Sigiloso" não trazem CPF.
- Contratos: SIASG de jan/2022 a jan/2025, mais o PNCP federal disponível. O valor do SIASG em atas e contratos sob demanda pode ser o teto, não o gasto.
- Retratos semestrais: quem entrou, saiu ou mudou de órgão entre dois retratos pode ser classificado errado.
- Indício, não infração. Cada caso precisa de conferência antes de qualquer encaminhamento.

## Como rodar

```bash
uv run scripts/qsa.py               # Sócios e Empresas do mês mais recente; zips apagados depois de lidos
uv run scripts/servidor_socio.py    # baixa os cadastros que faltarem e cruza
```

Os arquivos de sócios, de cadastro e o resultado do cruzamento contêm nomes e CPF parcial. Ficam só no disco local, fora do git.
