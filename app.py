import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Exames Exército", page_icon="🩺", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"

@st.cache_data(ttl=10)
def load_data():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))

def brl(value):
    if value is None:
        return "A cotar"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def status_badge(status):
    style = {
        "Agendado": "background:#dcfce7;color:#166534",
        "Fechado": "background:#dcfce7;color:#166534",
        "Quase fechado": "background:#fef3c7;color:#92400e",
        "Pendente": "background:#fee2e2;color:#991b1b",
        "SUS": "background:#dbeafe;color:#1e40af",
        "Retirado": "background:#e5e7eb;color:#374151",
        "Em cotação": "background:#ede9fe;color:#5b21b6",
    }.get(status, "background:#f3f4f6;color:#374151")
    return f'<span style="{style};padding:4px 9px;border-radius:999px;font-size:12px;font-weight:700">{status}</span>'

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {background:white;border:1px solid #e5e7eb;border-radius:12px;padding:12px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.panel {background:white;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:14px}
.small {color:#64748b;font-size:.88rem}
iframe {border-radius:10px;border:1px solid #e5e7eb}
</style>
""", unsafe_allow_html=True)

data = load_data()
meta = data["meta"]

st.title("🩺 Painel de Exames da Inspeção Militar")
st.caption(f'{meta["candidata"]} | {meta["cidade"]} | Resultados até {meta["prazo_interno"]} | Apresentação em {meta["apresentacao"]}')

pages = st.tabs(["Visão geral", "Agenda", "Exames", "Financeiro", "Contatos", "Painel digital"])

with pages[0]:
    known = sum(item.get("valor") or 0 for item in data["custos_base"])
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Prazo interno", meta["prazo_interno"])
    c2.metric("Apresentação", meta["apresentacao"])
    c3.metric("Subtotal conhecido", brl(known))
    c4.metric("Agendados", sum(1 for x in data["exames"] if x["status"] == "Agendado"))
    c5.metric("Pendentes", sum(1 for x in data["exames"] if x["status"] in ["Pendente", "Em cotação"]))

    st.subheader("Próximos compromissos")
    agenda_df = pd.DataFrame(data["agenda"])
    st.dataframe(agenda_df, use_container_width=True, hide_index=True)

    st.subheader("Prioridades")
    for i, item in enumerate(data["prioridades"], 1):
        st.markdown(f"**{i}. {item}**")

with pages[1]:
    st.subheader("📅 Agenda por dia")
    agenda = sorted(data["agenda"], key=lambda x: datetime.strptime(x["data"]+" "+x["horario"], "%d/%m/%Y %H:%M"))
    for item in agenda:
        with st.container(border=True):
            a,b,c = st.columns([1,2.2,1.2])
            a.markdown(f'### {item["data"]}')
            a.markdown(f'**{item["horario"]}**')
            b.markdown(f'**{item["tipo"]}**')
            b.caption(f'{item["local"]} | {item.get("endereco", "Endereço a confirmar")}')
            c.markdown(status_badge(item["status"]), unsafe_allow_html=True)
            if item.get("observacao"):
                st.info(item["observacao"])

with pages[2]:
    st.subheader("✅ Checklist completo")
    df = pd.DataFrame(data["exames"])
    q = st.text_input("Pesquisar exame, local ou pendência")
    statuses = st.multiselect("Status", sorted(df["status"].unique()))
    if q:
        mask = df.astype(str).apply(lambda c: c.str.contains(q, case=False, na=False)).any(axis=1)
        df = df[mask]
    if statuses:
        df = df[df["status"].isin(statuses)]
    display = df.copy()
    display["valor"] = display["valor"].apply(brl)
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader("Exames do SUS")
    s1,s2 = st.columns(2)
    with s1:
        st.success("Serão realizados")
        for x in data["sus"]["realizados"]:
            st.write("•", x)
    with s2:
        st.warning("Precisam ser particulares")
        for x in data["sus"]["nao_realizados"]:
            st.write("•", x)

with pages[3]:
    st.subheader("💰 Resumo financeiro")
    fdf = pd.DataFrame(data["custos_base"])
    fdf["valor"] = fdf["valor"].apply(brl)
    st.dataframe(fdf, use_container_width=True, hide_index=True)
    st.warning("O total final ainda depende de HDL, LDL, T4 Livre, avaliação odontológica e confirmação do oftalmológico.")

    st.subheader("Comparativo de radiologia")
    rdf = pd.DataFrame(data["radiologia"])
    rdf["total"] = rdf["total"].apply(brl)
    st.dataframe(rdf, use_container_width=True, hide_index=True)

with pages[4]:
    st.subheader("📱 Contatos")
    cdf = pd.DataFrame(data["contatos"])
    q2 = st.text_input("Pesquisar contato")
    if q2:
        cdf = cdf[cdf.astype(str).apply(lambda c: c.str.contains(q2, case=False, na=False)).any(axis=1)]
    st.dataframe(cdf, use_container_width=True, hide_index=True)
    st.caption("Os quatro últimos dígitos ficam junto ao nome para facilitar a localização no WhatsApp.")

with pages[5]:
    st.subheader("🌐 Digital em IFRAME")
    st.write("Use este quadro para abrir o edital, pasta digital, sistema do laboratório ou outro endereço web sem sair do painel.")
    default_url = data.get("iframe_url", "https://www.gov.br")
    iframe_url = st.text_input("URL para abrir", value=default_url)
    height = st.slider("Altura do quadro", 400, 1200, 750, 50)
    if iframe_url:
        components.iframe(iframe_url, height=height, scrolling=True)
        st.caption("Alguns sites bloqueiam abertura em iframe por segurança. Nesse caso, use o botão abaixo.")
        st.link_button("Abrir em nova aba", iframe_url)

st.divider()
st.caption("Painel pessoal de acompanhamento. Confirme sempre as exigências no edital e os prazos diretamente com cada prestador.")
