#!/usr/bin/env python3
"""Plantão Coroado News: monitoramento de feeds públicos, sem invenção de fatos."""
import datetime as dt
import html
import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "eleicoes-boletins.json"
SOURCES = [
    ("TSE — notícias oficiais", "https://www.tse.jus.br/comunicacao/noticias/RSS"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("G1 Amazonas", "https://g1.globo.com/rss/g1/am/amazonas/"),
    ("G1 Política", "https://g1.globo.com/rss/g1/politica/"),
    ("Agência Brasil — geral", "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml"),
    ("Rios de Notícias — Amazonas", "https://www.riosdenoticias.com.br/feed/"),
    ("D24AM — Amazonas", "https://d24am.com/feed/"),
    ("Portal do Holanda — Amazonas", "https://www.portaldoholanda.com.br/rss.xml"),
    ("A Crítica — Amazonas", "https://www.acritica.com/rss"),
    ("BNC Amazonas", "https://bncamazonas.com.br/feed/"),
]
LOCAL_SOURCES = ("Amazonas", "Rios de Notícias", "D24AM", "Portal do Holanda", "A Crítica", "BNC Amazonas", "TRE-AM")
LOCAL_PATTERN = re.compile(r"eleiç|eleitor|apuraç|votaç|urnas?|tse|tre.am|segundo turno|governador|omar aziz|maria do carmo|boca de urna|seções eleitorais",re.I)
PATTERN = re.compile(r"eleiç|eleitor|apuraç|votaç|urnas?|tse|tre-am|segundo turno|presiden|governador|governo do amazonas|amazonas|manaus|tre.am|segundo turno", re.I)
NS = {"a": "http://www.w3.org/2005/Atom"}
NOW = dt.datetime.now(dt.timezone.utc)

def get_text(el, tag):
    node = el.find(tag)
    return (node.text or "").strip() if node is not None else ""

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", s or ""))).strip()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CoroadoNews24h/1.0 (news monitoring)"})
    with urllib.request.urlopen(req, timeout=18) as response:
        return response.read(2_000_000)

def media(item):
    """Coleta imagem ou vídeo explícito do feed, sem inventar URLs."""
    ns_media="{http://search.yahoo.com/mrss/}"
    imgs=[]; video=""
    for node in item.iter():
        tag=node.tag
        if tag in (ns_media+"content",ns_media+"thumbnail","enclosure"):
            url=node.get("url","").strip()
            typ=node.get("type","").lower()
            if not url.startswith("https://"): continue
            if "video" in typ or re.search(r"\\.(mp4|webm)(?:\\?|$)",url,re.I):
                if not video: video=url
            elif "image" in typ or re.search(r"\\.(jpg|jpeg|png|webp)(?:\\?|$)",url,re.I):
                if url not in imgs: imgs.append(url)
    return imgs[:2],video

def entries(xml):
    root = ET.fromstring(xml)
    result = []
    for item in root.findall(".//item"):
        result.append((get_text(item,"title"),get_text(item,"link"),get_text(item,"description"),get_text(item,"pubDate"),*media(item)))
    for item in root.findall(".//a:entry",NS):
        link = item.find("a:link",NS)
        result.append((get_text(item,"a:title"),link.get("href","") if link is not None else "",get_text(item,"a:summary") or get_text(item,"a:content"),get_text(item,"a:updated") or get_text(item,"a:published"),*media(item)))
    return result

def recent(s):
    try:
        t=parsedate_to_datetime(s) if "," in s else dt.datetime.fromisoformat(s.replace("Z","+00:00"))
        if t.tzinfo is None: t=t.replace(tzinfo=dt.timezone.utc)
        return dt.timedelta(0)<=NOW-t.astimezone(dt.timezone.utc)<=dt.timedelta(hours=30)
    except Exception:
        return False

def main():
    data=json.loads(FILE.read_text(encoding="utf-8"))
    items=data.setdefault("boletins",[])
    seen={str(x.get("fonteUrl","")).strip() for x in items}
    order=max([int(x.get("ordemPublicacao",0)) for x in items] or [0])
    added=[]
    for name,url in SOURCES:
        try:
            feed=entries(fetch(url))
        except Exception as exc:
            print(f"Fonte indisponível {name}: {exc}")
            continue
        for title,link,summary,published,images,video in feed:
            title=clean(title);summary=clean(summary);link=link.strip()
            match = LOCAL_PATTERN if any(word in name for word in LOCAL_SOURCES) else PATTERN
            if not (title and link and published and recent(published) and match.search(title+" "+summary)):
                continue
            if link in seen or not link.startswith("https://"):
                continue
            # Feeds podem chegar truncados mesmo abaixo do limite de 420 caracteres.
            # Publicar somente frases completas; caso contrário, descartar o resumo.
            trecho=summary[:420].strip()
            finais=[m.end() for m in re.finditer(r'[.!?…](?:["”’ )\]]*)(?=\s|$)',trecho)]
            summary=trecho[:finais[-1]].strip() if finais and finais[-1]>=45 else ""
            if len(summary)<45:
                continue
            order+=1
            local=NOW.astimezone(dt.timezone(dt.timedelta(hours=-4)))
            bulletin={"titulo":title,"texto":"Segundo "+name+": "+summary,"horario":local.strftime("%d/%m/%Y • atualização automática às %Hh%M (Manaus)"),"dataPublicacao":local.strftime("%d/%m/%Y"),"horaPublicacao":local.strftime("%Hh%M (Manaus)"),"fonteNome":name,"fonteUrl":link,"ordemPublicacao":order}
            if images:
                bulletin["imagemUrl"]=images[0]
                bulletin["imagens"]=[{"url":u,"alt":title,"credito":name} for u in images]
            if video:
                bulletin["videoUrl"]=video
                bulletin["videoCredito"]=name
            added.append(bulletin)
            seen.add(link)
            if len(added)>=8: break
        if len(added)>=8: break
    if added:
        data["boletins"]=list(reversed(added))+items
        data["atualizadoEm"]=NOW.isoformat()
        FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Boletins novos: {len(added)}; fontes consultadas: {len(SOURCES)}")

if __name__=="__main__":
    main()
