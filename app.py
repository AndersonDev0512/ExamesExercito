"""Painel de acompanhamento dos exames da inspeção de saúde militar.

Os dados ficam em data.json. Este arquivo contém a interface e as funções
reutilizáveis de formatação, cálculo financeiro, prazos e validação.
"""

import copy
import html
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Exames Exército",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"

# Campo Grande/MS: UTC-4, sem horário de verão. O servidor do Streamlit Cloud roda em UTC.
FUSO_MS = timezone(timedelta(hours=-4))

STATUS_LIST = [
    "Não iniciado",
    "Em cotação",
    "Aguardando resposta",
    "Quase fechado",
    "Escolhido",
    "Fechado",
    "Agendado",
    "Realizado",
    "Resultado recebido",
    "Descartado",
    "SUS",
    "Não exigido",
]

# (fundo, texto)
VERDE = ("#dcfce7", "#166534")
AMARELO = ("#fef3c7", "#92400e")
VERMELHO = ("#fee2e2", "#991b1b")
AZUL = ("#dbeafe", "#1e40af")
CINZA = ("#e5e7eb", "#374151")
ROXO = ("#ede9fe", "#5b21b6")

STATUS_CORES = {
    "Agendado": VERDE,
    "Realizado": VERDE,
    "Resultado recebido": VERDE,
    "Escolhido": ("#ccfbf1", "#115e59"),
    "Fechado": ("#d1fae5", "#065f46"),
    "Aguardando resposta": AMARELO,
    "Quase fechado": AMARELO,
    "Não iniciado": VERMELHO,
    "SUS": AZUL,
    "Descartado": CINZA,
    "Não exigido": CINZA,
    "Em cotação": ROXO,
}

RISCO_CORES = {
    "Crítico": ("#fecaca", "#7f1d1d"),
    "Alto": VERMELHO,
    "Atenção": AMARELO,
    "": ("#ffffff", "#64748b"),
}

# Ordem de avanço usada para resumir o status de um compromisso com vários exames.
STATUS_PROGRESSO = {
    "Não iniciado": 0,
    "Em cotação": 1,
    "Aguardando resposta": 2,
    "Quase fechado": 3,
    "Escolhido": 4,
    "Fechado": 5,
    "Agendado": 5,
    "SUS": 5,
    "Realizado": 6,
    "Resultado recebido": 7,
    "Descartado": 8,
    "Não exigido": 8,
}

STATUS_FORA_DO_TOTAL = {"SUS", "Descartado", "Não exigido"}
STATUS_IGNORADOS = {"Descartado", "Não exigido"}
STATUS_CONCLUIDOS = {"Realizado", "Resultado recebido"}
STATUS_PRE_AGENDAMENTO = {"Não iniciado", "Em cotação", "Aguardando resposta", "Quase fechado", "Escolhido"}

VALOR_TIPOS = {
    "confirmado": "Confirmado",
    "orcamento": "Orçamento",
    "estimado": "Estimado",
    "opcao": "Opção (fora do total)",
    "a_cotar": "A cotar",
    "sus": "SUS",
    "nao_exigido": "Não exigido",
}
VALOR_TIPOS_NO_TOTAL = {"confirmado", "orcamento", "estimado"}

CHAVES_OBRIGATORIAS = ("meta", "contatos", "pacotes", "agenda", "exames")

AVISO_ARMAZENAMENTO = (
    "No Streamlit Community Cloud o disco é temporário: alterações gravadas em data.json "
    "se perdem quando o app reinicia ou é reimplantado. Para guardar de forma permanente, "
    "baixe o JSON e substitua o data.json no GitHub."
)


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------

def read_data_file():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def data_to_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def save_data_file(data):
    try:
        DATA_FILE.write_text(data_to_json(data) + "\n", encoding="utf-8")
        return True, "data.json gravado."
    except OSError as exc:
        return False, f"Não foi possível gravar o data.json: {exc}"


def init_state():
    if "data" not in st.session_state:
        try:
            st.session_state.data = read_data_file()
        except (OSError, json.JSONDecodeError) as exc:
            st.error(f"Erro ao carregar data.json: {exc}")
            st.stop()
        st.session_state.dirty = False


def mark_dirty():
    st.session_state.dirty = True


def apply_and_rerun(*mensagens):
    """Marca alteração e reexecuta para que todas as abas reflitam os novos dados."""
    mark_dirty()
    st.session_state.flash = [m for m in mensagens if m]
    st.rerun()


def show_flash():
    for msg in st.session_state.pop("flash", []):
        st.success(msg)


def index_by_id(items):
    return {item["id"]: item for item in items if "id" in item}


def today_ms():
    """Data de hoje em Campo Grande. Aceita ?hoje=dd/mm/aaaa na URL para simulação."""
    override = parse_date(st.query_params.get("hoje"))
    return override or datetime.now(FUSO_MS).date()


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def brl(value, vazio="A cotar"):
    if value is None:
        return vazio
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value):
    try:
        return datetime.strptime(str(value).strip(), "%H:%M").time()
    except ValueError:
        return None


def fmt_date(value, vazio="—"):
    d = parse_date(value)
    return d.strftime("%d/%m/%Y") if d else vazio


def fmt_hora(value):
    t = parse_time(value)
    return t.strftime("%Hh%M") if t else (value or "—")


DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def fmt_dia_semana(d):
    return f"{DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m/%Y')}"


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def only_digits(value):
    return re.sub(r"\D", "", value or "")


def whatsapp_url(phone):
    digits = only_digits(phone)
    if len(digits) not in (10, 11):
        return None
    return f"https://wa.me/55{digits}"


def contact_label(contato):
    if not contato:
        return "A definir"
    final = contato.get("final")
    return f'{contato["nome"]} ({final})' if final else f'{contato["nome"]} (sem número)'


def esc(value):
    return html.escape(str(value)) if value not in (None, "") else ""


def badge_html(text, cores=None):
    bg, fg = cores or STATUS_CORES.get(text, CINZA)
    return f'<span class="badge" style="background:{bg};color:{fg}">{esc(text)}</span>'


def style_cells(df, colunas):
    """Aplica as cores de status e risco às colunas indicadas de um DataFrame."""

    def cor(valor):
        bg, fg = STATUS_CORES.get(valor) or RISCO_CORES.get(valor) or ("", "")
        return f"background-color:{bg};color:{fg};font-weight:600" if bg else ""

    return df.style.map(cor, subset=[c for c in colunas if c in df.columns])


def search_df(df, query):
    """Filtra linhas que contenham o texto em qualquer coluna, ignorando acentos e maiúsculas."""
    if not query:
        return df
    termos = normalize(query).split()
    texto = df.astype(str).apply(lambda col: col.map(normalize)).agg(" ".join, axis=1)
    mask = pd.Series(True, index=df.index)
    for termo in termos:
        mask &= texto.str.contains(termo, regex=False)
    return df[mask]


# ---------------------------------------------------------------------------
# Regras de negócio
# ---------------------------------------------------------------------------

def agenda_by_exam(data):
    """Primeiro compromisso de cada exame."""
    mapa = {}
    for ag in data["agenda"]:
        for eid in ag.get("exames", []):
            atual = mapa.get(eid)
            if atual is None or (parse_date(ag["data"]) or date.max) < (parse_date(atual["data"]) or date.max):
                mapa[eid] = ag
    return mapa


def holidays(meta):
    return {d for d in map(parse_date, meta.get("feriados", [])) if d}


def add_business_days(inicio, dias, feriados):
    d, contados = inicio, 0
    while contados < dias:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in feriados:
            contados += 1
    return d


def latest_start(limite, dias, feriados):
    """Último dia útil em que o exame pode ser feito para o resultado sair até o limite."""
    d = limite
    while d.weekday() >= 5 or d in feriados or add_business_days(d, dias, feriados) > limite:
        d -= timedelta(days=1)
    return d


def is_walk_in(exame, data_agendada):
    """Exame por ordem de chegada ainda não realizado e sem compromisso na agenda."""
    return bool(
        exame.get("ordem_chegada")
        and not data_agendada
        and not exame.get("data_realizacao")
        and exame.get("status") not in STATUS_CONCLUIDOS | STATUS_IGNORADOS
    )


def expected_result(exame, data_agendada, meta, hoje=None):
    """Previsão do resultado: (data, fonte, fazer_até).

    fonte é "informado" (prazo_resultado no JSON), "média" (prazo_dias_uteis
    contado da realização ou do agendamento) ou "se feito hoje" (exame por
    ordem de chegada, contado a partir de hoje). fazer_até é a data-limite
    para realizar o exame quando ele ainda não tem data.
    """
    informado = parse_date(exame.get("prazo_resultado"))
    if informado:
        return informado, "informado", None
    dias = exame.get("prazo_dias_uteis")
    if dias is None:
        return None, None, None
    feriados = holidays(meta)
    base = parse_date(exame.get("data_realizacao")) or data_agendada
    if base:
        return add_business_days(base, dias, feriados), "média", None
    prazo = parse_date(meta.get("prazo_resultados"))
    fazer_ate = latest_start(prazo, dias, feriados) if prazo else None
    if hoje and is_walk_in(exame, data_agendada):
        return add_business_days(hoje, dias, feriados), "se feito hoje", fazer_ate
    return None, None, fazer_ate


def earliest_result(exame, data_agendada, meta, hoje=None):
    """Data mais cedo do resultado, quando o prazo é uma faixa (prazo_dias_uteis_min)."""
    dias_min = exame.get("prazo_dias_uteis_min")
    if dias_min is None or exame.get("prazo_resultado"):
        return None
    base = parse_date(exame.get("data_realizacao")) or data_agendada
    if not base and hoje and is_walk_in(exame, data_agendada):
        base = hoje
    return add_business_days(base, dias_min, holidays(meta)) if base else None


def validity_start(exame, meta):
    """Data mínima do exame: data da inspeção menos a validade (edital: 30 dias; Beta HCG: 15)."""
    inspecao = parse_date(meta.get("apresentacao"))
    dias = exame.get("validade_dias", meta.get("validade_dias_padrao"))
    if not inspecao or dias is None:
        return None
    return inspecao - timedelta(days=int(dias))


