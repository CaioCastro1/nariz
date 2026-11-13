# Nariz

Código para cruzar bases abertas do Estado brasileiro e detectar indícios de irregularidade:
agendas de autoridades, cadastros de servidores, sanções a empresas, contratos públicos, sócios de
empresas, emendas parlamentares e doações de campanha. Cada indício é ponto de partida para
verificação e revisão humana, não conclusão.

## Tipologias

| # | Tipologia | Método | Script |
|---|---|---|---|
| 1 | Empresa sancionada contratada pelo poder público | [`1_sancoes.md`](docs/metodo/1_sancoes.md) | `scripts/sancoes.py` |
| 2 | Servidor sócio de empresa contratada | [`2_servidor_socio.md`](docs/metodo/2_servidor_socio.md) | `scripts/servidor_socio.py` |
| 3 | Servidor ativo representando entidade privada | [`3_4_servidor_representante_e_quarentena.md`](docs/metodo/3_4_servidor_representante_e_quarentena.md) | `scripts/tipologias_3_4.py` |
| 4 | Quarentena: ex-alto escalão de volta ao próprio órgão | [`3_4_servidor_representante_e_quarentena.md`](docs/metodo/3_4_servidor_representante_e_quarentena.md) | `scripts/porta_giratoria.py`, `scripts/tipologias_3_4.py` |
| 6 | Indícios de empresa de fachada | [`6_fachada.md`](docs/metodo/6_fachada.md) | `scripts/fachada.py` |
| 9 | Emenda paga a empresa de doador da campanha do autor | [`9_emendas_doadores.md`](docs/metodo/9_emendas_doadores.md) | `scripts/emendas_doadores.py` |

A numeração segue o catálogo de tipologias do projeto; as que não aparecem aqui ainda não têm detecção.

O repositório traz código e método. Dados brutos, tabelas casadas e resultados são gerados
localmente em `data/` e não entram no git.

## Como rodar

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12+.

```bash
git clone https://github.com/CaioCastro1/nariz.git && cd nariz
uv sync
mkdir -p data
```

```bash
# 1. Agendas (e-Agendas, CGU)
curl -o data/dados_e-agendas.zip https://dadosabertos-download.cgu.gov.br/dados_e-agendas/dados_e-agendas.zip
uv run scripts/extract.py     # reuniões, participações e pessoas privadas
uv run scripts/resolve.py     # junta grafias da mesma entidade (curadoria/aliases.csv)
uv run scripts/build.py       # agrega -> data/painel.json
uv run scripts/render.py      # painel/template.html + data/painel.json -> painel/index.html

# 2. Servidores (Portal da Transparência): tipologias 3 e 4
uv run scripts/servidores.py 2019-01:2026-08
uv run scripts/servidores.py --bacen 2019-01:2026-08
uv run scripts/porta_giratoria.py
uv run scripts/tipologias_3_4.py

# 3. Contratos e sanções: tipologia 1
#    baixar à mão de portaldatransparencia.gov.br/download-de-dados/{ceis,cnep,compras}
#    -> data/sancoes/AAAAMMDD_CEIS.csv, AAAAMMDD_CNEP.csv, data/contratos/raw/AAAAMM.zip
uv run scripts/pncp.py        # contratos do PNCP, mês a mês, com retomada
uv run scripts/sancoes.py

# 4. Sócios da Receita: tipologias 2 e 6
uv run scripts/qsa.py         # ~2 GB de download, 1 GB em disco
uv run scripts/qsa.py --estab
uv run scripts/servidor_socio.py
uv run scripts/fachada.py

# 5. Emendas e doações (Portal da Transparência e TSE): tipologia 9
uv run scripts/emendas_doadores.py
```

## Painel de agendas

`scripts/build.py` e `scripts/render.py` geram um painel estático com as entidades privadas que mais
se reúnem com o Executivo federal. Decisões de método:

- Unidade: reunião distinta (`ID do registro`). O mesmo ID aparece uma vez por autoridade presente.
- Só "Reunião" e "Audiência"; eventos e audiências públicas ficam fora. Cancelados (assunto com "CANCELAD") saem.
- "Interesse Próprio" não entra. Órgãos públicos, imprensa e registros genéricos ("Advogado") são excluídos do ranking.
- Entidades com CNPJ agrupadas pela raiz (8 dígitos). Sem CNPJ, a chave é o nome normalizado, com
  casamento automático por nome e revisão manual em `curadoria/aliases.csv`.
- Marcas da mesma empresa são unidas (Vivo → Telefônica, CCR → Motiva); subsidiárias com CNPJ próprio ficam separadas.
- Tipo e setor: regras em `scripts/classify.py`, sobrepostas por `curadoria/classificacao.csv` (revisão manual).

Depois de rodar `build.py`, entidades novas sem setor entre as 400 maiores devem ser classificadas em
`curadoria/classificacao.csv`:

```bash
uv run python -c "import json; d=json.load(open('data/painel.json')); print([(e['id'],e['rotulo']) for e in d['entidades'] if e['setor']=='Não classificado'])"
```

Limites: a agenda pessoal do Presidente não está no e-Agendas; os últimos meses ainda recebem
registros atrasados; fornecedores de TI e concessionárias aparecem por reuniões de contrato e
regulação, não necessariamente lobby.

## Estrutura

```
scripts/       um script por etapa ou tipologia
docs/metodo/   regras, base legal e limites de cada tipologia
curadoria/     aliases e classificação de entidades revisados à mão
painel/        template do painel de agendas
```

## Licença

Código sob licença [MIT](LICENSE). Documentação em `docs/` sob
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt_BR).
