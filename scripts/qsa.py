"""Baixa os arquivos de Sócios (QSA) dos Dados Abertos do CNPJ da Receita Federal
e guarda só os sócios pessoa física.

Uso: uv run scripts/qsa.py            (mês mais recente publicado)
     uv run scripts/qsa.py 2026-10    (mês específico)
     uv run scripts/qsa.py --estab    (opcional: Estabelecimentos*.zip do mês de meta.json, só dos
                                       CNPJs que aparecem nos contratos; ver estabelecimentos())

Os arquivos ficam num compartilhamento público do Nextcloud da Receita (SERPRO+);
o endereço antigo arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/
redireciona para a tela de login. O compartilhamento é lido por WebDAV, sem senha,
com o token do link público como usuário.

Layout do arquivo SOCIOCSV (sem cabeçalho, ";" e latin1; "NOVO LAYOUT DOS DADOS
ABERTOS DO CNPJ"): cnpj_basico, identificador (1 PJ, 2 PF, 3 estrangeiro), nome,
CPF/CNPJ do sócio (PF mascarado como ***NNNNNN**), qualificação, data de entrada
(AAAAMMDD), país, CPF do representante legal, nome do representante,
qualificação do representante, faixa etária.

EMPRECSV: cnpj_basico, razão social, natureza jurídica, qualificação do
responsável, capital social, porte, ente federativo responsável.

Cada zip (Socios: 10 partes, ~650 MB; Empresas: 10 partes, ~1,3 GB) é baixado
para data/qsa/, lido em blocos direto do zip, sem descompactar em disco, e
apagado. Ficam:
- data/qsa/socios.parquet: cnpj_basico, nome_socio, nome_norm, cpf6 (os 6 dígitos
  do meio, iguais aos que o Portal da Transparência mostra), cod_qualificacao,
  qualificacao e data_entrada;
- data/qsa/empresas.parquet: cnpj_basico, natureza_juridica, natureza,
  capital_social, porte, ente_federativo (serve para separar sociedade
  empresária de fundação, associação e estatal);
- data/qsa/estabelecimentos.parquet (só com --estab): CNPJ completo, situação cadastral, data de
  início da atividade, CNAE principal e endereço dos estabelecimentos contratados;
- data/qsa/qualificacoes.csv, naturezas.csv e meta.json.
"""
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from base64 import b64encode
from pathlib import Path

import polars as pl

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "qsa"
TOKEN = "YggdBLfdninEJX9"  # link público arquivos.receitafederal.gov.br/index.php/s/<TOKEN>
DAV = "https://arquivos.receitafederal.gov.br/public.php/webdav/"
LIMITE = 8 * 2**30  # para se data/qsa passar disso
BLOCO = 256 * 2**20
COLS = ["cnpj_basico", "identificador", "nome_socio", "cpf_cnpj", "cod_qualificacao", "data_entrada",
        "pais", "cpf_representante", "nome_representante", "qualif_representante", "faixa_etaria"]
# EMPRECSV: a razão social fica fora (os contratos já trazem o nome do contratado)
COLS_EMPRESAS = ["cnpj_basico", "razao_social", "natureza_juridica", "qualif_responsavel", "capital_social",
                 "porte", "ente_federativo"]


def req(caminho, metodo="GET", depth=None):
    r = urllib.request.Request(DAV + caminho, method=metodo, headers={
        "Authorization": "Basic " + b64encode(f"{TOKEN}:".encode()).decode(), "User-Agent": "Mozilla/5.0"})
    if depth is not None:
        r.add_header("Depth", depth)
    return urllib.request.urlopen(r, timeout=600)


def lista(caminho=""):
    with req(caminho, "PROPFIND", "1") as r:
        x = r.read().decode()
    return [h.rstrip("/").rsplit("/", 1)[-1] for h in re.findall(r"<d:href>([^<]*)", x)][1:]


def baixa(caminho, dest):
    with req(caminho) as r, dest.open("wb") as f:
        if "text/html" in r.headers.get("Content-Type", ""):
            raise SystemExit(f"{caminho}: o servidor devolveu HTML (login/verificação?); parando")
        shutil.copyfileobj(r, f, 2**20)