def assess_risk(exame, data_agendada, prazo, hoje, dias_alerta, prazo_resultado=None, fazer_ate=None, meta=None,
                resultado_minimo=None):
    """Retorna (nível, motivo). Níveis: Crítico, Alto, Atenção ou vazio."""
    status = exame.get("status")
    if status in STATUS_IGNORADOS or status == "Resultado recebido":
        return "", ""
    if prazo is None:
        return "Atenção", "Prazo interno não definido"

    dias = (prazo - hoje).days

    validade = validity_start(exame, meta) if meta else None
    data_exame = parse_date(exame.get("data_realizacao")) or data_agendada
    if validade and data_exame and data_exame < validade:
        return "Crítico", f"Fora da validade do edital: precisa ser datado a partir de {fmt_date(validade)}"

    if is_walk_in(exame, data_agendada):
        se_hoje = f"; se feito hoje, resultado em {fmt_date(prazo_resultado)}" if prazo_resultado else ""
        if fazer_ate and hoje > fazer_ate:
            return "Crítico", f"Ordem de chegada: precisava ser feito até {fmt_date(fazer_ate)}{se_hoje}"
        if fazer_ate:
            nivel = "Alto" if (fazer_ate - hoje).days <= dias_alerta else "Atenção"
            return nivel, f"Ordem de chegada: fazer até {fmt_date(fazer_ate)}{se_hoje}"
        nivel = "Alto" if dias <= dias_alerta else "Atenção"
        return nivel, f"Ordem de chegada: prazo do resultado não informado; faltam {dias} dias para {fmt_date(prazo)}"

    if prazo_resultado and prazo_resultado > prazo:
        if resultado_minimo and resultado_minimo <= prazo:
            return "Alto", (
                f"Resultado entre {fmt_date(resultado_minimo)} e {fmt_date(prazo_resultado)}; "
                f"no pior caso, após {fmt_date(prazo)}"
            )
        return "Crítico", f"Resultado previsto até {fmt_date(prazo_resultado)}, após {fmt_date(prazo)}"
    if data_agendada and data_agendada > prazo:
        return "Crítico", f"Agendado para {fmt_date(data_agendada)}, após {fmt_date(prazo)}"
    if dias < 0:
        return "Crítico", f"Prazo de {fmt_date(prazo)} vencido sem resultado"
    if status in STATUS_PRE_AGENDAMENTO and not data_agendada and fazer_ate:
        if hoje > fazer_ate:
            return "Crítico", f"Precisava ser feito até {fmt_date(fazer_ate)} para sair até {fmt_date(prazo)}"
        if (fazer_ate - hoje).days <= dias_alerta:
            return "Alto", f"Fazer até {fmt_date(fazer_ate)} ({exame['prazo_dias_uteis']} dias úteis para o resultado)"
        return "Atenção", f"Fazer até {fmt_date(fazer_ate)}"
    if status in STATUS_PRE_AGENDAMENTO and not data_agendada:
        if dias <= dias_alerta:
            return "Alto", f"Ainda não agendado; faltam {dias} dias para {fmt_date(prazo)}"
        return "Atenção", "Ainda não agendado"
    if prazo_resultado and prazo_resultado < hoje:
        return "Alto", f"Resultado deveria ter saído em {fmt_date(prazo_resultado)}"
    if not prazo_resultado:
        return "Atenção", "Prazo do resultado não confirmado"
    return "", ""


def exam_value_label(exame, pacotes):
    status = exame.get("status")
    tipo = exame.get("valor_tipo")
    if status in STATUS_IGNORADOS or tipo == "nao_exigido":
        return "Fora do total"
    if status == "SUS" or tipo == "sus":
        return "SUS (sem custo)"
    valor = brl(exame.get("valor"))
    if exame.get("pacote"):
        pacote = pacotes.get(exame["pacote"], {})
        return f"{valor} (no pacote {pacote.get('nome', exame['pacote'])})"
    return valor


def provider_label(item, contatos):
    contato = contatos.get(item.get("contato"))
    partes = [contact_label(contato)] if contato else []
    profissional = (item.get("profissional") or "").strip()
    if profissional:
        partes.append(profissional)
    return " — ".join(partes) if partes else "A definir"


def build_exam_rows(data, hoje):
    meta = data["meta"]
    prazo = parse_date(meta.get("prazo_resultados"))
    dias_alerta = int(meta.get("dias_alerta", 14))
    contatos = index_by_id(data["contatos"])
    pacotes = index_by_id(data["pacotes"])
    agenda = agenda_by_exam(data)

    rows = []
    for ex in sorted(data["exames"], key=lambda e: e.get("ordem", 0)):
        ag = agenda.get(ex["id"])
        data_ag = parse_date(ag["data"]) if ag else None
        previsto, fonte, fazer_ate = expected_result(ex, data_ag, meta, hoje)
        minimo = earliest_result(ex, data_ag, meta, hoje)
        nivel, motivo = assess_risk(ex, data_ag, prazo, hoje, dias_alerta, previsto, fazer_ate, meta, minimo)
        rows.append({
            "id": ex["id"],
            "Ordem": ex.get("ordem", 0),
            "Grupo": ex.get("grupo", ""),
            "Exame": ex.get("nome", ""),
            "Exigência do edital": ex.get("exigencia", ""),
            "Clínica / profissional": provider_label(ex, contatos),
            "Valor": exam_value_label(ex, pacotes),
            "Tipo de valor": VALOR_TIPOS.get(ex.get("valor_tipo"), ex.get("valor_tipo") or ""),
            "Data agendada": (
                f'{fmt_date(data_ag)} {fmt_hora(ag["horario"])}' if ag
                else f"{fmt_date(hoje)} — ordem de chegada" if is_walk_in(ex, data_ag)
                else "—"
            ),
            "Válido a partir de": fmt_date(validity_start(ex, meta), ""),
            "Prazo do resultado": "Não se aplica" if ex.get("status") in STATUS_IGNORADOS else result_label(previsto, fonte, fazer_ate, minimo),
            "Status": ex.get("status", ""),
            "Risco": nivel,
            "Motivo do risco": motivo,
            "Pago": "Sim" if is_paid(ex, pacotes) else "Não",
            "Pendências": ex.get("pendencias", ""),
            "Observações": ex.get("observacoes", ""),
            "Protocolo": ex.get("protocolo", ""),
            "Código de acompanhamento": ex.get("codigo_acompanhamento", ""),
            "Realizado em": fmt_date(ex.get("data_realizacao"), ""),
            "Resultado em": fmt_date(ex.get("data_resultado"), ""),
            "_valor": ex.get("valor"),
            "_data": data_ag,
        })
    return rows


def result_label(previsto, fonte, fazer_ate, minimo=None):
    if previsto:
        sufixo = {"média": " (média)", "se feito hoje": " (média, se feito hoje)"}.get(fonte, "")
        if minimo and minimo < previsto:
            return f"{fmt_date(minimo)} a {fmt_date(previsto)}{sufixo}"
        return fmt_date(previsto) + sufixo
    if fazer_ate:
        return f"Fazer até {fmt_date(fazer_ate)}"
    return "A confirmar"


def is_paid(exame, pacotes):
    if exame.get("pacote"):
        return bool(pacotes.get(exame["pacote"], {}).get("pago"))
    return bool(exame.get("pago"))


def agenda_status(exames):
    if not exames:
        return "Agendado"
    return min((e.get("status", "Agendado") for e in exames), key=lambda s: STATUS_PROGRESSO.get(s, 5))


def walk_in_items(data, hoje, contatos):
    """Um compromisso no dia de hoje por clínica, reunindo os exames por ordem de chegada."""
    meta = data["meta"]
    prazo = parse_date(meta.get("prazo_resultados"))
    agendados = agenda_by_exam(data)
    por_contato = {}
    for ex in sorted(data["exames"], key=lambda e: e.get("ordem", 0)):
        ag = agendados.get(ex["id"])
        if is_walk_in(ex, parse_date(ag["data"]) if ag else None):
            por_contato.setdefault(ex.get("contato"), []).append(ex)

    itens = []
    for cid, exames in por_contato.items():
        contato = contatos.get(cid) or {}
        grupos, previstos = {}, []
        for ex in exames:
            previsto, _, fazer_ate = expected_result(ex, None, meta, hoje)
            grupos.setdefault(ex.get("grupo", ""), []).append((previsto, fazer_ate))
            if previsto:
                previstos.append(previsto)
        orientacoes = []
        for grupo, lista in grupos.items():
            previsto, fazer_ate = lista[0]
            if fazer_ate:
                detalhe = f"fazer até {fmt_date(fazer_ate)}; se feito hoje, resultado em {fmt_date(previsto)} (média)"
            else:
                detalhe = "prazo do resultado não informado"
            orientacoes.append(f"{grupo} ({len(lista)}): {detalhe}")
        ultimo = max(previstos) if previstos else None
        itens.append({
            "id": f"oc_{cid}",
            "data": hoje,
            "exame_ids": [e["id"] for e in exames],
            "_resultado_risco": False,
            "dt": datetime.combine(hoje, time(0, 0)),
            "Data": fmt_date(hoje),
            "Horário": "Ordem de chegada",
            "Tipo de exame": "Ordem de chegada: " + ", ".join(grupos),
            "Clínica": contato.get("nome", "A definir"),
            "Clínica / profissional": contact_label(contato) if contato else "A definir",
            "Final do contato": contato.get("final") or "—",
            "Endereço": contato.get("endereco") or "A confirmar",
            "Valor": "No pacote / orçamento",
            "Status": agenda_status(exames),
            "Previsto": True,
            "Resultado previsto": result_label(ultimo, "se feito hoje", None) if ultimo else "A confirmar",
            "_resultado_atrasado": bool(ultimo and prazo and ultimo > prazo),
            "Orientações": orientacoes,
            "Documentos": contato.get("documentos", []),
            "Exames": [e.get("nome", "") for e in exames],
        })
    return itens


def next_service_days(contato, hoje, ate, feriados):
    """Próximos dias de atendimento do contato (campo dias_semana: 0=segunda … 6=domingo)."""
    dias_semana = contato.get("dias_semana")
    if not dias_semana or not ate:
        return []
    dias, d = [], hoje
    while d <= ate:
        if d.weekday() in dias_semana and d not in feriados:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def pending_to_schedule(data, hoje):
    """Exames que ainda precisam ser marcados: sem compromisso na agenda e fora da ordem de chegada."""
    meta = data["meta"]
    prazo = parse_date(meta.get("prazo_resultados"))
    contatos = index_by_id(data["contatos"])
    agendados = agenda_by_exam(data)
    pendentes = []
    for ex in sorted(data["exames"], key=lambda e: e.get("ordem", 0)):
        ag = agendados.get(ex["id"])
        data_ag = parse_date(ag["data"]) if ag else None
        if data_ag or ex.get("status") not in STATUS_PRE_AGENDAMENTO or is_walk_in(ex, data_ag):
            continue
        _, _, fazer_ate = expected_result(ex, None, meta, hoje)
        opcoes_ids = ex.get("opcoes_contato") or ([ex["contato"]] if ex.get("contato") else [])
        opcoes = [contatos[c] for c in opcoes_ids if c in contatos]
        pendentes.append({
            "exame": ex,
            "marcar_ate": fazer_ate or prazo,
            "opcoes": opcoes,
        })
    return pendentes


