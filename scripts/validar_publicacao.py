#!/usr/bin/env python3
"""Offline publication checks. Does not certify editorial accuracy or external services."""
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
errors = []

def fail(message):
    errors.append(message)

def local_file(value, context):
    if not isinstance(value, str) or not value.strip():
        fail(f"{context}: caminho vazio")
        return
    parsed = urlsplit(value)
    if parsed.scheme in ("http", "https", "data", "mailto", "tel") or parsed.netloc:
        return
    if parsed.scheme:
        fail(f"{context}: protocolo inválido")
        return
    path = (ROOT / unquote(parsed.path).lstrip("/")).resolve()
    if path.is_dir():
        path = path / "index.html"
    if not path.is_relative_to(ROOT) or not path.is_file():
        fail(f"{context}: arquivo local ausente: {value}")
        return
    if path.suffix.lower() == ".png":
        data = path.read_bytes()
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            fail(f"{context}: PNG inválido")
        elif not all(struct.unpack(">II", data[16:24])):
            fail(f"{context}: PNG sem dimensões")

try:
    news = json.loads((ROOT / "noticias.json").read_text())
except (OSError, ValueError) as exc:
    sys.exit(f"noticias.json inválido: {exc}")
if not isinstance(news, list) or not news:
    sys.exit("noticias.json precisa ser uma lista não vazia")
seen = set()
for item in news:
    if not isinstance(item, dict):
        fail("Notícia precisa ser um objeto")
        continue
    ident = item.get("id")
    label = f"Notícia {ident}"
    if not isinstance(ident, int) or isinstance(ident, bool) or ident in seen:
        fail(f"{label}: ID inválido ou duplicado")
    else:
        seen.add(ident)
    for key in ("titulo", "categoria", "data", "imagem"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            fail(f"{label}: campo {key} ausente")
    if not isinstance(item.get("corpo"), list) or not item["corpo"]:
        fail(f"{label}: corpo ausente")
    if item.get("url") != f"noticia.html?id={ident}":
        fail(f"{label}: link não corresponde ao ID")
    if re.search(r"noticia-\d+-original-20261019\.png", str(item.get("imagem", ""))):
        fail(f"{label}: captura de celular rejeitada; usar a foto revisada")
    for key in ("imagem", "imagemFallback", "mapaBairros"):
        if item.get(key):
            local_file(item[key], f"{label}/{key}")
    videos = item.get("videos", [item["video"]] if item.get("video") else [])
    if not isinstance(videos, list):
        fail(f"{label}: vídeos precisam ser uma lista")
    else:
        for video in videos:
            if not isinstance(video, dict) or video.get("tipo") not in ("mp4", "youtube", "instagram"):
                fail(f"{label}: formato de vídeo inválido")
            elif video.get("tipo") == "mp4":
                local_file(video.get("url"), f"{label}/vídeo")

home = (ROOT / "index.html").read_text()
start = home.find("const fallback=")
end = home.find("let noticias=fallback", start)
if start < 0 or end < 0:
    fail("Não foi possível conferir os dados de reserva da página inicial")
else:
    try:
        embedded = json.loads(home[start + len("const fallback="):end].strip().rstrip(";").strip())
        if embedded != news:
            fail("Página inicial e noticias.json têm dados diferentes")
    except ValueError:
        fail("Dados de reserva da página inicial são inválidos")

for html in ROOT.glob("*.html"):
    source = html.read_text()
    for value in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', source):
        if any(marker in value for marker in ("${", "+", "<")):
            continue
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        local_file(value, html.name)
    for attrs, code in re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", source, re.I):
        if not code.strip() or re.search(r'type=["\'](?:application/ld\+json|application/json|importmap)["\']', attrs, re.I):
            continue
        result = subprocess.run(
            ["node", "--check", "--input-type=" + ("module" if re.search(r'type=["\']module["\']', attrs) else "commonjs")],
            input=code, text=True, capture_output=True
        )
        if result.returncode:
            fail(f"{html.name}: JavaScript inválido: {result.stderr[:500]}")

if (ROOT / "CNAME").read_text().strip() != "coroadonews24h.com.br":
    fail("CNAME diferente do domínio esperado")
if errors:
    print("\n".join("ERRO: " + message for message in errors))
    sys.exit(1)
print(f"Validação concluída: {len(news)} notícias; arquivos locais, links, dados e sintaxe consistentes.")
print("A correspondência visual das fotos e a reprodução externa exigem conferência no navegador.")
