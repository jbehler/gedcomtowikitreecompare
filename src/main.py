"""Einstiegspunkt der App (Flet). Start am PC: `flet run` im Projektordner."""

import os
from pathlib import Path

import flet as ft

from ui.app import App


async def main(page: ft.Page):
    page.title = "WikiTree <-> GEDCOM"
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0

    data = os.environ.get("FLET_APP_STORAGE_DATA") or os.environ.get("WTCOMPARE_DATA")
    if not data and not page.web:
        try:
            data = await ft.StoragePaths().get_application_support_directory()
        except Exception:
            data = None
    data_dir = Path(data) if data else Path.home() / ".wtcompare"
    data_dir.mkdir(parents=True, exist_ok=True)
    App(page, data_dir)


# Wie im offiziellen Flet-Beispiel ohne __name__-Abfrage: so startet die App auch, wenn
# flet build / der Android-Starter main.py nicht als __main__ ausführt.
if os.environ.get("WTCOMPARE_NO_AUTORUN") != "1":
    ft.run(main)