def render_pending(data, hoje):
    pendentes = pending_to_schedule(data, hoje)
    if not pendentes:
        st.success("Nenhum exame pendente de marcar.")
        return
    st.markdown(f"#### 📌 Pendentes de marcar ({len(pendentes)})")
    pacotes = index_by_id(data["pacotes"])
    for item in pendentes:
        ex = item["exame"]
        with st.container(border=True):
            dias = (item["marcar_ate"] - hoje).days if item["marcar_ate"] else None
            cor = "#b91c1c" if dias is not None and dias <= 3 else "#92400e"
            st.markdown(
                f'<span class="tt" style="font-weight:700">{esc(ex.get("nome"))}</span> '
                f'{badge_html(ex.get("status"))} {badge_html("A marcar", VERMELHO)}'
                f'<div class="mt" style="color:{cor};font-weight:700;margin-top:4px">'
                f'⏰ Marcar até {fmt_date(item["marcar_ate"])}'
                + (f" (faltam {dias} dias)" if dias is not None and dias >= 0 else " (prazo vencido)")
                + "</div>"
                f'<div class="mt" style="color:#475569;font-size:.86rem">💰 {esc(exam_value_label(ex, pacotes))}</div>'
                + (f'<div class="mt" style="color:#475569;font-size:.86rem">📝 {esc(ex.get("pendencias"))}</div>' if ex.get("pendencias") else ""),
                unsafe_allow_html=True,
            )
            if item["opcoes"]:
                st.caption("Opções para marcar:")
                cols = st.columns(2)
                for n, c in enumerate(item["opcoes"]):
                    with cols[n % 2]:
                        texto = f'**{contact_label(c)}** · {brl(c.get("valor"), "sem valor")} · {c.get("situacao", "")}'
                        proximos = next_service_days(c, hoje, item["marcar_ate"], holidays(data["meta"]))
                        if c.get("horario_atendimento"):
                            texto += f'  \n🕑 {c["horario_atendimento"]}'
                        if proximos:
                            texto += "  \n📅 Próximos dias: " + ", ".join(fmt_dia_semana(d) for d in proximos)
                        st.markdown(texto)
                        link = whatsapp_url(c.get("telefone"))
                        if link:
                            st.link_button("💬 WhatsApp", link, width="stretch")
                        else:
                            st.caption("Número completo não cadastrado.")


def build_agenda(data, hoje):
    meta = data["meta"]
    prazo = parse_date(meta.get("prazo_resultados"))
    contatos = index_by_id(data["contatos"])
    exames = index_by_id(data["exames"])
    itens = []
    for ag in data["agenda"]:
        d = parse_date(ag.get("data"))
        t = parse_time(ag.get("horario")) or time(0, 0)
        vinculados = [exames[i] for i in ag.get("exames", []) if i in exames]
        contato = contatos.get(ag.get("contato"))
        valor = ag.get("valor")
        if contato and contato.get("categoria") == "SUS":
            valor_txt = "SUS (sem custo)"
        else:
            valor_txt = brl(valor)
            if any(e.get("pacote") for e in vinculados):
                valor_txt += " (no pacote)"
        previstos = []
        for e in vinculados:
            previsto, fonte, _ = expected_result(e, d, meta)
            if previsto:
                previstos.append((previsto, fonte, earliest_result(e, d, meta) or previsto))
        if previstos:
            ultimo, fonte, _ = max(previstos)
            # Todos os resultados prontos: o maior entre os mínimos de cada exame.
            minimo = max(m for _, _, m in previstos)
            resultado_txt = result_label(ultimo, fonte, None, minimo)
        else:
            ultimo = minimo = None
            resultado_txt = "A confirmar"
        itens.append({
            "id": ag["id"],
            "data": d,
            "exame_ids": [e["id"] for e in vinculados],
            "Resultado previsto": resultado_txt,
            "_resultado_atrasado": bool(minimo and prazo and minimo > prazo),
            "_resultado_risco": bool(ultimo and prazo and minimo and minimo <= prazo < ultimo),
            "dt": datetime.combine(d, t) if d else None,
            "Data": fmt_date(d),
            "Horário": fmt_hora(ag.get("horario")),
            "Tipo de exame": ag.get("tipo", ""),
            "Clínica": contato["nome"] if contato else "A definir",
            "Clínica / profissional": provider_label(ag, contatos),
            "Final do contato": (contato or {}).get("final") or "—",
            "Endereço": ag.get("endereco") or "A confirmar",
            "Valor": valor_txt,
            "Status": agenda_status(vinculados),
            "Previsto": bool(ag.get("previsto")),
            "Orientações": ag.get("orientacoes", []),
            "Documentos": ag.get("documentos", []),
            "Exames": [e.get("nome", "") for e in vinculados],
        })
    itens.extend(walk_in_items(data, hoje, contatos))
    itens.sort(key=lambda x: x["dt"] or datetime.max)
    return itens


def financial_lines(data):
    """Linhas que compõem o financeiro, sem dupla contagem.

    Pacotes entram uma única vez pelo valor consolidado; exames dentro de pacote
    não são somados individualmente. SUS, descartados e não exigidos ficam fora.
    """
    pacotes = data["pacotes"]
    exames_por_pacote = {}
    for ex in data["exames"]:
        if ex.get("pacote"):
            exames_por_pacote.setdefault(ex["pacote"], []).append(ex)

    linhas = []
    for pac in pacotes:
        itens = exames_por_pacote.get(pac["id"], [])
        ativos = [e for e in itens if e.get("status") not in STATUS_IGNORADOS]
        tipo = pac.get("valor_tipo", "orcamento")
        if itens and not ativos:
            tipo = "nao_exigido"
        linhas.append({
            "Descrição": pac["nome"],
            "Origem": "Pacote",
            "contato": pac.get("contato"),
            "Grupos": ", ".join(sorted({e.get("grupo", "") for e in ativos})),
            "Itens": ", ".join(e.get("nome", "") for e in ativos),
            "valor": pac.get("valor"),
            "tipo": tipo,
            "pago": bool(pac.get("pago")),
        })

    for ex in data["exames"]:
        if ex.get("pacote"):
            continue
        tipo = ex.get("valor_tipo", "a_cotar")
        if ex.get("status") in STATUS_FORA_DO_TOTAL:
            tipo = "sus" if ex.get("status") == "SUS" else "nao_exigido"
        elif ex.get("valor") is None:
            tipo = "a_cotar"
        linhas.append({
            "Descrição": ex.get("nome", ""),
            "Origem": "Exame",
            "contato": ex.get("contato"),
            "Grupos": ex.get("grupo", ""),
            "Itens": "",
            "valor": ex.get("valor"),
            "tipo": tipo,
            "pago": bool(ex.get("pago")),
        })
    return linhas


def financial_summary(linhas):
    def soma(filtro):
        return round(sum(l["valor"] or 0 for l in linhas if filtro(l)), 2)

    no_total = lambda l: l["tipo"] in VALOR_TIPOS_NO_TOTAL  # noqa: E731
    resumo = {
        "confirmado": soma(lambda l: l["tipo"] == "confirmado"),
        "orcamento": soma(lambda l: l["tipo"] == "orcamento"),
        "estimado": soma(lambda l: l["tipo"] == "estimado"),
        "total": soma(no_total),
        "pago": soma(lambda l: no_total(l) and l["pago"]),
        "opcoes": soma(lambda l: l["tipo"] == "opcao"),
        "a_cotar": sum(1 for l in linhas if l["tipo"] == "a_cotar"),
    }
    resumo["nao_pago"] = round(resumo["total"] - resumo["pago"], 2)
    # Conferência interna: as partes precisam fechar com o total.
    resumo["consistente"] = abs(resumo["confirmado"] + resumo["orcamento"] + resumo["estimado"] - resumo["total"]) < 0.005
    return resumo


def totals_by_provider(data):
    """Total por clínica/laboratório, com as mesmas regras do total geral (sem dupla contagem)."""
    contatos = index_by_id(data["contatos"])
    totais = {}
    for linha in financial_lines(data):
        if linha["tipo"] in ("sus", "nao_exigido"):
            continue
        contato = contatos.get(linha["contato"])
        nome = contact_label(contato) if contato else f'{linha["Grupos"] or "Prestador"} (a definir)'
        t = totais.setdefault(nome, {
            "confirmado": 0.0, "orcamento": 0.0, "estimado": 0.0, "opcao": 0.0,
            "a_cotar": 0, "pago": 0.0, "itens": [],
        })
        valor = linha["valor"] or 0
        if linha["tipo"] in t and linha["tipo"] != "a_cotar":
            t[linha["tipo"]] += valor
        if linha["tipo"] == "a_cotar":
            t["a_cotar"] += 1
        if linha["pago"] and linha["tipo"] in VALOR_TIPOS_NO_TOTAL:
            t["pago"] += valor
        t["itens"].append(linha["Descrição"])
    for t in totais.values():
        t["total"] = t["confirmado"] + t["orcamento"] + t["estimado"]
    return dict(sorted(totais.items(), key=lambda kv: -kv[1]["total"]))


def installment(valor, parcelas, juros_mes):
    """Valor da parcela (tabela Price). Sem juros, divide igualmente."""
    if parcelas <= 1:
        return valor
    if not juros_mes:
        return valor / parcelas
    i = juros_mes / 100
    return valor * i / (1 - (1 + i) ** -parcelas)


def payment_plan(data, parcelas_por_contato, juros_mes):
    """Separa o que será pago à vista (líquido) do que será parcelado, por prestador."""
    contatos_por_nome = {contact_label(c): c for c in data["contatos"]}
    linhas = []
    for nome, t in totals_by_provider(data).items():
        a_pagar = round(t["total"] - t["pago"], 2)
        if a_pagar <= 0:
            continue
        contato = contatos_por_nome.get(nome, {})
        n = parcelas_por_contato.get(contato.get("id"), 1)
        parcela = installment(a_pagar, n, juros_mes) if n > 1 else a_pagar
        linhas.append({
            "nome": nome,
            "a_pagar": a_pagar,
            "parcelas": n,
            "parcela": parcela,
            "total_pago": parcela * n,
            "forma": contato.get("forma_pagamento", ""),
        })
    return linhas


