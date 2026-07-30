# -*- coding: utf-8 -*-
"""
processa_mes.py — Processador mensal ANAC
Mescla Básica + Combinada + Aircrafts e gera o CSV processado (75 colunas, visão DEP).

Uso:
  python processa_mes.py 2026-01
  python processa_mes.py 2020-01 --saida C:\Temp

Replica fielmente a lógica do Power Query (fnBasicaMes + fnCombMes + Aircrafts).
"""

import argparse
import os
import sys
import time

import pandas as pd

# ── Caminhos padrão para uso LOCAL (.bat no PC corporativo) ─────────
# No robô do GitHub, estes são ignorados: o main.py passa os caminhos
# das bases baixadas do Drive (_tmp/bases/) e a pasta de saída temporária.
PASTA_BRUTOS = (
    r"C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE"
    r"\BI Operações - BI\Anac\Movimentacao\Raw"
)
AIRCRAFTS_PATH = (
    r"C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE"
    r"\BI Operações - BI\Bases\Aircraft.xlsx"
)
PASTA_SAIDA = (
    r"C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE"
    r"\BI Operações - BI\Anac\Movimentacao\Processado"
)  # noqa: W605

# Nome do arquivo de aeronaves dentro da pasta de bases (Drive ou local).
AIRCRAFT_NOME = "Aircraft.xlsx"

# ── Colunas que o M converte pra Int64 na básica ────────────────────
COLUNAS_INT_BASICA = [
    "nr_assentos_ofertados", "kg_payload", "km_distancia",
    "nr_passag_pagos", "nr_passag_gratis",
    "kg_bagagem_livre", "kg_bagagem_excesso",
    "kg_carga_paga", "kg_carga_gratis", "kg_correio",
]

# ── Colunas removidas (calendário, IDs internos etc.) ───────────────
COLUNAS_REMOVER = [
    "id_empresa", "nm_empresa", "nm_pais", "ds_tipo_empresa",
    "nr_singular", "id_di", "cd_di", "ds_grupo_di",
    "nr_ano_referencia", "nr_semestre_referencia", "nm_semestre_referencia",
    "nr_trimestre_referencia", "nm_trimestre_referencia",
    "nr_mes_referencia", "nm_mes_referencia",
    "nr_semana_referencia", "nm_dia_semana_referencia",
    "nr_dia_referencia", "nr_ano_mes_referencia",
    "cd_tipo_linha", "id_tipo_linha",
    "ds_natureza_tipo_linha", "ds_servico_tipo_linha",
    "nr_ano_partida_real", "nr_semestre_partida_real",
    "nm_semestre_partida_real", "nr_trimestre_partida_real",
    "nm_trimestre_partida_real", "nr_mes_partida_real",
    "nm_mes_partida_real", "nr_semana_partida_real",
    "nm_dia_semana_partida_real", "nr_dia_partida_real",
    "nr_ano_mes_partida_real",
    "id_aerodromo_origem",
    "nr_ano_chegada_real", "nr_semestre_chegada_real",
    "nm_semestre_chegada_real", "nr_trimestre_chegada_real",
    "nm_trimestre_chegada_real", "nr_mes_chegada_real",
    "nm_mes_chegada_real", "nr_semana_chegada_real",
    "nm_dia_semana_chegada_real", "nr_dia_chegada_real",
    "nr_ano_mes_chegada_real",
    "id_equipamento", "id_aerodromo_destino",
    "nr_pax_gratis_km", "nr_carga_paga_km", "nr_carga_gratis_km",
    "nr_correio_km", "nr_bagagem_paga_km", "nr_bagagem_gratis_km",
    "nr_atk", "nr_rtk",
    "id_arquivo", "nm_arquivo", "nr_linha", "dt_sistema",
    "id_basica", "dt_referencia",
]

