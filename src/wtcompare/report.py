"""Export als HTML-Bericht (filterbar, eigenständige Datei) und CSV (für Excel, mit ';' getrennt)."""

from __future__ import annotations

import csv
import html
import io
import json


def csv_bytes(res: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Typ", "WikiTree-ID", "WikiTree-Person", "GEDCOM-ID", "GEDCOM-Person", "Watchlist",
                "Kategorie", "Status", "Wert GEDCOM", "Wert WikiTree", "Hinweis"])
    for p in res["persons"]:
        for f in p["f"]:
            w.writerow(["Vergleich", p["w"], p["wname"], p["g"], p["gname"], "ja" if p["watch"] else "nein",
                        f["kat"], f["status"], f["ged"], f["wt"], f["hinweis"]])
    for m in res["missing"]:
        w.writerow(["Fehlende Person", m["wid"], "", m["g"], m["who"], "", m["rel"], m["status"], "", "", ""])
    for u in res["unmatched"]:
        w.writerow(["Ohne Zuordnung", u["w"], u["wname"], "",
                    "; ".join(f"{c['name']} [{c['g']}] {c['s']}" for c in u["cands"]),
                    "ja", "", "nicht zugeordnet", "", "", ""])
    return buf.getvalue().encode("utf-8-sig")


def html_bytes(res: dict) -> bytes:
    data = json.dumps(res, ensure_ascii=False).replace("</", "<\\/")
    tpl = HTML_TEMPLATE.replace("__DATA__", data).replace("__TITLE__", html.escape(res["meta"]["title"]))
    return tpl.encode("utf-8")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e2dd;--bad:#c0392b;--warn:#b7791f;--info:#2b6cb0;--ok:#2f855a;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root{--bg:#171716;--card:#21211f;--ink:#ecebe6;--mute:#a09f98;--line:#363532;--bad:#ef6f61;--warn:#e0a84a;--info:#6aa6e8;--ok:#5fbf8a;--chip:#2c2c29}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:18px;margin:0 0 4px}.meta{color:var(--mute);font-size:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-top:10px}