def provider_kpis(totais):
    itens = []
    for nome, t in totais.items():
        if t["total"]:
            partes = [f"{VALOR_TIPOS[k].lower()} {brl(t[k])}" for k in ("confirmado", "orcamento", "estimado") if t[k]]
            sub = " + ".join(partes) if len(partes) > 1 else VALOR_TIPOS[next(k for k in ("confirmado", "orcamento", "estimado") if t[k])]
            cor = "green" if t["confirmado"] == t["total"] else "amber" if t["estimado"] == 0 else "gray"
            itens.append((nome, brl(t["total"]), sub, cor))
        elif t["opcao"]:
            itens.append((nome, brl(t["opcao"]), "opção, fora do total", "gray"))
        else:
            itens.append((nome, "A cotar", f'{t["a_cotar"]} item(ns) sem valor', "red"))
    return itens


def values_by_group(data):
    grupos = {}
    for ex in data["exames"]:
        if ex.get("status") in STATUS_FORA_DO_TOTAL or ex.get("valor_tipo") not in VALOR_TIPOS_NO_TOTAL:
            continue
        g = grupos.setdefault(ex.get("grupo", ""), {"valor": 0.0, "itens": 0, "a_cotar": 0})
        if ex.get("valor") is None:
            g["a_cotar"] += 1
        else:
            g["valor"] += ex["valor"]
            g["itens"] += 1
    return grupos


def comparison_summary(comparativo):
    opcoes = [o for o in comparativo.get("opcoes", []) if o.get("valor") is not None]
    if not opcoes:
        return None
    escolhida = next((o for o in opcoes if o.get("escolhida")), None)
    referencia = escolhida or min(opcoes, key=lambda o: o["valor"])
    mais_cara = max(opcoes, key=lambda o: o["valor"])
    acima = sorted((o for o in opcoes if o["valor"] > referencia["valor"]), key=lambda o: o["valor"])
    return {
        "referencia": referencia,
        "escolhida": escolhida is not None,
        "mais_cara": mais_cara,
        "economia_max": mais_cara["valor"] - referencia["valor"],
        "proxima": acima[0] if acima else None,
        "economia_proxima": (acima[0]["valor"] - referencia["valor"]) if acima else 0,
    }


def validate_data(data):
    """Retorna (erros, avisos) encontrados em data.json."""
    erros, avisos = [], []
    for chave in CHAVES_OBRIGATORIAS:
        if chave not in data:
            erros.append(f"Chave obrigatória ausente: '{chave}'.")
    if erros:
        return erros, avisos

    meta = data["meta"]
    for campo in ("prazo_resultados", "conferencia", "apresentacao"):
        if not parse_date(meta.get(campo)):
            erros.append(f"Data inválida em meta.{campo}: {meta.get(campo)!r}.")

    for feriado in meta.get("feriados", []):
        if not parse_date(feriado):
            erros.append(f"Feriado inválido em meta.feriados: {feriado!r}.")

    for colecao in ("contatos", "pacotes", "agenda", "exames"):
        ids = [i.get("id") for i in data[colecao]]
        repetidos = {i for i in ids if ids.count(i) > 1}
        if repetidos:
            erros.append(f"IDs repetidos em {colecao}: {', '.join(sorted(map(str, repetidos)))}.")
        if None in ids:
            erros.append(f"Há item sem 'id' em {colecao}.")

    contatos = index_by_id(data["contatos"])
    pacotes = index_by_id(data["pacotes"])
    exames = index_by_id(data["exames"])

    for c in data["contatos"]:
        tel, final = c.get("telefone"), c.get("final")
        if tel:
            digitos = only_digits(tel)
            if final and not digitos.endswith(final):
                erros.append(f"Contato {c['nome']}: final {final} não confere com {tel}.")
            if len(digitos) == 10:
                avisos.append(f"Contato {contact_label(c)}: telefone {tel} tem 8 dígitos após o DDD; confirme o número.")
            elif len(digitos) != 11:
                erros.append(f"Contato {contact_label(c)}: telefone {tel} inválido.")

    for ex in data["exames"]:
        nome = ex.get("nome", ex.get("id"))
        if ex.get("status") not in STATUS_LIST:
            erros.append(f"Exame {nome}: status inválido {ex.get('status')!r}.")
        if ex.get("valor_tipo") not in VALOR_TIPOS:
            erros.append(f"Exame {nome}: tipo de valor inválido {ex.get('valor_tipo')!r}.")
        valor = ex.get("valor")
        if valor is not None and (not isinstance(valor, (int, float)) or valor < 0):
            erros.append(f"Exame {nome}: valor inválido {valor!r}.")
        if valor is None and ex.get("valor_tipo") in VALOR_TIPOS_NO_TOTAL:
            avisos.append(f"Exame {nome}: tipo de valor '{ex['valor_tipo']}' sem valor informado.")
        if ex.get("contato") and ex["contato"] not in contatos:
            erros.append(f"Exame {nome}: contato '{ex['contato']}' não existe.")
        for cid in ex.get("opcoes_contato", []):
            if cid not in contatos:
                erros.append(f"Exame {nome}: opção de contato '{cid}' não existe.")
        if ex.get("pacote") and ex["pacote"] not in pacotes:
            erros.append(f"Exame {nome}: pacote '{ex['pacote']}' não existe.")
        dias_uteis = ex.get("prazo_dias_uteis")
        if dias_uteis is not None and (not isinstance(dias_uteis, int) or dias_uteis < 0):
            erros.append(f"Exame {nome}: prazo_dias_uteis inválido {dias_uteis!r}.")
        dias_min = ex.get("prazo_dias_uteis_min")
        if dias_min is not None and (not isinstance(dias_min, int) or dias_min < 0
                                     or (isinstance(dias_uteis, int) and dias_min > dias_uteis)):
            erros.append(f"Exame {nome}: prazo_dias_uteis_min inválido {dias_min!r}.")
        for campo in ("prazo_resultado", "data_realizacao", "data_resultado"):
            if ex.get(campo) and not parse_date(ex[campo]):
                erros.append(f"Exame {nome}: data inválida em {campo}: {ex[campo]!r}.")
        composicao = ex.get("composicao")
        if composicao and valor is not None and abs(sum(i["valor"] for i in composicao) - valor) > 0.005:
            erros.append(f"Exame {nome}: composição soma {brl(sum(i['valor'] for i in composicao))}, mas o valor é {brl(valor)}.")

    for pac in data["pacotes"]:
        itens = [e for e in data["exames"] if e.get("pacote") == pac["id"]]
        if not itens:
            avisos.append(f"Pacote {pac['nome']} não tem exames vinculados.")
            continue
        soma = sum(e.get("valor") or 0 for e in itens)
        if pac.get("valor") is not None and abs(soma - pac["valor"]) > 0.005:
            avisos.append(
                f"Pacote {pac['nome']}: itens somam {brl(soma)}, mas o pacote vale {brl(pac['valor'])}. "
                "O total usa o valor do pacote."
            )

    prazo = parse_date(meta.get("prazo_resultados"))
    for ag in data["agenda"]:
        d = parse_date(ag.get("data"))
        if not d:
            erros.append(f"Agenda {ag.get('tipo')}: data inválida {ag.get('data')!r}.")
        elif prazo and d > prazo:
            avisos.append(f"Agenda {ag.get('tipo')}: compromisso em {fmt_date(d)}, após o prazo interno.")
        if not parse_time(ag.get("horario")):
            erros.append(f"Agenda {ag.get('tipo')}: horário inválido {ag.get('horario')!r} (use HH:MM).")
        if ag.get("contato") and ag["contato"] not in contatos:
            erros.append(f"Agenda {ag.get('tipo')}: contato '{ag['contato']}' não existe.")
        for eid in ag.get("exames", []):
            if eid not in exames:
                erros.append(f"Agenda {ag.get('tipo')}: exame '{eid}' não existe.")

    if not financial_summary(financial_lines(data))["consistente"]:
        erros.append("Os subtotais financeiros não fecham com o total geral.")
    return erros, avisos


# ---------------------------------------------------------------------------
# Componentes de interface
# ---------------------------------------------------------------------------