# ── Renomear colunas (original → amigável) ──────────────────────────
RENAME_MAP = {
    "sg_empresa_icao": "Airline Icao",
    "nr_voo": "Voo",
    "ds_di": "Id Voo",
    "ds_tipo_linha": "Id Linha",
    "sg_icao_origem": "Aero Icao",
    "nr_etapa": "Etapa",
    "sg_equipamento_icao": "Aircraft",
    "ds_modelo": "Acft Modelo",
    "ds_matricula": "Matrícula",
    "sg_icao_destino": "OD Icao",
    "nr_escala_destino": "Escala",
    "lt_combustivel": "Combustível (L)",
    "nr_assentos_ofertados": "Seats",
    "kg_payload": "Payload Capacidade (Kg)",
    "km_distancia": "Distância (Km)",
    "nr_passag_pagos": "PAX Pagos",
    "nr_passag_gratis": "PAX Grátis",
    "kg_bagagem_livre": "Bagagem Livre (Kg)",
    "kg_bagagem_excesso": "Bagagem Excesso (Kg)",
    "kg_carga_paga": "Carga Paga (Kg)",
    "kg_carga_gratis": "Carga Grátis (Kg)",
    "kg_correio": "Correios (Kg)",
    "kg_peso": "Peso Útil (Kg)",
    "nr_horas_voadas": "Horas Voadas",
    "nr_decolagem": "Decolagens",
    "nr_velocidade_media": "Vméd (Km/h)",
    "nr_ask": "Ask",
    "nr_rpk": "Rpk",
    "sg_empresa_iata": "Airline",
    "sg_iata_origem": "Aero",
    "sg_iata_destino": "OD",
    "ds_natureza_etapa": "Natureza",
    "nm_aerodromo_origem": "Aeroporto",
    "nm_municipio_origem": "Cidade",
    "sg_uf_origem": "UF",
    "nm_regiao_origem": "Região",
    "nm_pais_origem": "País",
    "nm_continente_origem": "Continente",
    "nm_aerodromo_destino": "OD Aeroporto",
    "nm_municipio_destino": "OD Cidade",
    "sg_uf_destino": "OD UF",
    "nm_regiao_destino": "OD Região",
    "nm_pais_destino": "OD País",
    "nm_continente_destino": "OD Continente",
    "hr_partida_real": "Hora",
    "dt_partida_real": "Data",
    "hr_chegada_real": "OD Hora",
    "dt_chegada_real": "OD Data",
}

# ── Colunas que recebem Text.Proper ─────────────────────────────────
COLUNAS_PROPER = [
    "Id Voo", "Id Linha", "Natureza",
    "Aeroporto", "Cidade", "Região", "País", "Continente",
    "OD Aeroporto", "OD Cidade", "OD Região", "OD País", "OD Continente",
    "Acft Modelo",
]

# ── Ordem final das 75 colunas ──────────────────────────────────────
COLUNAS_SAIDA = [
    # Identificação/voo
    "Airline Icao", "Airline", "Voo", "Fln Icao", "Fln",
    "Id Voo", "Id Linha", "Natureza", "Tipo", "Base", "Etapa", "Escala",
    # Tempo
    "Hora", "Data", "OD Hora", "OD Data",
    # Origem geo
    "Aero Icao", "Aero", "Aeroporto", "Cidade", "UF", "Região", "País", "Continente",
    # Destino geo
    "OD Icao", "OD", "OD Aeroporto", "OD Cidade", "OD UF", "OD Região", "OD País", "OD Continente",
    # Aeronave
    "Aircraft", "Acft Modelo", "Matrícula", "Acft Group", "Mtow", "Acft Fra Group",
    # Métricas básica
    "Combustível (L)", "Seats", "Payload Capacidade (Kg)", "Distância (Km)",
    "PAX Pagos", "PAX Grátis",
    "Bagagem Livre (Kg)", "Bagagem Excesso (Kg)",
    "Carga Paga (Kg)", "Carga Grátis (Kg)", "Correios (Kg)",
    "Decolagens", "Horas Voadas", "Peso Útil (Kg)", "Vméd (Km/h)", "Ask", "Rpk",
    # Calculadas
    "Pax Total", "LF", "Cargo Total", "Group",
    # Chaves
    "Chave", "KeyTkt",
    # Combinada
    "CD Dest: PAX Pagos", "CD Dest: PAX Grátis",
    "CD Dest: Bags Livre (kg)", "CD Dest: Bags Excesso (kg)",
    "CD Dest: Carga Paga (kg)", "CD Dest: Carga Grátis (kg)",
    "CD Dest: Correios (kg)",
    "CI Dest: PAX Pagos", "CI Dest: PAX Grátis",
    "CI Dest: Bags Livre (kg)", "CI Dest: Bags Excesso (kg)",
    "CI Dest: Carga Paga (kg)", "CI Dest: Carga Grátis (kg)",
    "CI Dest: Correios (kg)",
]


