"""Busca de resultados nos portais dos laboratórios.

- Ultramedical: portal Pixeon Korus (ASP.NET WebForms), login de paciente com CPF e senha.
  O botão "Visualizar todos" devolve um único PDF com todos os laudos disponíveis.
- Sodré (toxicológico): portal do doador com login Keycloak (CPF com máscara e senha).
  A API do portal informa a rastreabilidade da amostra e o laudo é baixado em PDF.
- SUS (LABCEM, Prefeitura de Campo Grande): sistema Net, login com usuário e senha da etiqueta
  de coleta. A API lista os pedidos e o laudo de cada pedido sai em PDF.

As credenciais chegam por parâmetro (vêm de st.secrets) e nunca são gravadas.
"""

import base64
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin

try:  # Em redes com proxy corporativo, usa os certificados do sistema operacional.
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - opcional
    pass

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ExamesExercito/1.0"
TIMEOUT = 90

ULTRA_BASE = "https://ultralbd-rol.pixeonkorus.com/"
ULTRA_LOGIN = ULTRA_BASE + "Login.aspx?ad=ultralbd"
ULTRA_PACIENTE = ULTRA_BASE + "Paciente.aspx?ad=ultralbd"
ULTRA_CAMPO = "ctl00$ContentPlaceHolderConteudo$"

SODRE_BASE = "https://cliente.sodretox.com.br"
SODRE_RESULTADOS = SODRE_BASE + "/minha-conta/resultados"

SUS_BASE = "http://exames.capital.ms.gov.br"  # o site não responde em https


class PortalErro(Exception):
    """Falha de login ou mudança no portal."""


@dataclass
class Laudo:
    titulo: str
    arquivo: str
    pdf: bytes


@dataclass
class ResultadoPortal:
    portal: str
    itens: list = field(default_factory=list)  # dicts com data, descricao, status
    laudos: list = field(default_factory=list)  # Laudo
    detalhes: dict = field(default_factory=dict)


def _sessao():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _inputs(form, tipos=(None, "hidden", "text", "password")):
    return {
        i["name"]: i.get("value", "")
        for i in form.find_all("input")
        if i.get("name") and (i.get("type") or "").lower() in {(t or "") for t in tipos}
    }


def cpf_com_mascara(cpf):
    d = re.sub(r"\D", "", str(cpf))
    if len(d) != 11:
        raise PortalErro("CPF inválido nos secrets (precisa ter 11 dígitos).")
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def cpf_sem_mascara(cpf):
    return re.sub(r"\D", "", str(cpf))


# ---------------------------------------------------------------------------
# Ultramedical (Pixeon Korus)
# ---------------------------------------------------------------------------

def ultramedical_buscar(cpf, senha, baixar=True):
    s = _sessao()
    soup = BeautifulSoup(s.get(ULTRA_LOGIN, timeout=TIMEOUT).text, "html.parser")
    form = soup.find("form")
    if not form:
        raise PortalErro("Ultramedical: página de login mudou (formulário não encontrado).")
    dados = {k: v for k, v in _inputs(form).items() if k.startswith("__")}
    dados[ULTRA_CAMPO + "TXT_Cpf"] = cpf_sem_mascara(cpf)
    dados[ULTRA_CAMPO + "TXT_PacienteSenha"] = senha
    dados[ULTRA_CAMPO + "BTN_PacienteAcesso"] = "Entrar"
    r = s.post(ULTRA_LOGIN, data=dados, timeout=TIMEOUT)
    if "Paciente.aspx" not in r.url:
        raise PortalErro("Ultramedical: login recusado. Confira CPF e senha nos secrets.")

    soup = BeautifulSoup(r.text, "html.parser")
    atendimento = re.search(r"ATENDIMENTO:\s*([\d\-]+)", soup.get_text(" ", strip=True))
    resultado = ResultadoPortal("ultramedical", detalhes={"atendimento": atendimento.group(1) if atendimento else ""})

    grid = soup.find(id=re.compile("GV_Pacientes"))
    for tr in grid.find_all("tr")[1:] if grid else []:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) >= 4 and tds[2]:
            resultado.itens.append({"data": tds[1], "descricao": tds[2], "status": tds[3]})

    if baixar and any(i["status"].lower().startswith("dispon") for i in resultado.itens):
        dados = {k: v for k, v in _inputs(soup.find("form")).items() if k.startswith("__")}
        dados["__EVENTTARGET"] = "ctl00$ContentPlaceHolderNavegacao$LBT_PacientesVisualizarTodos"
        dados["__EVENTARGUMENT"] = ""
        r = s.post(ULTRA_PACIENTE, data=dados, timeout=TIMEOUT)
        m = re.search(r'DowloadFileUri\(\s*"([A-Za-z0-9+/=]+)"', r.text)
        if not m:
            raise PortalErro("Ultramedical: o portal não devolveu o PDF dos laudos.")
        pdf = base64.b64decode(m.group(1))
        if not pdf.startswith(b"%PDF"):
            raise PortalErro("Ultramedical: arquivo recebido não é PDF.")
        num = resultado.detalhes["atendimento"] or "laudos"
        resultado.laudos.append(Laudo(f"Ultramedical — atendimento {num}", f"ultramedical_{num}.pdf", pdf))
    return resultado