def tamanho():
    return sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())


def le_blocos(zpath, cols, seleciona, prefixo):
    """Lê o CSV de dentro do zip em blocos de ~256 MB, sem descompactar em disco,
    e grava um parquet por bloco com o que seleciona() devolver."""
    with zipfile.ZipFile(zpath) as z, z.open(z.namelist()[0]) as f:
        resto, i = b"", 0
        while True:
            b = f.read(BLOCO)
            fim = not b
            b = resto + b
            if not b:
                break
            corte = len(b) if fim else b.rfind(b"\n") + 1
            bloco, resto = b[:corte], b[corte:]
            d = pl.read_csv(io.BytesIO(bloco.decode("latin1").encode()), separator=";", has_header=False,
                            new_columns=cols, infer_schema=False)
            seleciona(d).write_parquet(OUT / f"{prefixo}_{i:02d}.parquet")
            i += 1
            if fim:
                break


def socios_pf(d):
    return d.filter(pl.col("identificador") == "2").select(
        "cnpj_basico", "nome_socio",
        pl.col("cpf_cnpj").str.extract(r"^\*{3}(\d{6})\*{2}$", 1).alias("cpf6"),
        "cod_qualificacao",
        pl.col("data_entrada").str.to_date("%Y%m%d", strict=False).alias("data_entrada"),
    )


def empresas(d):
    return d.select("cnpj_basico", "natureza_juridica",
                    pl.col("capital_social").str.replace(",", ".").cast(pl.Float64, strict=False),
                    "porte", "ente_federativo")


def tabela(mes, nome, cols):
    """Tabelas de código (Qualificacoes, Naturezas) do mesmo mês."""
    baixa(f"{mes}/{nome}.zip", OUT / "_t.zip")
    with zipfile.ZipFile(OUT / "_t.zip") as z:
        t = pl.read_csv(io.BytesIO(z.read(z.namelist()[0]).decode("latin1").encode()), separator=";",
                        has_header=False, new_columns=cols, infer_schema=False)
    (OUT / "_t.zip").unlink()
    return t


def baixa_partes(mes, arquivos, cols, seleciona, tag):
    for a in arquivos:
        parte = re.search(r"\d+", a).group()
        if list(OUT.glob(f"_{tag}{parte}_*.parquet")):
            print(a, "já lido", file=sys.stderr)
            continue
        z = OUT / a
        if not (z.exists() and zipfile.is_zipfile(z)):  # zip completo de uma execução interrompida
            baixa(f"{mes}/{a}", z)
        le_blocos(z, cols, seleciona, f"_{tag}{parte}")
        z.unlink()
        print(a, "ok", f"{tamanho() / 2**30:.2f} GB em data/qsa", file=sys.stderr)
        if tamanho() > LIMITE:
            raise SystemExit("data/qsa passou de 8 GB; parando")
    return sorted(OUT.glob(f"_{tag}*.parquet"))


def norm_expr(c):
    """O mesmo que extract.norm, vetorizado (25 milhões de nomes)."""
    return (pl.col(c).str.normalize("NFKD").str.replace_all(r"[^\x00-\x7F]", "")
            .str.replace_all(r"[^A-Za-z0-9 ]+", " ").str.to_uppercase()
            .str.replace_all(r"\s+", " ").str.strip_chars())


COLS_ESTAB = ["cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz_filial", "nome_fantasia", "situacao",
              "data_situacao", "motivo_situacao", "cidade_exterior", "pais", "data_inicio", "cnae_principal",
              "cnae_secundaria", "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
              "uf", "municipio", "ddd1", "tel1", "ddd2", "tel2", "ddd_fax", "fax", "email", "situacao_especial",
              "data_situacao_especial"]