# ════════════════════════════════════════════════════════════════════
# Funções de processamento
# ════════════════════════════════════════════════════════════════════

def encontrar_arquivo(pasta, prefixo, ano, mes):
    """Tenta com hífen primeiro, depois sem."""
    nome_hifen = f"{prefixo}{ano}-{mes:02d}.txt"
    nome_junto = f"{prefixo}{ano}{mes:02d}.txt"
    caminho = os.path.join(pasta, nome_hifen)
    if os.path.isfile(caminho):
        return caminho
    caminho2 = os.path.join(pasta, nome_junto)
    if os.path.isfile(caminho2):
        return caminho2
    return None


def processar_combinada(caminho_comb):
    """
    Lê a combinada e retorna a tabela agrupada por Chave
    com as 14 colunas CD/CI (soma por direção D/I do cd_cotran).
    """
    df = pd.read_csv(caminho_comb, sep=";", encoding="cp1252", dtype=str)
    df.columns = df.columns.str.strip()

    # Construir Chave idêntica à do M
    df["Chave"] = (
        df["sg_empresa_icao"] + "-" +
        df["nr_voo"] + "-" +
        df["dt_referencia"] + "-" +
        df["sg_icao_origem"] + "-" +
        df["sg_icao_destino"]
    )

    # Converter campos numéricos necessários
    campos_num = [
        "nr_passag_pagos", "nr_passag_gratis",
        "kg_bagagem_livre", "kg_bagagem_excesso",
        "kg_carga_paga", "kg_carga_gratis", "kg_correio",
    ]
    for c in campos_num:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    is_d = df["cd_cotran"] == "D"
    is_i = df["cd_cotran"] == "I"

    # CD (Cabotagem Doméstica) e CI (Cabotagem Internacional)
    df["CD: PAX Pagos"]           = df["nr_passag_pagos"].where(is_d, 0)
    df["CD: PAX Grátis"]          = df["nr_passag_gratis"].where(is_d, 0)
    df["CD: Bagagem Livre (kg)"]  = df["kg_bagagem_livre"].where(is_d, 0)
    df["CD: Bagagem Excesso (kg)"]= df["kg_bagagem_excesso"].where(is_d, 0)
    df["CD: Carga Paga (kg)"]     = df["kg_carga_paga"].where(is_d, 0)
    df["CD: Carga Grátis (kg)"]   = df["kg_carga_gratis"].where(is_d, 0)
    df["CD: Correios (kg)"]       = df["kg_correio"].where(is_d, 0)

    df["CI: PAX Pagos"]           = df["nr_passag_pagos"].where(is_i, 0)
    df["CI: PAX Grátis"]          = df["nr_passag_gratis"].where(is_i, 0)
    df["CI: Bagagem Livre (kg)"]  = df["kg_bagagem_livre"].where(is_i, 0)
    df["CI: Bagagem Excesso (kg)"]= df["kg_bagagem_excesso"].where(is_i, 0)
    df["CI: Carga Paga (kg)"]     = df["kg_carga_paga"].where(is_i, 0)
    df["CI: Carga Grátis (kg)"]   = df["kg_carga_gratis"].where(is_i, 0)
    df["CI: Correios (kg)"]       = df["kg_correio"].where(is_i, 0)

    colunas_agg = {
        "CD: PAX Pagos": "sum", "CD: PAX Grátis": "sum",
        "CD: Bagagem Livre (kg)": "sum", "CD: Bagagem Excesso (kg)": "sum",
        "CD: Carga Paga (kg)": "sum", "CD: Carga Grátis (kg)": "sum",
        "CD: Correios (kg)": "sum",
        "CI: PAX Pagos": "sum", "CI: PAX Grátis": "sum",
        "CI: Bagagem Livre (kg)": "sum", "CI: Bagagem Excesso (kg)": "sum",
        "CI: Carga Paga (kg)": "sum", "CI: Carga Grátis (kg)": "sum",
        "CI: Correios (kg)": "sum",
    }

    agrupado = df.groupby("Chave", as_index=False).agg(colunas_agg)

    # Renomear pra nomenclatura final (CD Dest: / CI Dest:)
    rename_comb = {
        "CD: PAX Pagos":           "CD Dest: PAX Pagos",
        "CD: PAX Grátis":          "CD Dest: PAX Grátis",
        "CD: Bagagem Livre (kg)":  "CD Dest: Bags Livre (kg)",
        "CD: Bagagem Excesso (kg)":"CD Dest: Bags Excesso (kg)",
        "CD: Carga Paga (kg)":     "CD Dest: Carga Paga (kg)",
        "CD: Carga Grátis (kg)":   "CD Dest: Carga Grátis (kg)",
        "CD: Correios (kg)":       "CD Dest: Correios (kg)",
        "CI: PAX Pagos":           "CI Dest: PAX Pagos",
        "CI: PAX Grátis":          "CI Dest: PAX Grátis",
        "CI: Bagagem Livre (kg)":  "CI Dest: Bags Livre (kg)",
        "CI: Bagagem Excesso (kg)":"CI Dest: Bags Excesso (kg)",
        "CI: Carga Paga (kg)":     "CI Dest: Carga Paga (kg)",
        "CI: Carga Grátis (kg)":   "CI Dest: Carga Grátis (kg)",
        "CI: Correios (kg)":       "CI Dest: Correios (kg)",
    }
    agrupado = agrupado.rename(columns=rename_comb)

    return agrupado