CSS = """
<style>
.stApp {background:#ffffff;}
.block-container {padding-top:1.2rem; padding-bottom:3rem; max-width:1300px;}
h1 {font-size:1.7rem !important;}
.badge {display:inline-block;padding:3px 10px;border-radius:999px;font-size:.78rem;font-weight:700;white-space:nowrap;}
.kpis {display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:.4rem 0 1rem;}
.kpi {background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px 14px;box-shadow:0 1px 4px rgba(15,23,42,.05);}
.kpi .lbl {font-size:.78rem;color:#64748b;}
.kpi .val {font-size:1.35rem;font-weight:700;color:#0f172a;line-height:1.3;}
.kpi .sub {font-size:.75rem;color:#64748b;}
.kpi.red {border-left:4px solid #dc2626;} .kpi.green {border-left:4px solid #16a34a;}
.kpi.blue {border-left:4px solid #2563eb;} .kpi.amber {border-left:4px solid #d97706;}
.kpi.gray {border-left:4px solid #94a3b8;}
.day {margin:1.1rem 0 .4rem;font-weight:700;color:#1e3a8a;border-bottom:2px solid #dbeafe;padding-bottom:4px;}
.day .late {color:#b91c1c;font-weight:600;font-size:.85rem;margin-left:6px;}
.ev {display:flex;gap:12px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px;margin-bottom:10px;}
.ev .hr {min-width:62px;font-weight:700;font-size:1.05rem;color:#1d4ed8;}
.ev .bd {flex:1;min-width:0;}
.ev .tt {font-weight:700;color:#0f172a;margin-right:6px;}
.ev .mt {color:#475569;font-size:.86rem;margin-top:3px;overflow-wrap:anywhere;}
.ev ul {margin:.3rem 0 0 1rem;padding:0;font-size:.85rem;color:#334155;}
.ev .sec {font-size:.78rem;font-weight:700;color:#64748b;margin-top:6px;text-transform:uppercase;}
.cal {display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:.5rem;}
.cal .h {text-align:center;font-size:.72rem;color:#64748b;font-weight:700;}
.cal .c {min-height:64px;border:1px solid #e5e7eb;border-radius:8px;padding:4px;font-size:.7rem;background:#fff;overflow:hidden;}
.cal .c.out {background:#f8fafc;color:#cbd5e1;}
.cal .c.today {outline:2px solid #2563eb;}
.cal .c.prazo {background:#fee2e2;border-color:#fca5a5;}
.cal .c.conf {background:#fef3c7;border-color:#fcd34d;}
.cal .c.apres {background:#dbeafe;border-color:#93c5fd;}
.cal .n {font-weight:700;color:#0f172a;}
.cal .e {display:block;background:#dcfce7;color:#166534;border-radius:4px;padding:1px 3px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.cal .e.prev {background:#fef3c7;color:#92400e;border:1px dashed #d97706;}
.cal .m {display:block;font-weight:700;margin-top:2px;}
.cal .m .sm {display:none;}
.legend {font-size:.78rem;color:#475569;margin-bottom:1rem;}
.legend span {display:inline-block;margin-right:10px;}
.contact {background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:10px 12px;}
.contact .nm {font-weight:700;color:#0f172a;}
.contact .mt {font-size:.84rem;color:#475569;}
@media (max-width: 640px) {
  .block-container {padding-left:1rem;padding-right:1rem;}
  h1 {font-size:1.35rem !important;}
  .kpi .val {font-size:1.1rem;}
  .ev {flex-direction:column;gap:4px;}
  .cal .c {min-height:44px;padding:2px;}
  .cal .e .t {display:none;}
  .cal .m .lg {display:none;}
  .cal .m .sm {display:inline;}
}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def kpi_grid(itens):
    """itens: lista de (rótulo, valor, subtítulo, cor)."""
    cards = "".join(
        f'<div class="kpi {cor}"><div class="lbl">{esc(lbl)}</div><div class="val">{esc(val)}</div>'
        f'<div class="sub">{esc(sub)}</div></div>'
        for lbl, val, sub, cor in itens
    )
    st.markdown(f'<div class="kpis">{cards}</div>', unsafe_allow_html=True)


def event_card_html(item, hoje, mostrar_detalhes=True):
    partes = [
        f'<div class="ev"><div class="hr">{esc(item["Horário"])}</div><div class="bd">',
        f'<span class="tt">{esc(item["Tipo de exame"])}</span>{badge_html(item["Status"])}'
        + (" " + badge_html("Horário previsto", AMARELO) if item.get("Previsto") else ""),
        f'<div class="mt">📍 {esc(item["Clínica / profissional"])} · {esc(item["Endereço"])}</div>',
        f'<div class="mt">💰 {esc(item["Valor"])}</div>',
        '<div class="mt"'
        + (' style="color:#b91c1c;font-weight:700"' if item["_resultado_atrasado"]
           else ' style="color:#b45309;font-weight:700"' if item.get("_resultado_risco") else "")
        + f'>📄 Resultado previsto: {esc(item["Resultado previsto"])}'
        + (" — após o prazo interno" if item["_resultado_atrasado"]
           else " — no pior caso, após o prazo interno" if item.get("_resultado_risco") else "")
        + "</div>",
    ]
    if item["data"] and item["data"] < hoje and item["Status"] not in STATUS_CONCLUIDOS:
        partes.append('<div class="mt" style="color:#b91c1c">Data passou: se já foi feito, toque em “Exame realizado”.</div>')
    if mostrar_detalhes:
        if len(item["Exames"]) > 1:
            partes.append(f'<div class="sec">Exames</div><div class="mt">{esc(", ".join(item["Exames"]))}</div>')
        if item["Orientações"]:
            lis = "".join(f"<li>{esc(o)}</li>" for o in item["Orientações"])
            partes.append(f'<div class="sec">Orientações</div><ul>{lis}</ul>')
        docs = item["Documentos"]
        lis = "".join(f"<li>{esc(d)}</li>" for d in docs) if docs else "<li>Não informados</li>"
        partes.append(f'<div class="sec">Documentos</div><ul>{lis}</ul>')
    partes.append("</div></div>")
    return "".join(partes)


def cal_mark(texto, curto, cor):
    return f'<span class="m" style="color:{cor}"><span class="lg">{texto}</span><span class="sm">{curto}</span></span>'


def calendar_html(itens, meta, hoje, a_marcar=0):
    prazo = parse_date(meta.get("prazo_resultados"))
    conf = parse_date(meta.get("conferencia"))
    apres = parse_date(meta.get("apresentacao"))
    datas = [i["data"] for i in itens if i["data"]] + [d for d in (hoje, prazo, apres) if d]
    inicio, fim = min(datas), max(datas)
    inicio -= timedelta(days=inicio.weekday())
    fim += timedelta(days=6 - fim.weekday())

    por_dia = {}
    for i in itens:
        if i["data"]:
            por_dia.setdefault(i["data"], []).append(i)

    cells = [f'<div class="h">{d}</div>' for d in DIAS_SEMANA]
    d = inicio
    while d <= fim:
        classes = ["c"]
        marcas = []
        if d < hoje:
            classes.append("out")
        if d == hoje:
            classes.append("today")
            if a_marcar:
                marcas.append(cal_mark(f"A marcar: {a_marcar}", f"⚠ {a_marcar}", "#b91c1c"))
        if d == prazo:
            classes.append("prazo")
            marcas.append(cal_mark("Prazo", "Prazo", "#991b1b"))
        if d == conf:
            classes.append("conf")
            marcas.append(cal_mark("Conferência", "Conf.", "#92400e"))
        if d == apres:
            classes.append("apres")
            marcas.append(cal_mark("Apresentação", "Apres.", "#1e40af"))
        eventos = "".join(
            f'<span class="e{" prev" if e.get("Previsto") else ""}" title="{esc(e["Tipo de exame"])}">{esc(e["Horário"])}'
            f'<span class="t"> {esc(e["Tipo de exame"])}</span></span>'
            for e in por_dia.get(d, [])
        )
        cells.append(f'<div class="{" ".join(classes)}"><span class="n">{d.day:02d}/{d.month:02d}</span>{"".join(marcas)}{eventos}</div>')
        d += timedelta(days=1)

    legenda = (
        '<div class="legend"><span>🟩 compromisso</span><span>🟨 horário previsto (ordem de chegada)</span><span>🟥 prazo dos resultados</span>'
        '<span>🟨 conferência</span><span>🟦 apresentação</span><span>🔲 hoje (contorno azul)</span></div>'
    )
    return f'<div class="cal">{"".join(cells)}</div>{legenda}'


def multiselect_filter(df, coluna, rotulo, key, container=st):
    opcoes = [o for o in df[coluna].dropna().unique().tolist() if o != ""]
    escolhidas = container.multiselect(rotulo, opcoes, key=key, placeholder="Todos")
    return df[df[coluna].isin(escolhidas)] if escolhidas else df


# ---------------------------------------------------------------------------
# Abas
# ---------------------------------------------------------------------------

def render_header(data, hoje):
    meta = data["meta"]
    prazo = parse_date(meta["prazo_resultados"])
    st.title("🩺 Exames da Inspeção de Saúde")
    dias = (prazo - hoje).days if prazo else None
    contagem = f"faltam {dias} dias para o prazo dos resultados" if dias is not None and dias >= 0 else "prazo dos resultados vencido"
    st.caption(
        f'{meta["candidata"]} · {meta["cidade"]} · Hoje: {fmt_date(hoje)} · {contagem}'
    )


def render_validation(data):
    erros, avisos = validate_data(data)
    if erros:
        with st.expander(f"⛔ {len(erros)} erro(s) nos dados — corrija o data.json", expanded=True):
            for e in erros:
                st.error(e)
            for a in avisos:
                st.warning(a)
    elif avisos:
        with st.expander(f"⚠️ Dados validados com {len(avisos)} aviso(s)"):
            for a in avisos:
                st.warning(a)
    return erros


def tab_overview(data, rows, agenda, hoje):
    meta = data["meta"]
    resumo = financial_summary(financial_lines(data))
    prazo = parse_date(meta["prazo_resultados"])
    dias = (prazo - hoje).days

    ativos = [r for r in rows if r["Status"] not in STATUS_IGNORADOS]
    agendados = sum(1 for r in ativos if r["Status"] in ("Agendado", "Fechado"))
    pendentes = sum(1 for r in ativos if r["Status"] in STATUS_PRE_AGENDAMENTO)
    recebidos = sum(1 for r in ativos if r["Status"] == "Resultado recebido")
    risco = sum(1 for r in ativos if r["Risco"] in ("Crítico", "Alto"))

    kpi_grid([
        ("Prazo interno dos resultados", meta["prazo_resultados"], f"faltam {dias} dias" if dias >= 0 else "vencido", "red"),
        ("Conferência", meta.get("conferencia", "—"), "", "amber"),
        ("Data de apresentação", meta["apresentacao"], "", "blue"),
        ("Subtotal conhecido", brl(resumo["total"]), f'{resumo["a_cotar"]} item(ns) a cotar', "gray"),
        ("Exames agendados", agendados, f"de {len(ativos)} (inclui ordem de chegada)", "green"),
        ("Exames pendentes", pendentes, "sem agendamento", "amber"),
        ("Resultados recebidos", recebidos, f"de {len(ativos)}", "green"),
        ("Risco de atraso", risco, "crítico ou alto", "red"),
    ])

    col1, col2 = st.columns([1.1, 1])
    with col1:
        st.subheader("📅 Próximos compromissos")
        proximos = [i for i in agenda if i["data"] and i["data"] >= hoje][:5]
        if not proximos:
            st.info("Nenhum compromisso futuro na agenda.")
        for i in proximos:
            quando = "Hoje" if i["data"] == hoje else fmt_dia_semana(i["data"])
            st.markdown(f'<div class="day">{esc(quando)}</div>' + event_card_html(i, hoje, mostrar_detalhes=False), unsafe_allow_html=True)

        st.subheader("🎯 Prioridades atuais")
        for n, item in enumerate(data.get("prioridades", []), 1):
            st.markdown(f"{n}. {item}")

    with col2:
        st.subheader("⏰ Alertas de prazo")
        criticos = [r for r in ativos if r["Risco"] == "Crítico"]
        altos = [r for r in ativos if r["Risco"] == "Alto"]
        atencao = [r for r in ativos if r["Risco"] == "Atenção"]
        for alerta, lista_risco in ((st.error, criticos), (st.warning, altos)):
            grupos = {}
            for r in lista_risco:
                grupos.setdefault((r["Grupo"], r["Motivo do risco"]), []).append(r["Exame"])
            for (grupo, motivo), nomes in grupos.items():
                if len(nomes) == 1:
                    alerta(f"**{nomes[0]}** — {motivo}.")
                else:
                    lista = ", ".join(nomes) if len(nomes) <= 4 else f"{len(nomes)} exames"
                    alerta(f"**{grupo}** — {motivo} ({lista}).")
        if atencao:
            with st.expander(f"ℹ️ {len(atencao)} exame(s) com prazo do resultado a confirmar"):
                for r in atencao:
                    st.markdown(f'- **{r["Exame"]}** — {r["Motivo do risco"]}')
        if not (criticos or altos or atencao):
            st.success("Nenhum alerta de prazo.")

        st.subheader("💰 Resumo financeiro")
        kpi_grid([
            ("Confirmado", brl(resumo["confirmado"]), "", "green"),
            ("Orçamentos", brl(resumo["orcamento"]), "", "amber"),
            ("Estimado", brl(resumo["estimado"]), "", "gray"),
            ("Pago", brl(resumo["pago"]), f'falta {brl(resumo["nao_pago"])}', "blue"),
        ])
        st.markdown("**Por clínica / laboratório**")
        kpi_grid(provider_kpis(totals_by_provider(data)))
        st.caption("SUS, descartados e não exigidos não entram no total. Pacotes entram uma vez só.")


def tab_agenda(data, agenda, hoje):
    st.subheader("📅 Agenda")
    for msg in st.session_state.pop("flash_agenda", []):
        st.success(msg)
    render_agenda_body(data, agenda, hoje)
    st.divider()
    render_pending(data, hoje)


def _update_exams(ids, acao, dia):
    """Callback dos botões da agenda: realizado, resultado recebido ou desfazer."""
    data = st.session_state.data
    alterados = []
    for e in data["exames"]:
        if e["id"] not in ids or e.get("status") in STATUS_IGNORADOS:
            continue
        if acao == "realizado" and e.get("status") not in STATUS_CONCLUIDOS:
            e["status_anterior"] = e.get("status")
            e["status"] = "Realizado"
            e["data_realizacao"] = e.get("data_realizacao") or dia
        elif acao == "resultado" and e.get("status") == "Realizado":
            e["status"] = "Resultado recebido"
            e["data_resultado"] = dia
        elif acao == "desfazer" and e.get("status") == "Resultado recebido":
            e["status"] = "Realizado"
            e["data_resultado"] = None
        elif acao == "desfazer" and e.get("status") == "Realizado":
            e["status"] = e.pop("status_anterior", None) or "Agendado"
            e["data_realizacao"] = None
        else:
            continue
        alterados.append(e.get("nome", e["id"]))
    if not alterados:
        return
    rotulo = {"realizado": "marcado como realizado", "resultado": "com resultado recebido",
              "desfazer": "voltou ao status anterior"}[acao]
    lista = ", ".join(alterados) if len(alterados) <= 3 else f"{len(alterados)} exames"
    ok, msg = save_data_file(data)
    st.session_state.dirty = not ok
    st.session_state.flash_agenda = [f"{lista}: {rotulo}.", msg + " " + AVISO_ARMAZENAMENTO if ok else msg]


def render_card_actions(item, hoje):
    ids = item.get("exame_ids") or []
    if not ids:
        return
    status = item["Status"]
    futuro = bool(item["data"] and item["data"] > hoje)
    dia_realizacao = fmt_date(min(item["data"], hoje) if item["data"] else hoje)
    c1, c2, c3 = st.columns(3)
    if status not in STATUS_CONCLUIDOS:
        c1.button(
            "✅ Exame realizado", key=f"ag_fim_{item['id']}", width="stretch", disabled=futuro,
            on_click=_update_exams, args=(ids, "realizado", dia_realizacao),
            help="Disponível a partir do dia do exame." if futuro else "Marca os exames deste compromisso como realizados.",
        )
    if status == "Realizado":
        c2.button(
            "📄 Resultado recebido", key=f"ag_res_{item['id']}", width="stretch",
            on_click=_update_exams, args=(ids, "resultado", fmt_date(hoje)),
        )
    if status in STATUS_CONCLUIDOS:
        c3.button(
            "↩️ Desfazer", key=f"ag_desf_{item['id']}", width="stretch",
            on_click=_update_exams, args=(ids, "desfazer", fmt_date(hoje)),
        )


def render_agenda_body(data, agenda, hoje):
    if not agenda:
        st.info("Nenhum compromisso cadastrado.")
        return
    df = pd.DataFrame(agenda)

    with st.expander("🔎 Filtros", expanded=False):
        c1, c2 = st.columns(2)
        c3, c4 = st.columns(2)
        df = multiselect_filter(df, "Data", "Data", "ag_f_data", c1)
        df = multiselect_filter(df, "Clínica", "Clínica", "ag_f_clinica", c2)
        df = multiselect_filter(df, "Status", "Status", "ag_f_status", c3)
        df = multiselect_filter(df, "Tipo de exame", "Tipo de exame", "ag_f_tipo", c4)
    filtrados = [i for i in agenda if i["id"] in set(df["id"])]

    st.markdown("#### Calendário")
    st.markdown(calendar_html(filtrados, data["meta"], hoje, len(pending_to_schedule(data, hoje))), unsafe_allow_html=True)

    if not filtrados:
        st.info("Nenhum compromisso com esses filtros.")
        return

    prazo = parse_date(data["meta"]["prazo_resultados"])
    dia_atual = None
    for i in filtrados:
        if i["data"] != dia_atual:
            dia_atual = i["data"]
            extra = '<span class="late">após o prazo interno</span>' if prazo and dia_atual and dia_atual > prazo else ""
            rotulo = fmt_dia_semana(dia_atual) if dia_atual else "Sem data"
            st.markdown(f'<div class="day">{esc(rotulo)}{extra}</div>', unsafe_allow_html=True)
        st.markdown(event_card_html(i, hoje), unsafe_allow_html=True)
        render_card_actions(i, hoje)

    with st.expander("Ver agenda em tabela"):
        tabela = df.drop(columns=["id", "data", "dt", "Clínica", "Exames", "exame_ids",
                                  "_resultado_atrasado", "_resultado_risco"]).copy()
        tabela["Previsto"] = tabela["Previsto"].map({True: "Sim", False: ""})
        tabela["Orientações"] = tabela["Orientações"].map("; ".join)
        tabela["Documentos"] = tabela["Documentos"].map(lambda d: "; ".join(d) or "Não informados")
        st.dataframe(style_cells(tabela, ["Status"]), hide_index=True, width="stretch")


def tab_exams(data, rows):
    st.subheader("✅ Exames exigidos")
    df = pd.DataFrame(rows)

    q = st.text_input("Pesquisar em todas as colunas", key="ex_busca", placeholder="Ex.: ultramedical, cobb, hepatite, 1741")
    c1, c2, c3 = st.columns([1.3, 1.3, 1])
    status_sel = c1.multiselect("Status", STATUS_LIST, key="ex_f_status", placeholder="Todos")
    df = multiselect_filter(df, "Grupo", "Grupo", "ex_f_grupo", c2)
    so_risco = c3.toggle("Só com risco de atraso", key="ex_f_risco")

    df = search_df(df, q)
    if status_sel:
        df = df[df["Status"].isin(status_sel)]
    if so_risco:
        df = df[df["Risco"].isin(["Crítico", "Alto"])]

    st.caption(f"{len(df)} de {len(rows)} exames")
    colunas = [
        "Ordem", "Grupo", "Exame", "Exigência do edital", "Clínica / profissional", "Valor",
        "Data agendada", "Prazo do resultado", "Status", "Risco", "Pendências", "Observações",
        "Motivo do risco", "Tipo de valor", "Pago", "Protocolo", "Código de acompanhamento",
        "Realizado em", "Resultado em", "Válido a partir de",
    ]
    st.dataframe(
        style_cells(df[colunas], ["Status", "Risco"]),
        hide_index=True,
        width="stretch",
        height=min(38 * (len(df) + 1) + 4, 620),
        column_config={
            "Ordem": st.column_config.NumberColumn(width="small"),
            "Exame": st.column_config.TextColumn(width="medium"),
            "Pendências": st.column_config.TextColumn(width="large"),
        },
    )
    st.markdown(
        " ".join(badge_html(s) for s in STATUS_LIST)
        + " " + badge_html("Crítico", RISCO_CORES["Crítico"]) + " " + badge_html("Alto", RISCO_CORES["Alto"]),
        unsafe_allow_html=True,
    )

    st.subheader("🏥 SUS × particular")
    todos = pd.DataFrame(rows)
    eh_sus = (todos["Status"] == "SUS") | (todos["Tipo de valor"] == VALOR_TIPOS["sus"])
    sus = todos[eh_sus]
    particulares = todos[~eh_sus & ~todos["Status"].isin(STATUS_IGNORADOS)]
    fora = todos[todos["Status"].isin(STATUS_IGNORADOS)]
    s1, s2 = st.columns(2)
    with s1:
        st.info(f"**Pelo SUS ({len(sus)})**")
        for _, r in sus.iterrows():
            st.markdown(f'- {r["Exame"]} — {r["Data agendada"]}')
        if len(fora):
            st.caption("Fora do edital / descartados: " + ", ".join(fora["Exame"]))
    with s2:
        st.warning(f"**Particulares ({len(particulares)})**")
        for grupo, g in particulares.groupby("Grupo", sort=False):
            st.markdown(f"- **{grupo}**: {', '.join(g['Exame'])}")


def tab_finance(data):
    st.subheader("💰 Financeiro")
    linhas = financial_lines(data)
    resumo = financial_summary(linhas)
    if not resumo["consistente"]:
        st.error("Os subtotais não fecham com o total. Verifique o data.json.")

    kpi_grid([
        ("Total geral", brl(resumo["total"]), "confirmado + orçamentos + estimado", "blue"),
        ("Valor confirmado", brl(resumo["confirmado"]), "", "green"),
        ("Orçamentos (favoritos)", brl(resumo["orcamento"]), "", "amber"),
        ("Valor estimado", brl(resumo["estimado"]), "", "gray"),
        ("Total pago", brl(resumo["pago"]), "", "green"),
        ("Ainda não pago", brl(resumo["nao_pago"]), "", "red"),
        ("Itens a cotar", resumo["a_cotar"], "sem valor", "amber"),
        ("Opções fora do total", brl(resumo["opcoes"]), "somam se escolhidas", "gray"),
    ])

    st.markdown("#### Quanto vai ficar em cada clínica / laboratório")
    totais = totals_by_provider(data)
    kpi_grid(provider_kpis(totais))
    pdf = pd.DataFrame([
        {
            "Clínica / laboratório": nome,
            "Total": brl(t["total"]) if t["total"] else ("—" if t["opcao"] else "A cotar"),
            "Confirmado": brl(t["confirmado"]),
            "Orçamento": brl(t["orcamento"]),
            "Estimado": brl(t["estimado"]),
            "Opções fora do total": brl(t["opcao"]),
            "Itens a cotar": t["a_cotar"],
            "Pago": brl(t["pago"]),
            "A pagar": brl(t["total"] - t["pago"]),
            "O que inclui": "; ".join(t["itens"]),
        }
        for nome, t in totais.items()
    ])
    st.dataframe(pdf, hide_index=True, width="stretch")
    soma_prestadores = round(sum(t["total"] for t in totais.values()), 2)
    if abs(soma_prestadores - resumo["total"]) > 0.005:
        st.error(f"A soma por prestador ({brl(soma_prestadores)}) não confere com o total geral ({brl(resumo['total'])}).")
    else:
        st.caption(f"Soma por prestador confere com o total geral: {brl(soma_prestadores)}. Exames do SUS não aparecem (custo zero).")

    render_payment_simulator(data, resumo)

    st.markdown("#### Composição do total (sem dupla contagem)")
    tabela = pd.DataFrame([
        {
            "Descrição": l["Descrição"],
            "Origem": l["Origem"],
            "Valor": brl(l["valor"]),
            "Tipo": VALOR_TIPOS.get(l["tipo"], l["tipo"]),
            "No total": "Sim" if l["tipo"] in VALOR_TIPOS_NO_TOTAL else "Não",
            "Pago": "Sim" if l["pago"] else "Não",
            "Itens incluídos": l["Itens"],
        }
        for l in linhas if l["tipo"] not in ("sus", "nao_exigido")
    ])
    st.dataframe(tabela, hide_index=True, width="stretch")
    st.caption(
        "Exames dentro de um pacote aparecem só no pacote. Ex.: os R$ 1.260,00 da Ultramedical já incluem "
        "radiologia, ultrassom das mamas, ECG e colpocitológico."
    )

    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.markdown("#### Valor por grupo")
        grupos = values_by_group(data)
        gdf = pd.DataFrame([
            {"Grupo": g, "Valor": brl(v["valor"]), "Itens com valor": v["itens"], "A cotar": v["a_cotar"]}
            for g, v in grupos.items()
        ])
        st.dataframe(gdf, hide_index=True, width="stretch")
    with c2:
        st.markdown("#### Valor por exame")
        pacotes = index_by_id(data["pacotes"])
        edf = pd.DataFrame([
            {
                "Exame": e.get("nome"),
                "Grupo": e.get("grupo"),
                "Valor": exam_value_label(e, pacotes),
                "Tipo": VALOR_TIPOS.get(e.get("valor_tipo"), ""),
                "Status": e.get("status"),
            }
            for e in sorted(data["exames"], key=lambda e: e.get("ordem", 0))
        ])
        st.dataframe(style_cells(edf, ["Status"]), hide_index=True, width="stretch", height=360)

    st.markdown("#### Comparativo entre clínicas e economia")
    for comp in data.get("comparativos", []):
        resumo_comp = comparison_summary(comp)
        if not resumo_comp:
            continue
        with st.container(border=True):
            ref = resumo_comp["referencia"]
            rotulo = "Escolhida" if resumo_comp["escolhida"] else "Mais barata (nenhuma escolhida)"
            st.markdown(f'**{comp["categoria"]}** — {rotulo}: {ref["nome"]} · {brl(ref["valor"])}')
            texto = f'Economia de **{brl(resumo_comp["economia_max"])}** em relação à opção mais cara ({resumo_comp["mais_cara"]["nome"]}).'
            if resumo_comp["proxima"] and resumo_comp["proxima"] is not resumo_comp["mais_cara"]:
                texto += f' Em relação à próxima opção ({resumo_comp["proxima"]["nome"]}): {brl(resumo_comp["economia_proxima"])}.'
            st.markdown(texto)
            cdf = pd.DataFrame([
                {
                    "Opção": o["nome"],
                    "Valor": brl(o.get("valor")),
                    "Diferença": brl((o["valor"] - ref["valor"]) if o.get("valor") is not None else None, "—"),
                    "Escolhida": "Sim" if o.get("escolhida") else "",
                    "Observações": o.get("observacoes", ""),
                }
                for o in sorted(comp["opcoes"], key=lambda o: (o.get("valor") is None, o.get("valor") or 0))
            ])
            st.dataframe(cdf, hide_index=True, width="stretch")

    pendencias = [l["Descrição"] for l in linhas if l["tipo"] == "a_cotar"]
    opcoes = [f'{l["Descrição"]} ({brl(l["valor"])})' for l in linhas if l["tipo"] == "opcao"]
    if pendencias or opcoes:
        msg = []
        if pendencias:
            msg.append("**Sem valor (a cotar):** " + ", ".join(pendencias))
        if opcoes:
            msg.append("**Opções que ainda não entram no total:** " + ", ".join(opcoes))
        st.warning("  \n".join(msg))


def render_payment_simulator(data, resumo):
    st.markdown("#### 💳 À vista (líquido) × parcelado")
    teto = data["meta"].get("orcamento_teto")
    if teto:
        folga = teto - resumo["total"]
        st.caption(
            f"Teto planejado: {brl(teto)} · total atual: {brl(resumo['total'])} · "
            + (f"folga de {brl(folga)}" if folga >= 0 else f"acima do teto em {brl(-folga)}")
        )

    parcelaveis = [c for c in data["contatos"] if c.get("parcelas_max")]
    parcelas_por_contato = {}
    cols = st.columns(len(parcelaveis) + 1) if parcelaveis else [st]
    for col, c in zip(cols, parcelaveis):
        parcelas_por_contato[c["id"]] = col.number_input(
            f"Parcelas — {c['nome']}", min_value=1, max_value=int(c["parcelas_max"]),
            value=int(c.get("parcelas", 1)), step=1, key=f"parc_{c['id']}",
        )
    juros = cols[-1].number_input(
        "Juros do parcelamento (% ao mês)", min_value=0.0, max_value=20.0, value=0.0, step=0.1,
        format="%.2f", key="parc_juros", help="Deixe 0 se a clínica parcelar sem juros.",
    )

    plano = payment_plan(data, parcelas_por_contato, juros)
    liquido = sum(l["a_pagar"] for l in plano if l["parcelas"] == 1)
    parcelado = [l for l in plano if l["parcelas"] > 1]
    mensal = sum(l["parcela"] for l in parcelado)
    custo_final = liquido + sum(l["total_pago"] for l in parcelado)
    kpi_grid([
        ("Precisa à vista (líquido)", brl(liquido), "dinheiro, Pix ou débito", "green"),
        ("Parcelado", brl(sum(l["a_pagar"] for l in parcelado)),
         " + ".join(f'{l["parcelas"]}× {brl(l["parcela"])}' for l in parcelado) or "nada parcelado", "blue"),
        ("Parcela mensal", brl(mensal), "no cartão", "amber"),
        ("Custo final", brl(custo_final), "com juros" if juros else "sem juros", "gray"),
    ])
    st.dataframe(pd.DataFrame([
        {
            "Clínica / laboratório": l["nome"],
            "A pagar": brl(l["a_pagar"]),
            "Forma": "À vista" if l["parcelas"] == 1 else f'{l["parcelas"]}× de {brl(l["parcela"])}',
            "Total com juros": brl(l["total_pago"]),
            "Condição informada": l["forma"],
        }
        for l in plano
    ]), hide_index=True, width="stretch")
    st.caption("Parcelas são simulação: confirme com cada clínica se aceita cartão, o número de parcelas e se há juros.")


def tab_contacts(data):
    st.subheader("📱 Contatos")
    contatos = data["contatos"]
    df = pd.DataFrame([
        {
            "id": c["id"],
            "Categoria": c.get("categoria", ""),
            "Nome": contact_label(c),
            "Final": c.get("final") or "—",
            "Telefone": c.get("telefone") or "Não cadastrado",
            "WhatsApp": whatsapp_url(c.get("telefone")),
            "Valor informado": brl(c.get("valor"), "—"),
            "Situação": c.get("situacao", ""),
            "Observações": c.get("observacoes", ""),
        }
        for c in contatos
    ])
    c1, c2 = st.columns([1.4, 1])
    q = c1.text_input("Pesquisar contato", placeholder="Nome, final, categoria…")
    df = multiselect_filter(df, "Categoria", "Categoria", "ct_f_categoria", c2)
    df = search_df(df, q)
    st.caption(f"{len(df)} contato(s). Só aparecem números cadastrados no data.json.")

    por_id = index_by_id(contatos)
    cols = st.columns(2)
    for n, cid in enumerate(df["id"]):
        c = por_id[cid]
        link = whatsapp_url(c.get("telefone"))
        with cols[n % 2].container(border=True):
            st.markdown(
                f'<div class="nm" style="font-weight:700">{esc(contact_label(c))}</div>'
                f'<div class="mt" style="font-size:.84rem;color:#475569">{esc(c.get("categoria"))} · '
                f'{esc(c.get("telefone") or "número completo não cadastrado")} · {esc(brl(c.get("valor"), "sem valor"))} · '
                f'{esc(c.get("situacao"))}</div>'
                + (f'<div class="mt" style="font-size:.8rem;color:#64748b">{esc(c.get("observacoes"))}</div>' if c.get("observacoes") else ""),
                unsafe_allow_html=True,
            )
            if link:
                st.link_button("💬 Abrir WhatsApp", link, width="stretch")

    with st.expander("Ver contatos em tabela"):
        st.dataframe(
            df.drop(columns=["id"]),
            hide_index=True,
            width="stretch",
            column_config={"WhatsApp": st.column_config.LinkColumn("WhatsApp", display_text="Abrir")},
        )


def tab_edital(data):
    st.subheader("📄 Edital PDF")
    documentos = data.get("documentos", [])
    if not documentos:
        st.info("Nenhum documento cadastrado em data.json.")
    for doc in documentos:
        st.markdown(f"#### {doc['nome']}")
        if doc.get("descricao"):
            st.caption(doc["descricao"])
        for n, img in enumerate(doc.get("imagens", []), 1):
            caminho = BASE_DIR / img
            if caminho.is_file():
                st.image(str(caminho), caption=f"Página {n}", width="stretch")
            else:
                st.warning(f"Imagem não encontrada: {img}")


def _date_or_none(value):
    return value.strftime("%d/%m/%Y") if value else None


def tab_settings(data):
    st.subheader("⚙️ Configurações")
    show_flash()
    st.warning(AVISO_ARMAZENAMENTO)

    exames = sorted(data["exames"], key=lambda e: e.get("ordem", 0))
    pacotes = index_by_id(data["pacotes"])

    st.markdown("#### Atualizar exame")
    rotulos = {e["id"]: f'{e.get("ordem")}. {e.get("nome")} — {e.get("status")}' for e in exames}
    eid = st.selectbox("Exame", list(rotulos), format_func=rotulos.get, key="cfg_exame")
    ex = next(e for e in exames if e["id"] == eid)

    with st.form(f"form_exame_{eid}"):
        c1, c2 = st.columns(2)
        status = c1.selectbox("Status", STATUS_LIST, index=STATUS_LIST.index(ex["status"]) if ex.get("status") in STATUS_LIST else 0)
        tipos = list(VALOR_TIPOS)
        valor_tipo = c2.selectbox(
            "Tipo de valor", tipos, format_func=VALOR_TIPOS.get,
            index=tipos.index(ex["valor_tipo"]) if ex.get("valor_tipo") in tipos else 0,
        )
        c3, c4, c5 = st.columns(3)
        realizacao = c3.date_input("Data de realização", value=parse_date(ex.get("data_realizacao")), format="DD/MM/YYYY")
        resultado = c4.date_input("Data do resultado", value=parse_date(ex.get("data_resultado")), format="DD/MM/YYYY")
        prazo_res = c5.date_input("Prazo do resultado (data informada)", value=parse_date(ex.get("prazo_resultado")), format="DD/MM/YYYY")
        dias_uteis = c5.number_input(
            "Prazo em dias úteis (média)", value=ex.get("prazo_dias_uteis"), min_value=0, step=1,
            placeholder="Não informado", help="Usado para prever o resultado quando não há data informada.",
        )
        dias_uteis_min = c5.number_input(
            "Prazo mínimo em dias úteis", value=ex.get("prazo_dias_uteis_min"), min_value=0, step=1,
            placeholder="Não informado", help="Preencha quando o laboratório informar uma faixa (ex.: 5 a 10 dias úteis).",
        )
        c6, c7 = st.columns(2)
        valor = c6.number_input(
            "Valor (R$)", value=float(ex["valor"]) if ex.get("valor") is not None else None,
            min_value=0.0, step=1.0, format="%.2f", placeholder="A cotar",
        )
        if ex.get("pacote"):
            c7.caption(f'Pagamento controlado pelo pacote “{pacotes[ex["pacote"]]["nome"]}”. Ajuste abaixo.')
            pago = bool(ex.get("pago"))
        else:
            pago = c7.checkbox("Pago", value=bool(ex.get("pago")))
        c8, c9 = st.columns(2)
        protocolo = c8.text_input("Protocolo", value=ex.get("protocolo", ""))
        codigo = c9.text_input("Código de acompanhamento", value=ex.get("codigo_acompanhamento", ""))
        pendencias = st.text_area("Pendências", value=ex.get("pendencias", ""), height=70)
        observacoes = st.text_area("Observações", value=ex.get("observacoes", ""), height=70)
        if st.form_submit_button("Aplicar alterações", type="primary"):
            ex.update({
                "status": status,
                "valor_tipo": valor_tipo,
                "data_realizacao": _date_or_none(realizacao),
                "data_resultado": _date_or_none(resultado),
                "prazo_resultado": _date_or_none(prazo_res),
                "prazo_dias_uteis": int(dias_uteis) if dias_uteis is not None else None,
                "prazo_dias_uteis_min": int(dias_uteis_min) if dias_uteis_min is not None else None,
                "valor": (int(valor) if float(valor).is_integer() else round(valor, 2)) if valor is not None else None,
                "pago": pago,
                "protocolo": protocolo.strip(),
                "codigo_acompanhamento": codigo.strip(),
                "pendencias": pendencias.strip(),
                "observacoes": observacoes.strip(),
            })
            apply_and_rerun(
                f'Exame “{ex.get("nome")}” atualizado nesta sessão.',
                "Exame em pacote: o total usa o valor do pacote. Se o preço mudou, ajuste o pacote abaixo."
                if ex.get("pacote") else "",
                "Data do resultado informada: considere mudar o status para “Resultado recebido”."
                if resultado and status != "Resultado recebido" else "",
            )

    st.markdown("#### Atualizar pacote")
    if data["pacotes"]:
        pid = st.selectbox("Pacote", list(pacotes), format_func=lambda p: pacotes[p]["nome"], key="cfg_pacote")
        pac = pacotes[pid]
        with st.form(f"form_pacote_{pid}"):
            c1, c2, c3 = st.columns(3)
            valor_p = c1.number_input("Valor do pacote (R$)", value=float(pac.get("valor") or 0), min_value=0.0, step=1.0, format="%.2f")
            tipos_p = ["confirmado", "orcamento", "estimado"]
            tipo_p = c2.selectbox("Tipo de valor", tipos_p, format_func=VALOR_TIPOS.get,
                                  index=tipos_p.index(pac["valor_tipo"]) if pac.get("valor_tipo") in tipos_p else 1)
            pago_p = c3.checkbox("Pago", value=bool(pac.get("pago")))
            obs_p = st.text_area("Observações do pacote", value=pac.get("observacoes", ""), height=70)
            if st.form_submit_button("Aplicar no pacote", type="primary"):
                pac.update({
                    "valor": int(valor_p) if float(valor_p).is_integer() else round(valor_p, 2),
                    "valor_tipo": tipo_p,
                    "pago": pago_p,
                    "observacoes": obs_p.strip(),
                })
                apply_and_rerun(f'Pacote “{pac["nome"]}” atualizado nesta sessão.')

    st.markdown("#### Novo compromisso na agenda")
    contatos = index_by_id(data["contatos"])
    with st.form("form_agenda", clear_on_submit=True):
        c1, c2 = st.columns(2)
        dia = c1.date_input("Data", value=None, format="DD/MM/YYYY")
        hora = c2.time_input("Horário", value=None, step=300)
        tipo = st.text_input("Tipo de exame")
        c3, c4 = st.columns(2)
        contato_id = c3.selectbox("Clínica / contato", [None] + list(contatos),
                                  format_func=lambda c: "(nenhum)" if c is None else contact_label(contatos[c]))
        profissional = c4.text_input("Profissional")
        c5, c6 = st.columns([2, 1])
        endereco = c5.text_input("Endereço")
        valor_ag = c6.number_input("Valor (R$)", value=None, min_value=0.0, step=1.0, format="%.2f")
        vinculados = st.multiselect("Exames deste compromisso", [e["id"] for e in exames], format_func=lambda i: rotulos[i])
        orientacoes = st.text_area("Orientações (uma por linha)", height=70)
        documentos = st.text_area("Documentos necessários (um por linha)", height=70)
        if st.form_submit_button("Adicionar à agenda", type="primary"):
            if not (dia and hora and tipo.strip()):
                st.error("Informe data, horário e tipo de exame.")
            else:
                novo_id = f"ag_{dia.strftime('%Y%m%d')}_{hora.strftime('%H%M')}_{len(data['agenda'])}"
                data["agenda"].append({
                    "id": novo_id,
                    "data": dia.strftime("%d/%m/%Y"),
                    "horario": hora.strftime("%H:%M"),
                    "tipo": tipo.strip(),
                    "contato": contato_id,
                    "profissional": profissional.strip(),
                    "endereco": endereco.strip() or None,
                    "valor": valor_ag,
                    "exames": vinculados,
                    "orientacoes": [l.strip() for l in orientacoes.splitlines() if l.strip()],
                    "documentos": [l.strip() for l in documentos.splitlines() if l.strip()],
                })
                for e in data["exames"]:
                    if e["id"] in vinculados and e.get("status") in STATUS_PRE_AGENDAMENTO:
                        e["status"] = "Agendado"
                apply_and_rerun("Compromisso adicionado. Exames vinculados passaram para “Agendado”.")

    st.markdown("#### Salvar, exportar e importar")
    if st.session_state.get("dirty"):
        st.info("Há alterações nesta sessão que ainda não foram salvas nem exportadas.")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "⬇️ Exportar JSON", data_to_json(data).encode("utf-8"), file_name="data.json",
        mime="application/json", width="stretch",
    )
    if c2.button("💾 Gravar no data.json", width="stretch"):
        ok, msg = save_data_file(data)
        (st.success if ok else st.error)(msg)
        if ok:
            st.session_state.dirty = False
    if c3.button("↩️ Descartar alterações", width="stretch"):
        st.session_state.data = read_data_file()
        st.session_state.dirty = False
        st.rerun()

    arquivo = st.file_uploader("Importar JSON exportado anteriormente", type=["json"])
    if arquivo is not None and st.button("Carregar JSON importado"):
        try:
            novo = json.loads(arquivo.getvalue().decode("utf-8"))
            erros, _ = validate_data(novo)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            st.error(f"Arquivo inválido: {exc}")
        else:
            if erros:
                st.error("O arquivo tem erros e não foi carregado:\n\n- " + "\n- ".join(erros))
            else:
                st.session_state.data = novo
                apply_and_rerun("JSON importado. Exporte ou grave para manter as alterações.")


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

def main():
    inject_css()
    init_state()
    data = st.session_state.data
    hoje = today_ms()

    render_header(data, hoje)
    erros = render_validation(data)
    if any("Chave obrigatória" in e for e in erros):
        st.stop()

    rows = build_exam_rows(data, hoje)
    agenda = build_agenda(data, hoje)

    with st.sidebar:
        st.markdown(f'**{data["meta"]["candidata"]}**')
        st.caption(f'Resultados até {data["meta"]["prazo_resultados"]} · Apresentação em {data["meta"]["apresentacao"]}')
        if st.session_state.get("dirty"):
            st.warning("Alterações não salvas.")
        st.download_button("⬇️ Exportar JSON", data_to_json(data).encode("utf-8"), file_name="data.json",
                           mime="application/json", width="stretch", key="sb_export")

    abas = st.tabs(["Visão geral", "Agenda", "Exames", "Financeiro", "Contatos", "Edital PDF", "Configurações"])
    with abas[0]:
        tab_overview(data, rows, agenda, hoje)
    with abas[1]:
        tab_agenda(data, agenda, hoje)
    with abas[2]:
        tab_exams(data, rows)
    with abas[3]:
        tab_finance(data)
    with abas[4]:
        tab_contacts(data)
    with abas[5]:
        tab_edital(data)
    with abas[6]:
        tab_settings(data)

    st.divider()
    st.caption("Painel pessoal de acompanhamento. Confirme sempre as exigências no edital e os prazos com cada prestador.")


main()