def estabelecimentos():
    """Estabelecimentos*.zip do mês de meta.json, um por vez, mantendo só os CNPJs (14 dígitos) que
    aparecem nos contratos (sancoes.contratos()). Opt-in: não roda no fluxo padrão."""
    meta_p = OUT / "meta.json"
    meta = json.loads(meta_p.read_text())
    mes = meta["mes"]
    arquivos = sorted(a for a in lista(mes + "/") if a.startswith("Estabelecimentos"))
    if not arquivos:
        raise SystemExit("faltam Estabelecimentos*.zip no mês " + mes)
    sys.path.insert(0, str(Path(__file__).parent))
    from sancoes import contratos
    cn = contratos().select("cnpj").unique()
    print(len(arquivos), "partes;", cn.height, "CNPJs de contratos", file=sys.stderr)

    def sel(d):
        d = d.with_columns(pl.concat_str("cnpj_basico", "cnpj_ordem", "cnpj_dv").alias("cnpj"))
        d = d.join(cn, on="cnpj", how="semi")
        return d.select(
            "cnpj", "matriz_filial", "situacao",
            pl.col("data_situacao").str.to_date("%Y%m%d", strict=False),
            "motivo_situacao",
            pl.col("data_inicio").str.to_date("%Y%m%d", strict=False),
            "cnae_principal", "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep", "uf", "municipio")

    partes = baixa_partes(mes, arquivos, COLS_ESTAB, sel, "est")
    e = pl.scan_parquet(partes).unique("cnpj").collect()
    e.write_parquet(OUT / "estabelecimentos.parquet", compression="zstd")
    for p in partes:
        p.unlink()
    meta.update({"arquivos_estabelecimentos": arquivos, "estabelecimentos": e.height})
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(e.height, "estabelecimentos", file=sys.stderr)


def main():
    OUT.mkdir(exist_ok=True)
    if sys.argv[1:] == ["--estab"]:
        return estabelecimentos()
    meses = sorted(m for m in lista() if re.fullmatch(r"\d{4}-\d{2}", m))
    mes = sys.argv[1] if len(sys.argv) > 1 else meses[-1]
    arquivos = lista(mes + "/")
    socios = sorted(a for a in arquivos if a.startswith("Socios"))
    emp = sorted(a for a in arquivos if a.startswith("Empresas"))
    print(mes, socios, emp, file=sys.stderr)
    if not socios or not emp:
        raise SystemExit("faltam arquivos Socios*.zip ou Empresas*.zip no mês " + mes)
    meta_p = OUT / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    if meta.get("mes") not in (None, mes):
        meta = {}

    if not (OUT / "socios.parquet").exists() or "socios_pf" not in meta:
        q = tabela(mes, "Qualificacoes", ["cod_qualificacao", "qualificacao"])
        q.write_csv(OUT / "qualificacoes.csv")
        partes = baixa_partes(mes, socios, COLS, socios_pf, "parte")
        s = pl.scan_parquet(partes).join(q.lazy(), on="cod_qualificacao", how="left").collect()
        s = s.with_columns(norm_expr("nome_socio").alias("nome_norm"))
        s.write_parquet(OUT / "socios.parquet", compression="zstd")
        for p in partes:
            p.unlink()
        meta.update({"mes": mes, "arquivos": socios, "socios_pf": s.height,
                     "com_cpf6": s.filter(pl.col("cpf6").is_not_null()).height,
                     "cnpj_basicos": s["cnpj_basico"].n_unique()})
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        del s

    if not (OUT / "empresas.parquet").exists() or "empresas" not in meta:
        n = tabela(mes, "Naturezas", ["natureza_juridica", "natureza"])
        n.write_csv(OUT / "naturezas.csv")
        partes = baixa_partes(mes, emp, COLS_EMPRESAS, empresas, "emp")
        e = pl.scan_parquet(partes).join(n.lazy(), on="natureza_juridica", how="left").collect()
        e.write_parquet(OUT / "empresas.parquet", compression="zstd")
        for p in partes:
            p.unlink()
        meta.update({"mes": mes, "arquivos_empresas": emp, "empresas": e.height})
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(meta, file=sys.stderr)


if __name__ == "__main__":
    main()
