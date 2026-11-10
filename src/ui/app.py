"""Flet-Oberfläche: Projekte, Einrichten, Ergebnis, Verlauf."""

from __future__ import annotations

import re
import threading
import traceback
from datetime import datetime
from pathlib import Path

import flet as ft

from wtcompare.profile import as_text
from wtcompare.project import Project, ProjectStore
from wtcompare.report import csv_bytes, html_bytes
from wtcompare.rundiff import diff_runs
from wtcompare.textutil import norm
from wtcompare.wikitree import Cancelled, WikiTree

from .widgets import hint, section, stat, status_chip

PAGE_SIZE = 60
WT_ID_RX = re.compile(r"^[^\s-][^\s]*-\d+$")


def _fmt_ts(iso: str, seconds: bool = False) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M" + (":%S" if seconds else ""))
    except (TypeError, ValueError):
        return iso or "–"


class App:
    def __init__(self, page: ft.Page, data_dir: Path):
        self.page = page
        self.store = ProjectStore(data_dir)
        self.project: Project | None = None
        self.wt: WikiTree | None = None
        self.result: dict | None = None
        self.online = True
        self.busy = False
        self.cancel = threading.Event()
        self.pending_mapping = False
        self.file_picker = ft.FilePicker()   # Dienst: Referenz halten, sonst wird er abgemeldet
        self.url_launcher = ft.UrlLauncher()
        self.clipboard = ft.Clipboard()

        # Ergebnis-Filter
        self.res_tab = "p"
        self.res_query = ""
        self.only_diff = True
        self.hide_similar = True
        self.only_wl = True
        self.res_limit = PAGE_SIZE

        self.body = ft.Container(expand=True)
        self.nav = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.FOLDER, label="Projekte"),
                ft.NavigationBarDestination(icon=ft.Icons.TUNE, label="Einrichten"),
                ft.NavigationBarDestination(icon=ft.Icons.FACT_CHECK, label="Ergebnis"),
                ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label="Verlauf"),
            ],
            on_change=lambda e: self.show(e.control.selected_index),
        )
        page.navigation_bar = self.nav
        page.appbar = ft.AppBar(title=ft.Text("WikiTree <-> GEDCOM"))
        page.add(ft.SafeArea(self.body, expand=True))
        projects = self.store.list()
        if len(projects) == 1:
            self.open_project(projects[0], go=False)
        self.show(1 if self.project else 0)

    # ================================================================ Allgemein
    def show(self, idx: int):
        if idx > 0 and not self.project:
            self.toast("Bitte zuerst ein Projekt wählen oder anlegen.")
            idx = 0
        self.nav.selected_index = idx
        builder = [self.view_projects, self.view_setup, self.view_result, self.view_history][idx]
        try:
            self.body.content = builder()
        except Exception as ex:  # Anzeige-Fehler nicht die ganze App abstürzen lassen
            traceback.print_exc()
            self.body.content = ft.Text(f"Fehler beim Anzeigen: {ex}", color=ft.Colors.ERROR)
        self.page.appbar.title = ft.Text(self.project.settings.name if self.project else "WikiTree <-> GEDCOM")
        self.page.update()

    def refresh(self):
        self.show(self.nav.selected_index or 0)

    def toast(self, msg: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(msg), show_close_icon=True))

    def open_url(self, url: str):
        self.page.run_task(self.url_launcher.launch_url, url)

    def wt_link(self, wtid: str) -> ft.Control:
        return ft.TextButton(wtid, icon=ft.Icons.OPEN_IN_NEW,
                             on_click=lambda e: self.open_url(f"https://www.wikitree.com/wiki/{wtid}"))

    def run_bg(self, job, done=None, label="Arbeite …"):
        """Lange Arbeiten im Hintergrund-Thread; Fortschritt landet in self.log_text."""
        if self.busy:
            self.toast("Es läuft bereits ein Vorgang.")
            return
        self.busy = True
        self.cancel.clear()
        self.log(label)

        def runner():
            try:
                out = job()
                if done:
                    done(out)
            except Cancelled:
                self.log("Abgebrochen.")
                self.toast("Abgebrochen.")
            except Exception as ex:  # Fehler anzeigen statt abstürzen
                traceback.print_exc()
                self.log(f"Fehler: {ex}")
                self.toast(f"Fehler: {ex}")
            finally:
                self.busy = False
                self.refresh()

        self.refresh()
        self.page.run_thread(runner)

    _log_lines: list[str] = []

    def log(self, line: str):
        self._log_lines = (self._log_lines + [line])[-6:]
        if getattr(self, "log_text", None) is not None:
            self.log_text.value = "\n".join(self._log_lines)
            try:
                self.log_text.update()
            except Exception:
                pass
        if line.startswith("WikiTree meldet HTTP"):
            self.toast(line)

    # ================================================================ Projekte
    def open_project(self, p: Project, go=True):
        old = self.wt
        self.project = p
        self.result = None
        self.pending_mapping = False
        self.wt = p.wikitree(offline=not self.online, log=self.log, cancel=self.cancel)
        if old and old.logged_in:   # Anmeldung bleibt beim Projektwechsel erhalten
            self.wt.session, self.wt.user = old.session, old.user
        runs = p.runs()
        if runs:
            try:
                self.result = p.load_run(runs[0])
            except Exception:
                self.result = None
        if go:
            self.show(1)

    def view_projects(self):
        name = ft.TextField(label="Name für neues Projekt", expand=True, on_submit=lambda e: create(e))

        def create(e):
            p = self.store.create(name.value or "Projekt")
            self.open_project(p)

        def rename(p):
            tf = ft.TextField(value=p.settings.name, autofocus=True)

            def ok(e):
                self.store.rename(p, tf.value)
                self.page.pop_dialog()
                self.refresh()
            self.page.show_dialog(ft.AlertDialog(title=ft.Text("Projekt umbenennen"), content=tf, actions=[
                ft.TextButton("Abbrechen", on_click=lambda e: self.page.pop_dialog()),
                ft.FilledButton("Speichern", on_click=ok)]))

        def delete(p):
            def ok(e):
                if self.project and self.project.dir == p.dir:
                    self.project, self.wt, self.result = None, None, None
                self.store.delete(p)
                self.page.pop_dialog()
                self.refresh()
            self.page.show_dialog(ft.AlertDialog(
                title=ft.Text("Projekt löschen?"),
                content=ft.Text(f"„{p.settings.name}“ mit GEDCOM-Kopie, WikiTree-Cache, Zuordnungen und allen "
                                "gespeicherten Läufen wird gelöscht."),
                actions=[ft.TextButton("Abbrechen", on_click=lambda e: self.page.pop_dialog()),
                         ft.FilledButton("Löschen", on_click=ok)]))

        tiles = []
        for p in self.store.list():
            s = p.settings
            runs = p.runs()
            sub = " · ".join(x for x in [s.gedcom_name or "keine GEDCOM",
                                          f"Start {s.wt_start}" if s.wt_start else "",
                                          f"{len(runs)} Läufe" if runs else ""] if x)
            tiles.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.FOLDER),
                title=ft.Text(s.name, weight=ft.FontWeight.BOLD if self.project and p.dir == self.project.dir else None),
                subtitle=ft.Text(sub),
                selected=bool(self.project and p.dir == self.project.dir),
                on_click=lambda e, p=p: self.open_project(p),
                trailing=ft.Row([ft.IconButton(ft.Icons.EDIT, tooltip="Umbenennen", on_click=lambda e, p=p: rename(p)),
                                 ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Löschen",
                                               on_click=lambda e, p=p: delete(p))], tight=True, spacing=0),
            ))
        return ft.ListView([
            section("Neues Projekt",
                    ft.Row([name, ft.FilledButton("Anlegen", icon=ft.Icons.ADD, on_click=create)]),
                    subtitle="Ein Projekt = eine GEDCOM, ein Startpaar, eigene Zuordnungen und Läufe."),
            section("Projekte", *(tiles or [hint("Noch keine Projekte.")])),
        ], padding=12, spacing=8, expand=True)

    # ================================================================ Einrichten
    def view_setup(self):
        p, s, wt = self.project, self.project.settings, self.wt
        self.log_text = ft.Text("\n".join(self._log_lines), size=12, selectable=True)

        # --- GEDCOM
        async def pick_gedcom(e):
            files = await self.file_picker.pick_files(
                dialog_title="GEDCOM-Datei wählen", file_type=ft.FilePickerFileType.ANY,
                with_data=self.page.web or self.page.platform.is_mobile())
            if not files:
                return
            f = files[0]

            def job():
                data = f.bytes if f.bytes is not None else Path(f.path).read_bytes()
                self.log(f"GEDCOM lesen: {f.name} ({len(data) // 1024} KB)")
                p.set_gedcom(data, f.name)
                g = p.gedcom()
                if s.ged_start and s.ged_start not in g.indi:
                    s.ged_start = ""
                    p.save()
                return g
            self.run_bg(job, lambda g: self.log(f"GEDCOM geladen: {len(g.indi)} Personen, {len(g.fam)} Familien"),
                        "GEDCOM wird eingelesen …")

        ged_info = (f"{s.gedcom_name} · eingelesen {_fmt_ts(s.gedcom_loaded)}" if p.has_gedcom
                    else "Noch keine GEDCOM-Datei geladen.")
        ged_sec = section("1 · GEDCOM", hint(ged_info),
                          ft.Button("GEDCOM-Datei wählen …", icon=ft.Icons.FOLDER_OPEN, on_click=pick_gedcom,
                                    disabled=self.busy),
                          subtitle="Die Datei wird ins Projekt kopiert. Bei Änderungen einfach neu wählen.")

        # --- WikiTree
        email = ft.TextField(label="WikiTree E-Mail", keyboard_type=ft.KeyboardType.EMAIL, expand=True)
        pw = ft.TextField(label="Passwort", password=True, can_reveal_password=True, expand=True,
                          on_submit=lambda e: login(e))

        def login(e):
            if not email.value or not pw.value:
                self.toast("E-Mail und Passwort eingeben.")
                return
            em, pa = email.value, pw.value
            pw.value = ""
            self.run_bg(lambda: wt.login(em, pa), lambda u: self.log(f"Angemeldet als {u}"), "Anmelden …")

        def refresh_wl(e):
            def job():
                try:
                    p.refresh_wikitree(wt, log=self.log)
                except Exception:
                    # Cache unverändert lassen: Daten neu von der Festplatte laden
                    fresh = p.wikitree(offline=not self.online, log=self.log, cancel=self.cancel)
                    fresh.session, fresh.user = wt.session, wt.user
                    self.wt = fresh
                    raise
            self.run_bg(job, label="WikiTree-Daten werden geladen …")

        def set_online(e):
            self.online = e.control.value
            wt.offline = not self.online

        cache_info = (f"Cache vom {_fmt_ts(wt.saved)}: {len(wt.watchlist)} Watchlist-Profile, {len(wt.people)} Profile"
                      if wt.saved else "Noch keine WikiTree-Daten geladen.")
        wt_controls = [hint(cache_info)]
        if wt.logged_in:
            wt_controls += [ft.Text(f"Angemeldet als {wt.user}"),
                            ft.Row([ft.Button("Watchlist laden / aktualisieren", icon=ft.Icons.SYNC,
                                              on_click=refresh_wl, disabled=self.busy),
                                    ft.TextButton("Abmelden", on_click=lambda e: (wt.logout(), self.refresh()))],
                                   wrap=True)]
        else:
            wt_controls += [ft.Row([email, pw], wrap=False),
                            ft.Button("Anmelden", icon=ft.Icons.LOGIN, on_click=login, disabled=self.busy),
                            hint("Die Watchlist kann nur mit Anmeldung geladen werden. Passwort und E-Mail werden "
                                 "nicht gespeichert.")]
        wt_controls.append(ft.Switch(label="Fehlendes online nachladen", value=self.online,
                                     on_change=set_online))
        wt_sec = section("2 · WikiTree", *wt_controls)

        # --- Startpaar
        start_sec = self._start_section()

        # --- Einstellungen
        th_label = ft.Text(f"Mindest-Ähnlichkeit für Zuordnung: {s.threshold:.2f}")

        def th_change(e):
            th_label.value = f"Mindest-Ähnlichkeit für Zuordnung: {e.control.value:.2f}"
            th_label.update()

        def th_end(e):
            s.threshold = round(e.control.value, 2)
            p.save()

        def exp_change(e):
            s.expand_all = e.control.value
            p.save()

        opt_sec = section(
            "4 · Einstellungen", th_label,
            ft.Slider(min=0.4, max=0.9, divisions=10, value=s.threshold, on_change=th_change, on_change_end=th_end),
            hint("Höher = strenger (weniger, aber sicherere Zuordnungen)."),
            ft.Switch(label="Über die Watchlist hinaus weiterlaufen", value=s.expand_all,
                      on_change=exp_change),
            hint("Braucht mehr Abrufe bei WikiTree."))

        # --- Manuelle Zuordnungen
        man_sec = self._mapping_section()

        # --- Lauf
        def start(e):
            self.run_bg(lambda: p.run(self.wt, log=self.log), self._run_done, "Vergleich läuft …")

        def stop(e):
            self.cancel.set()

        ready = p.has_gedcom and s.ged_start and s.wt_start
        run_sec = section(
            "5 · Vergleich",
            ft.Row([ft.FilledButton("Vergleich starten", icon=ft.Icons.PLAY_ARROW, on_click=start,
                                    disabled=self.busy or not ready),
                    ft.OutlinedButton("Abbrechen", icon=ft.Icons.STOP, on_click=stop, visible=self.busy)], wrap=True),
            ft.ProgressBar(visible=self.busy),
            self.log_text,
            *([] if ready else [hint("Dafür werden GEDCOM und Startpaar gebraucht.")]))
        return ft.ListView([ged_sec, wt_sec, start_sec, opt_sec, man_sec, run_sec], padding=12, spacing=8, expand=True)

    def _run_done(self, res):
        self.result = res
        self.pending_mapping = False
        self.res_limit = PAGE_SIZE
        self.log(f"Fertig: {len(res['persons'])} zugeordnet, {len(res['missing'])} fehlende Personen, "
                 f"{len(res['unmatched'])} ohne Zuordnung.")
        self.nav.selected_index = 2

    def _start_section(self):
        p, s, wt = self.project, self.project.settings, self.wt
        # GEDCOM-Seite
        g_cur = "–"
        if s.ged_start and p.has_gedcom:
            try:
                g_cur = f"{s.ged_start} · {p.gedcom().indi[s.ged_start].label()}"
            except (KeyError, RuntimeError):
                g_cur = s.ged_start
        g_results = ft.Column(spacing=0)
        g_query = ft.TextField(label="GEDCOM durchsuchen (Name [Jahr] oder XREF)", prefix_icon=ft.Icons.SEARCH,
                               on_submit=lambda e: g_search(e))

        def g_pick(xref):
            s.ged_start = xref
            p.save()
            self.refresh()

        def g_search(e):
            if not p.has_gedcom:
                self.toast("Zuerst eine GEDCOM-Datei wählen.")
                return
            hits = p.gedcom().search(g_query.value or "", limit=20)
            g_results.controls = [ft.ListTile(title=ft.Text(x.label()), subtitle=ft.Text(x.xref), dense=True,
                                              on_click=lambda e, x=x.xref: g_pick(x)) for _, x in hits] \
                or [hint("Keine Treffer.")]
            g_results.update()

        # WikiTree-Seite
        w_cur = s.wt_start or "–"
        if s.wt_start and s.wt_start in wt.name_to_id:
            w_cur = f"{s.wt_start} · {wt.label(wt.name_to_id[s.wt_start])}"
        w_results = ft.Column(spacing=0)
        w_query = ft.TextField(label="WikiTree: Name [Jahr] oder WikiTree-ID", prefix_icon=ft.Icons.SEARCH,
                               on_submit=lambda e: w_search(e))

        def w_pick(wtid):
            s.wt_start = wtid
            p.save()
            self.refresh()

        def tiles(ids):
            return [ft.ListTile(title=ft.Text(wt.label(i)),
                                subtitle=ft.Text(wt.wtid(i) + ("  · Watchlist" if i in wl else "")), dense=True,
                                on_click=lambda e, w=wt.wtid(i): w_pick(w)) for i in ids]

        wl = set(wt.watchlist)

        def w_search(e):
            q = (w_query.value or "").strip()
            if WT_ID_RX.match(q):
                w_results.controls = [ft.ListTile(title=ft.Text(f"WikiTree-ID {q} übernehmen"), dense=True,
                                                  leading=ft.Icon(ft.Icons.CHECK), on_click=lambda e: w_pick(q))]
            else:
                year = None
                mm = re.search(r"(\d{4})\s*$", q)
                if mm:
                    year, q = int(mm.group(1)), q[:mm.start()].strip()
                toks = norm(q).split()
                hits = []
                for i in (wt.watchlist + [x for x in wt.people if x not in wl]):
                    full = norm(f"{wt.given(i)} {wt.surname(i)} {wt.people[i].get('LastNameCurrent', '')} {wt.wtid(i)}")
                    if toks and not all(any(pt.startswith(t) for pt in full.split()) for t in toks):
                        continue
                    b = wt.date(i, "Birth")
                    if year and (b.empty or abs(b.y - year) > 2):
                        continue
                    hits.append(i)
                    if len(hits) >= 20:
                        break
                w_results.controls = tiles(hits) or [hint("Keine Treffer in den geladenen WikiTree-Daten.")]
            w_results.controls.append(ft.TextButton("Online bei WikiTree suchen", icon=ft.Icons.PERSON_SEARCH,
                                                    on_click=lambda e: w_online()))
            w_results.update()

        def w_online():
            q = (w_query.value or "").strip()
            year = None
            mm = re.search(r"(\d{4})\s*$", q)
            if mm:
                year, q = int(mm.group(1)), q[:mm.start()].strip()
            parts = q.split()
            if len(parts) < 2:
                self.toast("Für die Online-Suche Vor- und Nachnamen eingeben.")
                return
            first, last = " ".join(parts[:-1]), parts[-1]
            was_offline = wt.offline
            wt.offline = False

            def job():
                try:
                    return wt.search_person(first, last, year)
                finally:
                    wt.offline = was_offline

            def done(ids):
                w_results.controls = tiles(ids) or [hint("WikiTree hat nichts gefunden.")]
            self.run_bg(job, done, "Suche bei WikiTree …")

        return section(
            "3 · Startpaar",
            ft.Text("Dieselbe Person auf beiden Seiten. Von ihr aus wird der Stammbaum abgelaufen.", size=12),
            ft.Text(f"GEDCOM: {g_cur}", weight=ft.FontWeight.W_500), g_query, g_results,
            ft.Divider(height=1),
            ft.Text(f"WikiTree: {w_cur}", weight=ft.FontWeight.W_500), w_query, w_results)

    def _mapping_section(self):
        p, wt = self.project, self.wt
        m = p.mappings
        rows = []
        ged = None
        if p.has_gedcom and (m.manual or m.ignored):
            try:
                ged = p.gedcom()
            except Exception:
                ged = None
        for k, x in m.manual.items():
            wid = int(k)
            gname = ged.indi[x].label() if ged and x in ged.indi else "(nicht mehr in der GEDCOM)"
            rows.append(ft.ListTile(title=ft.Text(f"{wt.label(wid)}  <->  {gname}"), dense=True,
                                    subtitle=ft.Text(f"{wt.wtid(wid)} <-> {x}"),
                                    trailing=ft.IconButton(ft.Icons.LINK_OFF, tooltip="Zuordnung lösen",
                                                           on_click=lambda e, w=wid: self._unassign(w))))
        for wid in m.ignored:
            rows.append(ft.ListTile(title=ft.Text(f"{wt.label(wid)}  <->  kein Gegenstück"), dense=True,
                                    subtitle=ft.Text(wt.wtid(wid)),
                                    trailing=ft.IconButton(ft.Icons.LINK_OFF, tooltip="Markierung entfernen",
                                                           on_click=lambda e, w=wid: self._unignore(w))))
        return section("Manuelle Zuordnungen", *(rows or [hint("Keine. Zuordnen geht im Ergebnis unter „Ohne Zuordnung“.")]))

    # ================================================================ Zuordnen
    def _mapping_changed(self, msg):
        self.pending_mapping = True
        self.toast(msg + " Wirkt beim nächsten Vergleich.")
        self.refresh()

    def _unassign(self, wid):
        self.project.set_manual(wid, None)
        self._mapping_changed("Zuordnung gelöst.")

    def _unignore(self, wid):
        self.project.set_ignored(wid, False)
        self._mapping_changed("Markierung entfernt.")

    def assign_dialog(self, u: dict):
        p = self.project
        wid = u.get("wid") or self.wt.name_to_id.get(u["w"])
        if wid is None:
            self.toast("WikiTree-Profil nicht im Cache.")
            return
        ged = p.gedcom()
        results = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, height=260)

        def pick(xref):
            p.set_manual(int(wid), xref)
            self.page.pop_dialog()
            self._mapping_changed(f"{u['wname']} <-> {ged.indi[xref].label()} zugeordnet.")

        def none(e):
            p.set_ignored(int(wid), True)
            self.page.pop_dialog()
            self._mapping_changed(f"{u['wname']}: als „kein Gegenstück“ markiert.")

        def fill(hits):
            results.controls = [ft.ListTile(title=ft.Text(x.label()), subtitle=ft.Text(f"{x.xref}  ·  {s:.2f}"),
                                            dense=True, on_click=lambda e, x=x.xref: pick(x)) for s, x in hits] \
                or [hint("Keine Treffer.")]

        fill([(c["s"], ged.indi[c["g"]]) for c in u.get("cands", []) if c["g"] in ged.indi])
        q = ft.TextField(label="GEDCOM durchsuchen", prefix_icon=ft.Icons.SEARCH, value=u["wname"].split(" (")[0],
                         on_submit=lambda e: (fill(ged.search(q.value or "", 30)), results.update()))
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Zuordnen: {u['wname']}"),
            content=ft.Column([hint(f"WikiTree {u['w']}. Vorschläge oder Suche:"), q, results], tight=True, width=520),
            actions=[ft.TextButton("Kein Gegenstück", icon=ft.Icons.DO_NOT_DISTURB_ON_OUTLINED, on_click=none),
                     ft.TextButton("Abbrechen", on_click=lambda e: self.page.pop_dialog())]))

    # ================================================================ Ergebnis
    def view_result(self):
        res = self.result
        if not res:
            return ft.ListView([section("Noch kein Ergebnis",
                                        hint("Unter „Einrichten“ den Vergleich starten."))], padding=12, expand=True)
        P = [x for x in res["persons"] if not self.only_wl or x["watch"]]
        n_diff = sum(1 for x in P for f in x["f"] if f["status"] == "abweichend")
        n_mw = sum(1 for m in res["missing"] if m["status"] == "fehlt auf WikiTree")
        n_mg = sum(1 for m in res["missing"] if m["status"] == "fehlt in GEDCOM")
        stats = ft.Row([stat(len(P), "zugeordnet"), stat(n_diff, "Abweichungen"), stat(n_mw, "fehlen auf WikiTree"),
                        stat(n_mg, "fehlen in GEDCOM"), stat(len(res["unmatched"]), "ohne Zuordnung")],
                       wrap=True, spacing=8, run_spacing=8)

        def set_tab(e):
            self.res_tab = next(iter(e.control.selected))
            self.res_limit = PAGE_SIZE
            self.refresh()

        tabs = ft.SegmentedButton(
            segments=[ft.Segment(value="p", label=ft.Text("Vergleich")),
                      ft.Segment(value="m", label=ft.Text("Fehlende")),
                      ft.Segment(value="u", label=ft.Text("Ohne Zuordnung"))],
            selected=[self.res_tab], on_change=set_tab)

        def set_q(e):
            self.res_query = e.control.value or ""
            self.res_limit = PAGE_SIZE
            self.refresh()

        def flag(attr):
            def h(e):
                setattr(self, attr, e.control.value)
                self.res_limit = PAGE_SIZE
                self.refresh()
            return h

        query = ft.TextField(label="Name, WikiTree-ID oder GEDCOM-ID", prefix_icon=ft.Icons.SEARCH,
                             value=self.res_query, on_submit=set_q)
        filters = ft.Row([
            ft.Checkbox(label="nur Unterschiede", value=self.only_diff, on_change=flag("only_diff")),
            ft.Checkbox(label="„ähnlich“ ausblenden", value=self.hide_similar, on_change=flag("hide_similar")),
            ft.Checkbox(label="nur Watchlist", value=self.only_wl, on_change=flag("only_wl"))], wrap=True)

        async def export(kind):
            data = html_bytes(res) if kind == "html" else csv_bytes(res)
            stamp = res["meta"].get("created", "")[:16].replace(":", "").replace("T", "-")
            path = await self.file_picker.save_file(dialog_title="Bericht speichern",
                                                    file_name=f"vergleich-{stamp}.{kind}", src_bytes=data)
            if path:
                self.toast(f"Gespeichert: {path}")

        head = [
            hint(res["meta"].get("info", "")),
            stats,
            ft.Row([ft.OutlinedButton("HTML", icon=ft.Icons.DOWNLOAD, on_click=lambda e: self.page.run_task(export, "html")),
                    ft.OutlinedButton("CSV", icon=ft.Icons.DOWNLOAD, on_click=lambda e: self.page.run_task(export, "csv"))],
                   wrap=True),
        ]
        if self.pending_mapping:
            head.append(ft.FilledButton("Zuordnungen geändert: neu vergleichen", icon=ft.Icons.PLAY_ARROW,
                                        disabled=self.busy,
                                        on_click=lambda e: self.run_bg(lambda: self.project.run(self.wt, log=self.log),
                                                                       self._run_done, "Vergleich läuft …")))
        if self.busy:
            head.append(ft.ProgressBar())
        head += [tabs, query]
        if self.res_tab == "p":
            head.append(filters)
        items = {"p": self._persons_items, "m": self._missing_items, "u": self._unmatched_items}[self.res_tab](res)
        return ft.ListView([*head, *items], padding=12, spacing=8, expand=True)

    def _match(self, *fields) -> bool:
        q = self.res_query.lower().strip()
        return not q or q in " ".join(str(f) for f in fields).lower()

    def _keep(self, f) -> bool:
        if self.only_diff and f["status"] == "gleich":
            return False
        if self.hide_similar and f["status"] == "ähnlich":
            return False
        return True

    def _more(self, total, shown):
        if total <= shown:
            return []

        def more(e):
            self.res_limit += PAGE_SIZE
            self.refresh()
        return [ft.TextButton(f"Weitere anzeigen ({total - shown} übrig)", on_click=more)]

    def _persons_items(self, res):
        rows = []
        for x in res["persons"]:
            if self.only_wl and not x["watch"]:
                continue
            if not self._match(x["gname"], x["wname"], x["w"], x["g"]):
                continue
            fs = [f for f in x["f"] if self._keep(f)]
            if not fs and self.only_diff:
                continue
            rows.append((x, fs))
        out = []
        for x, fs in rows[:self.res_limit]:
            title = ft.Row([self.wt_link(x["w"]), ft.Text(x["wname"], weight=ft.FontWeight.BOLD),
                            *([ft.Text("Watchlist", size=11, color=ft.Colors.ON_SURFACE_VARIANT)] if x["watch"] else [])],
                           wrap=True, spacing=4)
            sub = hint(f"GEDCOM {x['g']}: {x['gname']} · {x['how']}")
            lines = []
            for f in fs:
                vals = []
                if f["ged"]:
                    vals.append(f"GEDCOM: {f['ged']}")
                if f["wt"]:
                    vals.append(f"WikiTree: {f['wt']}")
                lines.append(ft.Column([
                    ft.Row([ft.Text(f["kat"], weight=ft.FontWeight.W_500, width=110), status_chip(f["status"])],
                           wrap=True),
                    *([ft.Text("   ·   ".join(vals), size=13, selectable=True)] if vals else []),
                    *([hint(f["hinweis"])] if f["hinweis"] else [])], spacing=2))
            actions = []
            if x["how"] == "manuell zugeordnet":
                wid = x.get("wid") or self.wt.name_to_id.get(x["w"])
                if wid:
                    actions.append(ft.TextButton("Zuordnung lösen", icon=ft.Icons.LINK_OFF,
                                                 on_click=lambda e, w=wid: self._unassign(w)))
            out.append(ft.Card(ft.Container(ft.Column([title, sub, ft.Divider(height=1), *lines, *actions],
                                                      spacing=6), padding=12)))
        if not rows:
            out.append(hint("Keine Einträge für diesen Filter."))
        return out + self._more(len(rows), min(len(rows), self.res_limit))

    def copy(self, text: str, what: str = ""):
        async def job():
            await self.clipboard.set(text)
            self.toast(f"Kopiert: {what}" if what else "In die Zwischenablage kopiert.")
        self.page.run_task(job)

    def _details_view(self, details: dict) -> ft.Control:
        ctl = []
        for sec in details.get("sections", []):
            ctl.append(ft.Text(sec["title"], weight=ft.FontWeight.BOLD))
            for r in sec["rows"]:
                ctl.append(ft.Row([
                    ft.Text(r["label"], size=12, color=ft.Colors.ON_SURFACE_VARIANT, width=130),
                    ft.Text(r["value"], size=13, selectable=True, expand=True),
                    ft.IconButton(ft.Icons.CONTENT_COPY, icon_size=16, tooltip="Kopieren",
                                  on_click=lambda e, r=r: self.copy(r.get("copy", r["value"]), r["label"])),
                ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=6))
        return ft.Column(ctl or [hint("Keine weiteren Angaben vorhanden.")], spacing=2)

    def _missing_items(self, res):
        M = [m for m in res["missing"] if self._match(m["who"], m["rel"], m["wid"], m["g"])]
        out = []
        for m in M[:self.res_limit]:
            on_wt = m["status"] == "fehlt auf WikiTree"
            details = m.get("details")
            box = ft.Container()
            buttons = []
            if on_wt:
                anchor = m.get("anchor") or m["wid"]
                name = (m.get("anchor_name") or anchor).split(" (")[0]
                buttons.append(ft.TextButton(f"{name} auf WikiTree öffnen", icon=ft.Icons.OPEN_IN_NEW,
                                             on_click=lambda e, a=anchor: self.open_url(
                                                 f"https://www.wikitree.com/wiki/{a}")))
            else:
                buttons.append(self.wt_link(m["wid"]))
            if details:
                def toggle(e, box=box, details=details):
                    box.content = None if box.content else self._details_view(details)
                    e.control.content = "Profildaten ausblenden" if box.content else "Profildaten anzeigen"
                    box.update()
                    e.control.update()
                buttons.append(ft.TextButton("Profildaten anzeigen", icon=ft.Icons.EXPAND_MORE, on_click=toggle))
                buttons.append(ft.TextButton("Alles kopieren", icon=ft.Icons.CONTENT_COPY,
                                             on_click=lambda e, m=m: self.copy(
                                                 as_text(m["details"], f"{m['who']} – {m['rel']}"), m["who"])))
            out.append(ft.Card(ft.Container(ft.Column([
                ft.Row([status_chip(m["status"]), ft.Text(m["who"], weight=ft.FontWeight.W_500)], wrap=True),
                hint(f"{m['rel']} · GEDCOM {m['g']}" if on_wt else f"{m['rel']} · WikiTree {m['wid']}"),
                ft.Row(buttons, wrap=True, spacing=0), box], spacing=4), padding=12)))
        if not M:
            out.append(hint("Keine fehlenden Personen gefunden."))
        elif not any(m.get("details") for m in M):
            out.insert(0, hint("Profildaten gibt es erst ab dem nächsten Vergleich (ältere Läufe enthalten sie nicht)."))
        return out + self._more(len(M), min(len(M), self.res_limit))

    def _unmatched_items(self, res):
        p = self.project
        manual = {int(k) for k in p.mappings.manual}
        ignored = set(p.mappings.ignored)
        U = [u for u in res["unmatched"] if self._match(u["w"], u["wname"])]
        out = []
        for u in U[:self.res_limit]:
            wid = u.get("wid") or self.wt.name_to_id.get(u["w"])
            if wid in manual:
                state = [hint(f"Zugeordnet zu {p.mappings.manual[str(wid)]} – wirkt beim nächsten Vergleich."),
                         ft.TextButton("Zuordnung lösen", icon=ft.Icons.LINK_OFF, on_click=lambda e, w=wid: self._unassign(w))]
            elif wid in ignored:
                state = [hint("Als „kein Gegenstück“ markiert."),
                         ft.TextButton("Markierung entfernen", on_click=lambda e, w=wid: self._unignore(w))]
            else:
                cands = [ft.Text(f"{c['name']}  [{c['g']}] {c['s']}", size=13) for c in u["cands"]] \
                    or [hint("kein Kandidat")]
                state = [*cands, ft.FilledButton("Zuordnen …", icon=ft.Icons.COMPARE_ARROWS,
                                                 on_click=lambda e, u=u: self.assign_dialog(u))]
            out.append(ft.Card(ft.Container(ft.Column([
                ft.Row([self.wt_link(u["w"]), ft.Text(u["wname"], weight=ft.FontWeight.W_500)], wrap=True),
                *state], spacing=4), padding=12)))
        if not U:
            out.append(hint("Alle Watchlist-Profile wurden zugeordnet."))
        return out + self._more(len(U), min(len(U), self.res_limit))

    # ================================================================ Verlauf
    def view_history(self):
        p = self.project
        runs = p.runs()
        if not runs:
            return ft.ListView([section("Verlauf", hint("Noch keine gespeicherten Läufe."))], padding=12, expand=True)

        def label(path: Path):
            try:
                meta = p.load_run(path)["meta"]
                return f"{_fmt_ts(meta.get('created', ''), True)} · {meta.get('info', '').split(' · ')[0]}"
            except Exception:
                return path.name

        labels = {r.name: label(r) for r in runs}
        opts = [ft.DropdownOption(key=r.name, text=labels[r.name]) for r in runs]
        old_dd = ft.Dropdown(label="Älterer Lauf", options=opts, value=runs[1].name if len(runs) > 1 else runs[0].name)
        new_dd = ft.Dropdown(label="Neuerer Lauf", options=list(opts), value=runs[0].name)
        out = ft.Column(spacing=6)

        def compare(e=None):
            if old_dd.value == new_dd.value:
                out.controls = [hint("Zwei verschiedene Läufe wählen.")]
            else:
                d = diff_runs(p.load_run(p.runs_dir / old_dd.value), p.load_run(p.runs_dir / new_dd.value))
                out.controls = self._diff_controls(d)
            if e is not None:
                out.update()

        def show_run(path):
            self.result = p.load_run(path)
            self.res_limit = PAGE_SIZE
            self.show(2)

        def delete_run(path):
            p.delete_run(path)
            if self.result and self.result["meta"].get("file") == path.name:
                self.result = None
            self.refresh()

        if len(runs) > 1:
            compare()
        run_list = [ft.ListTile(title=ft.Text(labels[r.name]), dense=True, on_click=lambda e, r=r: show_run(r),
                                trailing=ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Lauf löschen",
                                                       on_click=lambda e, r=r: delete_run(r)))
                    for r in runs]
        return ft.ListView([
            section("Läufe vergleichen", ft.Row([old_dd, new_dd], wrap=True),
                    ft.Button("Vergleichen", icon=ft.Icons.COMPARE_ARROWS, on_click=compare), out),
            section("Gespeicherte Läufe", *run_list, subtitle="Antippen zeigt das Ergebnis dieses Laufs."),
        ], padding=12, spacing=8, expand=True)

    def _diff_controls(self, d):
        summ = d["summary"]
        ctl = [ft.Row([stat(summ.get("neue Abweichung", 0), "neue Abweichungen"),
                       stat(summ.get("behoben", 0), "behoben"),
                       stat(summ.get("neu zugeordnet", 0), "neu zugeordnet"),
                       stat(len(d["missing_gone"]), "fehlen nicht mehr"),
                       stat(len(d["missing_new"]), "fehlen neu")], wrap=True, spacing=8, run_spacing=8)]
        for c in d["changes"][:300]:
            ctl.append(ft.Container(ft.Column([
                ft.Row([status_chip(c["art"]), ft.Text(f"{c['name']} · {c['kat']}", weight=ft.FontWeight.W_500)],
                       wrap=True),
                *([hint(f"vorher: {c['alt']}")] if c["alt"] else []),
                *([hint(f"jetzt: {c['neu']}")] if c["neu"] else [])], spacing=2),
                padding=ft.Padding.symmetric(vertical=4)))
        if len(d["changes"]) > 300:
            ctl.append(hint(f"… und {len(d['changes']) - 300} weitere Änderungen."))
        for title, lst in (("Fehlen jetzt nicht mehr", d["missing_gone"]), ("Fehlen neu", d["missing_new"])):
            if lst:
                ctl.append(ft.Text(title, weight=ft.FontWeight.BOLD))
                ctl += [hint(f"{m['status']}: {m['who']} ({m['rel']})") for m in lst[:100]]
        for title, lst in (("Neu ohne Zuordnung", d["unmatched_new"]), ("Jetzt zugeordnet", d["unmatched_gone"])):
            if lst:
                ctl.append(ft.Text(title, weight=ft.FontWeight.BOLD))
                ctl += [hint(f"{u['w']}: {u['wname']}") for u in lst[:100]]
        if not d["changes"] and not any(d[k] for k in ("missing_new", "missing_gone", "unmatched_new", "unmatched_gone")):
            ctl.append(hint("Keine Unterschiede zwischen den beiden Läufen."))
        return ctl
