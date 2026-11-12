"""Baixa contratos do PNCP (Portal Nacional de Contratações Públicas) pela API
pública de consulta, de todas as esferas, e guarda só as colunas úteis.

Uso: uv run scripts/pncp.py                      (2023-01 a 2026-10)
     uv run scripts/pncp.py 202301 202302 ...    (ou 2023-01:2026-10)

API: https://pncp.gov.br/api/consulta/v1/contratos (dataInicial, dataFinal em
AAAAMMDD, pagina, tamanhoPagina de no máximo 500). O filtro de data é a de
publicação no PNCP, não a de assinatura: um contrato assinado em dez/2022 pode
aparecer em jan/2023. Por isso cada mês traz a assinatura que tiver, e o
sancoes.py deduplica pelo id do PNCP.

Grava data/contratos/pncp/AAAAMM.parquet, um por mês. Mês que já tem parquet é
pulado (retomada); o parquet só é gravado com o mês completo. Um mês
interrompido guarda as páginas já baixadas em AAAAMM.part e retoma de onde parou.

Regras:
- Pausa de PAUSA segundos entre requisições.
- Página que dá HTTP 500 em todas as tentativas é refeita em páginas de 100 itens.
- Erro 429 (limite de taxa; respeita o Retry-After), 5xx, timeout ou queda de conexão: tenta de novo com espera crescente.
- Se a API responder 401, 403, devolver HTML/captcha em vez de JSON ou
  falhar TENTATIVAS vezes seguidas, o script PARA e imprime o motivo. Não há
  tentativa de contornar bloqueio.
"""
import calendar
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import polars as pl

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "contratos" / "pncp"
URL = "https://pncp.gov.br/api/consulta/v1/contratos"
TAMANHO = 500  # máximo aceito pela API
PAUSA = 2.0  # segundos entre requisições
TENTATIVAS = 5
PADRAO = "2023-01:2026-10"
BLOQUEIO = {401, 403}


class Bloqueado(Exception):
    pass