def carregar_aircrafts(caminho):
    """
    Lê a dimensão Aircrafts do Excel cru e aplica o mesmo rename
    que o M faz no Dataflow. Retorna só as 4 colunas do merge,
    deduplicadas por Aircraft (como Table.Distinct no M).
    """
    df = pd.read_excel(caminho, dtype=str)
    df.columns = df.columns.str.strip()

    # Mapeamento do Excel cru → nomes usados no merge
    rename_acft = {
        "Name":   "Aircraft",
        "Group":  "Acft Group",
        "MTOWF":  "Mtow",
        "GROUPF": "Acft Fra Group",
    }
    for col_raw, col_final in rename_acft.items():
        if col_raw not in df.columns:
            print(f"  [AVISO] Coluna '{col_raw}' não encontrada em Aircraft.xlsx")

    df = df.rename(columns=rename_acft)

    colunas_acft = ["Aircraft", "Acft Group", "Mtow", "Acft Fra Group"]
    colunas_presentes = [c for c in colunas_acft if c in df.columns]
    df = df[colunas_presentes]

    # Remover duplicatas pela chave (mesmo que Table.Distinct no M)
    df = df.drop_duplicates(subset=["Aircraft"], keep="first")

    return df


def text_proper(valor):
    """Replica Text.Proper do Power Query — capitaliza cada palavra."""
    if pd.isna(valor) or not isinstance(valor, str) or valor == "":
        return valor
    return valor.title()