.bar input[type=search]{flex:1 1 220px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
.bar label{font-size:13px;white-space:nowrap}
nav{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}nav button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;cursor:pointer}
nav button.on{background:var(--ink);color:var(--bg)}
main{padding:16px;max-width:1200px;margin:0 auto}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px}.stat b{font-size:18px;display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.card h3{margin:0;font-size:14px;padding:10px 12px;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;border-bottom:1px solid var(--line)}
.card h3 small{color:var(--mute);font-weight:400}
a{color:var(--info)}table{width:100%;border-collapse:collapse}td,th{padding:6px 12px;text-align:left;vertical-align:top;border-top:1px solid var(--line)}
th{font-size:12px;color:var(--mute);font-weight:500}tr:first-child td{border-top:0}
.s{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--chip);white-space:nowrap}
.s-abweichend{color:var(--bad)}.s-nur,.s-fehlt{color:var(--warn)}.s-genauer{color:var(--info)}.s-gleich{color:var(--ok)}
.hint{color:var(--mute);font-size:12px}.tbl{overflow-x:auto}
.wl{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 5px;color:var(--mute)}
.empty{color:var(--mute);padding:20px;text-align:center}
</style></head><body>
<header><h1>__TITLE__</h1><div class="meta" id="meta"></div>
<nav id="tabs"><button data-t="p" class="on">Vergleich</button><button data-t="m">Fehlende Personen</button><button data-t="u">Ohne Zuordnung</button></nav>
<div class="bar"><input type="search" id="q" placeholder="Name, WikiTree-ID oder GEDCOM-ID suchen …">
<label><input type="checkbox" id="onlyDiff" checked> nur Unterschiede</label>
<label><input type="checkbox" id="hideSimilar" checked> „ähnlich“ ausblenden</label>
<label><input type="checkbox" id="onlyWl" checked> nur Watchlist</label></div></header>
<main><div class="stats" id="stats"></div><div id="out"></div></main>
<script>
const D=__DATA__;const $=s=>document.querySelector(s);let tab="p";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const wtLink=id=>`<a href="https://www.wikitree.com/wiki/${encodeURIComponent(id)}" target="_blank" rel="noopener">${esc(id)}</a>`;
const cls=s=>"s s-"+s.split(" ")[0];
$("#meta").textContent=D.meta.info;
document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{tab=b.dataset.t;document.querySelectorAll("#tabs button").forEach(x=>x.classList.toggle("on",x===b));render()});
["#q","#onlyDiff","#hideSimilar","#onlyWl"].forEach(s=>$(s).addEventListener("input",render));
function keep(f){if($("#onlyDiff").checked&&f.status==="gleich")return false;if($("#hideSimilar").checked&&f.status==="ähnlich")return false;return true}
function render(){const q=$("#q").value.toLowerCase().trim();const out=$("#out");
 const P=D.persons.filter(p=>!$("#onlyWl").checked||p.watch);
 const nd=P.reduce((a,p)=>a+p.f.filter(f=>f.status==="abweichend").length,0);
 $("#stats").innerHTML=`<div class="stat"><b>${P.length}</b>zugeordnete Personen</div><div class="stat"><b>${nd}</b>Abweichungen</div><div class="stat"><b>${D.missing.filter(m=>m.status==="fehlt auf WikiTree").length}</b>fehlen auf WikiTree</div><div class="stat"><b>${D.missing.filter(m=>m.status==="fehlt in GEDCOM").length}</b>fehlen in GEDCOM</div><div class="stat"><b>${D.unmatched.length}</b>Watchlist ohne Zuordnung</div>`;
 if(tab==="p"){let h="";P.slice().sort((a,b)=>b.score-a.score).forEach(p=>{
   if(q&&!(p.gname+p.wname+p.w+p.g).toLowerCase().includes(q))return;
   const fs=p.f.filter(keep);if(!fs.length&&$("#onlyDiff").checked)return;
   h+=`<div class="card"><h3>${wtLink(p.w)} ${esc(p.wname)} ${p.watch?'<span class="wl">Watchlist</span>':''}<small>GEDCOM ${esc(p.g)}: ${esc(p.gname)} · ${esc(p.how)}</small></h3><div class="tbl"><table><tr><th>Feld</th><th>Status</th><th>GEDCOM</th><th>WikiTree</th><th>Hinweis</th></tr>`+
   fs.map(f=>`<tr><td>${esc(f.kat)}</td><td><span class="${cls(f.status)}">${esc(f.status)}</span></td><td>${esc(f.ged)}</td><td>${esc(f.wt)}</td><td class="hint">${esc(f.hinweis)}</td></tr>`).join("")+`</table></div></div>`});
   out.innerHTML=h||'<div class="empty">Keine Einträge für diesen Filter.</div>'}
 else if(tab==="m"){const M=D.missing.filter(m=>!q||(m.who+m.rel+m.wid+m.g).toLowerCase().includes(q));
   out.innerHTML=M.length?`<div class="card"><div class="tbl"><table><tr><th>Status</th><th>Person</th><th>Beziehung</th><th>WikiTree</th><th>GEDCOM</th></tr>`+M.map(m=>`<tr><td><span class="${cls(m.status)}">${esc(m.status)}</span></td><td>${esc(m.who)}</td><td>${esc(m.rel)}</td><td>${wtLink(m.wid)}</td><td>${esc(m.g)}</td></tr>`).join("")+`</table></div></div>`:'<div class="empty">Keine fehlenden Personen gefunden.</div>'}
 else{const U=D.unmatched.filter(u=>!q||(u.w+u.wname).toLowerCase().includes(q));
   out.innerHTML=U.length?`<div class="card"><div class="tbl"><table><tr><th>WikiTree</th><th>Person</th><th>Beste GEDCOM-Kandidaten</th></tr>`+U.map(u=>`<tr><td>${wtLink(u.w)}</td><td>${esc(u.wname)}</td><td>${u.cands.length?u.cands.map(c=>`${esc(c.name)} <span class="hint">[${esc(c.g)}] ${c.s}</span>`).join("<br>"):'<span class="hint">kein Kandidat</span>'}</td></tr>`).join("")+`</table></div></div>`:'<div class="empty">Alle Watchlist-Profile wurden zugeordnet.</div>'}}
render();
</script></body></html>
"""