def meses(args):
    out = []
    for a in args:
        if ":" in a:
            ini, fim = (int(x.replace("-", "")) for x in a.split(":"))
            y, m = divmod(ini, 100)
            while y * 100 + m <= fim:
                out.append(f"{y}{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        else:
            out.append(a.replace("-", ""))
    return out


def ultimo_dia(mes):
    return calendar.monthrange(int(mes[:4]), int(mes[4:]))[1]


def pega(mes, pagina, tamanho=TAMANHO):
    url = f"{URL}?dataInicial={mes}01&dataFinal={mes}{ultimo_dia(mes):02d}&pagina={pagina}&tamanhoPagina={tamanho}"
    for i in range(TENTATIVAS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                corpo = r.read()
                tipo = r.headers.get("Content-Type", "")
            time.sleep(PAUSA)
            if r.status == 204 or not corpo:
                return {"data": [], "totalPaginas": 0}
            if "json" not in tipo:
                raise Bloqueado(f"resposta não-JSON ({tipo}): {corpo[:200]!r}")
            return json.loads(corpo)
        except urllib.error.HTTPError as e:
            if e.code in BLOQUEIO:
                raise Bloqueado(f"HTTP {e.code} em {url}")
            if e.code == 400:
                raise
            erro = f"HTTP {e.code}"
            if e.code == 429:  # limite de taxa, não bloqueio: respeita Retry-After e tenta de novo
                time.sleep(int(e.headers.get("Retry-After") or 0))
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, json.JSONDecodeError) as e:
            erro = repr(e)
        espera = 30 * 2 ** i
        print(f"{mes} p{pagina}: {erro}; esperando {espera}s ({i + 1}/{TENTATIVAS})", file=sys.stderr)
        time.sleep(espera)
    raise Bloqueado(f"{TENTATIVAS} falhas seguidas em {url}: {erro}")


def linha(c):
    o, u = c.get("orgaoEntidade") or {}, c.get("unidadeOrgao") or {}
    return {
        "id_pncp": c.get("numeroControlePNCP"),
        "cnpj": c.get("niFornecedor"),
        "tipo_pessoa": c.get("tipoPessoa"),
        "contratado": c.get("nomeRazaoSocialFornecedor"),
        "orgao_cnpj": o.get("cnpj"),
        "orgao": o.get("razaoSocial"),
        "esfera": o.get("esferaId"),  # F federal, E estadual, M municipal, D distrital
        "poder": o.get("poderId"),  # E executivo, L legislativo, J judiciário
        "uf": u.get("ufSigla"),
        "municipio": u.get("municipioNome"),
        "cod_ibge": u.get("codigoIbge"),
        "cod_unidade": u.get("codigoUnidade"),  # UASG, nas compras federais
        "unidade": u.get("nomeUnidade"),
        "contrato": c.get("numeroContratoEmpenho"),
        "ano": c.get("anoContrato"),
        "sequencial": c.get("sequencialContrato"),
        "assinatura": c.get("dataAssinatura"),
        "vigencia_inicio": c.get("dataVigenciaInicio"),
        "fim_vigencia": c.get("dataVigenciaFim"),
        "publicacao_pncp": (c.get("dataPublicacaoPncp") or "")[:10] or None,
        "valor_inicial": c.get("valorInicial"),
        "valor_global": c.get("valorGlobal"),
        "objeto": c.get("objetoContrato"),
        "tipo_contrato": (c.get("tipoContrato") or {}).get("nome"),
        "categoria": (c.get("categoriaProcesso") or {}).get("nome"),
        "compra_pncp": c.get("numeroControlePncpCompra"),
        "url": f"https://pncp.gov.br/app/contratos/{o.get('cnpj')}/{c.get('anoContrato')}/{c.get('sequencialContrato')}"
               if o.get("cnpj") else None,
    }


def processa(mes):
    dest = OUT / f"{mes}.parquet"
    if dest.exists():
        print(mes, "já existe", file=sys.stderr)
        return
    # progresso parcial: cada página vira uma linha de AAAAMM.part; se o script cair
    # (503 longo, queda de rede), a próxima execução retoma da página seguinte
    part = OUT / f"{mes}.part"
    linhas, pagina, total = [], 1, 1
    if part.exists():
        for l in part.read_text().splitlines():
            ps = json.loads(l)
            linhas += ps["linhas"]
            pagina, total = ps["pagina"] + 1, ps["total"]
    while pagina <= total:
        novas = []
        try:
            d = pega(mes, pagina)
            total = d.get("totalPaginas") or 0
            novas = [linha(c) for c in d["data"]]
        except Bloqueado as e:
            # Algumas páginas dão HTTP 500 sempre (dez/2024 p38, por exemplo), enquanto as vizinhas
            # respondem. Não é bloqueio: refaz o mesmo trecho em páginas de 100 itens.
            if not str(e).startswith(f"{TENTATIVAS} falhas") or not str(e).endswith("HTTP 500"):
                raise
            print(f"{mes} p{pagina}: HTTP 500 persistente; refazendo em páginas de 100", file=sys.stderr)
            f = TAMANHO // 100
            for sub in range((pagina - 1) * f + 1, pagina * f + 1):
                novas += [linha(c) for c in pega(mes, sub, 100)["data"]]
            total = max(total, pagina)
        linhas += novas
        with part.open("a") as fh:
            fh.write(json.dumps({"pagina": pagina, "total": total, "linhas": novas}) + "\n")
        if pagina % 20 == 0:
            print(f"{mes}: pág {pagina}/{total}, {len(linhas)} linhas", file=sys.stderr)
        pagina += 1
    df = pl.DataFrame(linhas, infer_schema_length=None, schema_overrides={
        "ano": pl.Int64, "sequencial": pl.Int64, "valor_inicial": pl.Float64, "valor_global": pl.Float64,
        "cnpj": pl.String, "cod_ibge": pl.String, "cod_unidade": pl.String})
    df = df.with_columns(pl.col(c).str.to_date("%Y-%m-%d", strict=False)
                         for c in ("assinatura", "vigencia_inicio", "fim_vigencia", "publicacao_pncp"))
    df.write_parquet(dest.with_suffix(".tmp"), compression="zstd")
    dest.with_suffix(".tmp").rename(dest)
    part.unlink(missing_ok=True)
    print(f"{mes}: {df.height} contratos, {dest.stat().st_size / 1e6:.1f} MB", file=sys.stderr)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for mes in meses(sys.argv[1:] or [PADRAO]):
        try:
            processa(mes)
        except Bloqueado as e:
            sys.exit(f"PARADO em {mes}: {e}\nNão contornar; relatar ao responsável.")


if __name__ == "__main__":
    main()