def processar_basica(caminho_bas, df_comb, df_acft):
    """
    Processa a básica: colunas calculadas, remove colunas,
    merge com Combinada e Aircrafts, renomeia, Text.Proper.
    Retorna DataFrame com as 75 colunas na ordem final.
    """
    # ── 1. Ler tudo como texto (preserva valores originais) ─────────
    df = pd.read_csv(caminho_bas, sep=";", encoding="cp1252", dtype=str)
    df.columns = df.columns.str.strip()

    # ── 2. Converter colunas numéricas (mesmo set que o M) ──────────
    for c in COLUNAS_INT_BASICA:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            # Preenche NaN com 0 e converte para inteiro nullable
            df[c] = df[c].fillna(0).astype(int)

    # ── 3. Colunas calculadas ───────────────────────────────────────
    df["Pax Total"] = df["nr_passag_pagos"] + df["nr_passag_gratis"]
    df["LF"] = df.apply(
        lambda r: round(r["Pax Total"] / r["nr_assentos_ofertados"], 4)
        if pd.notna(r["nr_assentos_ofertados"]) and r["nr_assentos_ofertados"] > 0
        else None,
        axis=1,
    )
    df["Cargo Total"] = (
        df["kg_bagagem_livre"] + df["kg_bagagem_excesso"] +
        df["kg_carga_paga"] + df["kg_carga_gratis"] + df["kg_correio"]
    )

    # ── 4. Chave (mesma lógica do M, campos ainda como texto) ───────
    df["Chave"] = (
        df["sg_empresa_icao"] + "-" +
        df["nr_voo"] + "-" +
        df["dt_referencia"] + "-" +
        df["sg_icao_origem"] + "-" +
        df["sg_icao_destino"]
    )

    # ── 5. Tipo e KeyTkt ────────────────────────────────────────────
    df["Tipo"] = "DEP"
    df["KeyTkt"] = (
        df["nr_ano_referencia"] + " - " +
        df["nr_ano_mes_partida_real"].str[-2:] + " - " +
        df["sg_empresa_icao"] + " - " +
        df["sg_icao_origem"] + " - " +
        df["sg_icao_destino"]
    )

    # ── 6. Remover colunas de calendário/IDs ────────────────────────
    colunas_presentes = [c for c in COLUNAS_REMOVER if c in df.columns]
    df = df.drop(columns=colunas_presentes)

    # ── 7. Substituir null por 0 em Pax Total e Cargo Total ─────────
    df["Pax Total"] = df["Pax Total"].fillna(0).astype(int)
    df["Cargo Total"] = df["Cargo Total"].fillna(0).astype(int)

    # ── 8. Group (classificação Pax/Cargo/Others) ───────────────────
    def classificar_group(row):
        tl = row.get("ds_tipo_linha", "")
        if tl in ("DOMÉSTICA CARGUEIRA", "INTERNACIONAL CARGUEIRA"):
            return "Cargo"
        if tl in ("DOMÉSTICA MISTA", "INTERNACIONAL MISTA"):
            return "Pax"
        if row["Pax Total"] > 0:
            return "Pax"
        if row["Cargo Total"] > 0:
            return "Cargo"
        if row["nr_assentos_ofertados"] > 0:
            return "Pax"
        return "Others"

    df["Group"] = df.apply(classificar_group, axis=1)

    # ── 9. Merge com Combinada (left outer join pela Chave) ─────────
    df = df.merge(df_comb, on="Chave", how="left")
    # NaN nas colunas CD/CI fica como está — o M não preenche com 0

    # ── 10. Renomear colunas ────────────────────────────────────────
    df = df.rename(columns=RENAME_MAP)

    # ── 11. Text.Proper nas colunas de texto ────────────────────────
    for c in COLUNAS_PROPER:
        if c in df.columns:
            df[c] = df[c].apply(text_proper)

    # ── 12. Merge com Aircrafts (left outer join por Aircraft) ──────
    if df_acft is not None and "Aircraft" in df.columns and "Aircraft" in df_acft.columns:
        df = df.merge(df_acft, on="Aircraft", how="left")
    else:
        # Se não tem Aircrafts, adiciona colunas vazias
        for c in ["Acft Group", "Mtow", "Acft Fra Group"]:
            if c not in df.columns:
                df[c] = None

    # ── 13. Colunas derivadas DEP ───────────────────────────────────
    df["Voo"] = df["Voo"].astype(str)
    df["Fln Icao"] = df["Airline Icao"] + df["Voo"]
    df["Fln"] = df["Airline"] + df["Voo"]
    df["Base"] = "Anac"

    # ── 14. Ordenar colunas na ordem final ──────────────────────────
    # Verificar se todas as colunas esperadas existem
    faltantes = [c for c in COLUNAS_SAIDA if c not in df.columns]
    if faltantes:
        print(f"  [AVISO] Colunas faltantes na saída: {faltantes}")
        for c in faltantes:
            df[c] = None

    df = df[COLUNAS_SAIDA]

    return df


# ════════════════════════════════════════════════════════════════════
# Orquestrador
# ════════════════════════════════════════════════════════════════════

def processar_mes(ano, mes, pasta_brutos=None, aircrafts_path=None, pasta_saida=None):
    """Processa um mês completo e grava o CSV.

    Modo por-pasta: localiza basica/combinada dentro de pasta_brutos pelo
    ano/mes. Usado no fluxo local (.bat), onde os arquivos estao todos
    numa pasta do OneDrive.
    """
    pasta_brutos = pasta_brutos or PASTA_BRUTOS
    aircrafts_path = aircrafts_path or AIRCRAFTS_PATH
    pasta_saida = pasta_saida or PASTA_SAIDA

    caminho_bas = encontrar_arquivo(pasta_brutos, "basica", ano, mes)
    caminho_comb = encontrar_arquivo(pasta_brutos, "combinada", ano, mes)

    periodo = f"{ano}-{mes:02d}"
    if not caminho_bas:
        print(f"  [ERRO] Arquivo basica {periodo} não encontrado em {pasta_brutos}")
        return None
    if not caminho_comb:
        print(f"  [ERRO] Arquivo combinada {periodo} não encontrado em {pasta_brutos}")
        return None

    return processar_par(caminho_bas, caminho_comb, aircrafts_path,
                         pasta_saida, ano, mes)