# ---------------------------------------------------------------------------
# Sodré (toxicológico)
# ---------------------------------------------------------------------------

def _sodre_login(s, cpf, senha):
    r = s.get(SODRE_RESULTADOS, timeout=TIMEOUT)
    form = BeautifulSoup(r.text, "html.parser").find("form", id="kc-form-login")
    if not form:
        raise PortalErro("Sodré: página de login mudou (formulário não encontrado).")
    dados = _inputs(form, tipos=(None, "hidden", "text", "password", "checkbox"))
    dados.update(username=cpf_com_mascara(cpf), password=senha)
    dados.pop("rememberMe", None)
    r = s.post(form["action"], data=dados, timeout=TIMEOUT)
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    if not form or "signin-oidc" not in (form.get("action") or ""):
        erro = soup.select_one("#input-error, .kc-feedback-text, .alert-error")
        raise PortalErro("Sodré: login recusado" + (f" ({erro.get_text(' ', strip=True)})" if erro else "") + ".")
    r = s.post(form["action"], data=_inputs(form), timeout=TIMEOUT)
    if "Meus Laudos" not in r.text:
        raise PortalErro("Sodré: não foi possível abrir a página de resultados.")
    return r.text


def _verdadeiro(valor):
    return valor is True or str(valor).strip().lower() in ("true", "1", "sim")


def sodre_buscar(cpf, senha, baixar=True):
    s = _sessao()
    html = _sodre_login(s, cpf, senha)
    rt = re.search(r"setRefreshTokenAsync\(\s*['\"]([^'\"]+)", html)
    token = s.post(f"{SODRE_BASE}/Token", data={"rt": rt.group(1) if rt else ""}, timeout=TIMEOUT).json()
    if not token.get("sucesso"):
        raise PortalErro("Sodré: não foi possível obter o token de acesso.")
    cabecalho = {"Authorization": f"Bearer {token['objeto']['accessToken']}"}

    resultado = ResultadoPortal("sodre")
    soup = BeautifulSoup(html, "html.parser")
    antiforgery = soup.find("input", {"name": "__RequestVerificationToken"})
    for h3 in soup.select('h3[onclick*="BuscarDetalhesDoExameAsync"]'):
        cid = h3.get("id")
        info = h3.select_one("span.info").get_text(" ", strip=True)  # "N° OS - 2606000731 - 29/10/2026"
        partes = [p.strip() for p in info.split(" - ")]
        os_num, data_os = (partes[1], partes[2]) if len(partes) >= 3 else (info, "")
        r = s.get(f"{SODRE_BASE}/API/Exame/GetDetalhesDoExame/{cid}", headers=cabecalho, timeout=TIMEOUT)
        obj = (r.json() or {}).get("objeto") or {}
        etapas = [
            {"procedimento": e.get("procedimento"), "data": e.get("dtProcedimento"), "hora": e.get("hrProcedimento"),
             "ocorrencia": e.get("observacao") == "EM_OCORRENCIA"}
            for e in obj.get("rastreabilidade") or []
        ]
        liberado = any(e["procedimento"] == "AMOSTRA ASSINADA" for e in etapas)
        resultado.itens.append({
            "data": data_os,
            "descricao": f"Toxicológico — OS {os_num}",
            "status": "Laudo liberado" if liberado else (etapas[-1]["procedimento"].title() if etapas else "Sem andamento"),
            "os": os_num,
        })
        resultado.detalhes[os_num] = {
            "laudo": obj.get("laudo"), "validade": (obj.get("validadeExame") or "")[:10],
            "resultado_amostra": obj.get("resultadoAmostra"), "etapas": etapas,
        }
        if not (baixar and liberado):
            continue
        for laudo in obj.get("laudos") or []:
            if _verdadeiro(laudo.get("eRevisor")) or _verdadeiro(laudo.get("eContraProva")):
                continue
            dados = {"codLaudo": cid, "codTriagem": laudo.get("codTriagemLoteItemAssinaturaCrypto", "")}
            if antiforgery:
                dados["__RequestVerificationToken"] = antiforgery.get("value", "")
            r = s.post(f"{SODRE_BASE}/minha-conta/baixarLaudo", data=dados, timeout=TIMEOUT)
            if not r.content.startswith(b"%PDF"):
                raise PortalErro("Sodré: o portal não devolveu o PDF do laudo.")
            resultado.laudos.append(Laudo(f"Toxicológico — OS {os_num}", f"toxicologico_{os_num}.pdf", r.content))
    return resultado