def processar_par(caminho_bas, caminho_comb, aircrafts_path, pasta_saida,
                  ano=None, mes=None):
    """Processa um par basica+combinada JA LOCALIZADO e grava o CSV.

    Este e o ponto de entrada usado pelo robo do GitHub: ele acabou de
    extrair os dois arquivos e sabe exatamente quais sao. Evita a busca
    por pasta. Devolve o Path (str) do CSV gerado, ou None em erro.

    ano/mes: se nao vierem, sao deduzidos do nome do arquivo basica
    (basicaYYYY-MM.txt ou basicaYYYYMM.txt).
    """
    caminho_bas = str(caminho_bas)
    caminho_comb = str(caminho_comb)

    if ano is None or mes is None:
        ano, mes = _periodo_do_nome(caminho_bas)
        if ano is None:
            print(f"  [ERRO] nao consegui deduzir periodo de {caminho_bas}")
            return None

    periodo = f"{ano}-{mes:02d}"
    print(f"\n{'='*60}")
    print(f"  Processando Movimentação: {periodo}")
    print(f"{'='*60}")
    t0 = time.time()

    print(f"  Básica:    {os.path.basename(caminho_bas)}")
    print(f"  Combinada: {os.path.basename(caminho_comb)}")

    # Carregar Aircrafts
    df_acft = None
    if aircrafts_path and os.path.isfile(aircrafts_path):
        print(f"  Aircrafts: {os.path.basename(aircrafts_path)}")
        df_acft = carregar_aircrafts(aircrafts_path)
        print(f"             {len(df_acft)} aeronaves carregadas")
    else:
        print(f"  [AVISO] Aircrafts não encontrado: {aircrafts_path}")
        print(f"          Colunas Acft Group / Mtow / Acft Fra Group ficarão vazias.")

    # Processar Combinada
    print(f"\n  Processando combinada...", end=" ")
    df_comb = processar_combinada(caminho_comb)
    print(f"{len(df_comb)} chaves agrupadas")

    # Processar Básica (inclui merge com Comb e Aircrafts)
    print(f"  Processando básica + merges...", end=" ")
    df = processar_basica(caminho_bas, df_comb, df_acft)
    print(f"{len(df)} linhas")

    # Formatar LF: tirar .0 desnecessário (ex: 1.0 → 1, 0.7118 fica)
    def formatar_lf(v):
        if pd.isna(v):
            return v
        if v == int(v):
            return int(v)
        return v

    df["LF"] = df["LF"].apply(formatar_lf)

    # Gravar CSV
    os.makedirs(pasta_saida, exist_ok=True)
    nome_csv = f"anac_{periodo}.csv"
    caminho_csv = os.path.join(pasta_saida, nome_csv)
    df.to_csv(caminho_csv, index=False, sep=";", encoding="utf-8-sig")

    tamanho_mb = os.path.getsize(caminho_csv) / (1024 * 1024)
    elapsed = time.time() - t0
    print(f"\n  Gravado: {caminho_csv}")
    print(f"  {len(df)} linhas x {len(df.columns)} colunas  |  "
          f"{tamanho_mb:.1f} MB  |  {elapsed:.1f}s")
    print(f"{'='*60}")

    return caminho_csv


def _periodo_do_nome(caminho):
    """Extrai (ano, mes) de um nome tipo basica2026-01.txt ou basica202601.txt."""
    import re
    nome = os.path.basename(caminho)
    m = re.search(r"(\d{4})-?(\d{2})", nome)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Processador mensal ANAC")
    parser.add_argument("periodo", help="Ano-mês no formato YYYY-MM (ex: 2026-01)")
    parser.add_argument("--brutos", default=PASTA_BRUTOS, help="Pasta dos arquivos brutos")
    parser.add_argument("--aircrafts", default=AIRCRAFTS_PATH, help="Caminho do Aircraft.xlsx")
    parser.add_argument("--saida", default=PASTA_SAIDA, help="Pasta de saída dos CSVs")
    args = parser.parse_args()

    try:
        ano, mes = args.periodo.split("-")
        ano = int(ano)
        mes = int(mes)
    except ValueError:
        print(f"[ERRO] Formato inválido: '{args.periodo}'. Use YYYY-MM (ex: 2026-01)")
        sys.exit(1)

    resultado = processar_mes(ano, mes, args.brutos, args.aircrafts, args.saida)
    if resultado is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