# ---------------------------------------------------------------------------
# SUS — LABCEM / Prefeitura de Campo Grande (sistema Net, da Matrix)
# ---------------------------------------------------------------------------

def _data_br(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) >= 10 else ""


def sus_buscar(usuario, senha, baixar=True, desde_dias=120):
    """Usuário e senha vêm na etiqueta entregue na coleta. Só considera pedidos recentes."""
    s = _sessao()
    soup = BeautifulSoup(s.get(SUS_BASE + "/wfrmLogin.aspx", timeout=TIMEOUT).text, "html.parser")
    form = soup.find("form")
    if not form or not form.find("input", {"name": "userLogin"}):
        raise PortalErro("SUS: página de login mudou (formulário não encontrado).")
    dados = _inputs(form)
    dados.update(userLogin=str(usuario).strip(), userPassword=str(senha).strip(), acceptCookie="true")
    r = s.post(SUS_BASE + "/wfrmLogin.aspx", data=dados, timeout=TIMEOUT)
    if "wfrmLogin.aspx" in r.url:
        raise PortalErro("SUS: login recusado. Confira usuário e senha da etiqueta nos secrets.")
    token = s.get(SUS_BASE + "/wfrmLogin.aspx/ValidaToken",
                  headers={"Content-Type": "application/json", "X-Authenticate": ""}, timeout=TIMEOUT).json().get("d")
    if not token:
        raise PortalErro("SUS: não foi possível obter o token de acesso.")
    r = s.get(SUS_BASE + "/api/resultados", params={"resultadosRecentes": "True"},
              headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    pedidos = (r.json() or {}).get("pedidos") or []

    limite = (datetime.now() - timedelta(days=desde_dias)).strftime("%Y-%m-%d")
    resultado = ResultadoPortal("sus")
    for p in pedidos:
        if (p.get("dataPedido") or "")[:10] < limite:
            continue
        prontos = []
        for proc in p.get("procedimentos") or []:
            # Depois de aberto, o status muda de "Pronto" para "Visto"/"Impresso"; vale a data de liberação.
            situacao = (proc.get("statusDescricao") or "").lower()
            pronto = bool(proc.get("dataLiberacao")) and "cancel" not in situacao and "aguard" not in situacao
            resultado.itens.append({
                "data": _data_br(proc.get("dataColeta")),
                "descricao": proc.get("nome", ""),
                "status": "Pronto" if pronto else (proc.get("statusDescricao") or "").capitalize(),
                "pedido": p.get("pedido"),
                "previsao": _data_br(proc.get("previsaoEntrega")),
            })
            if pronto and proc.get("permiteExibirInternet") == 1:
                prontos.append(str(proc["seqProcedimento"]))
        if not (baixar and prontos):
            continue
        r = s.post(SUS_BASE + "/wfrmLaudo.aspx", timeout=TIMEOUT, data={
            "txtNumeroPedido": p["pedidoCript"],  # muda a cada sessão
            "txtMedico": p.get("solicitante", ""),
            "txtTipoLaudo": "PDF",
            "txtMarcaImpresso": "1",
            "txtProcedimentos": ";".join(prontos),
        })
        if not r.content.startswith(b"%PDF"):
            raise PortalErro(f"SUS: o portal não devolveu o PDF do pedido {p.get('pedido')}.")
        resultado.laudos.append(Laudo(f"SUS (LABCEM) — pedido {p.get('pedido')}", f"sus_{p.get('pedido')}.pdf", r.content))
    return resultado
