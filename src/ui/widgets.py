"""Kleine wiederverwendbare Bausteine der Oberfläche."""

from __future__ import annotations

import flet as ft

STATUS_COLOR = {
    "abweichend": ft.Colors.ERROR,
    "nur GEDCOM": ft.Colors.ORANGE_800,
    "nur WikiTree": ft.Colors.ORANGE_800,
    "fehlt auf WikiTree": ft.Colors.ORANGE_800,
    "fehlt in GEDCOM": ft.Colors.ORANGE_800,
    "genauer GEDCOM": ft.Colors.BLUE_700,
    "genauer WikiTree": ft.Colors.BLUE_700,
    "ähnlich": ft.Colors.ON_SURFACE_VARIANT,
    "gleich": ft.Colors.GREEN_700,
    "neue Abweichung": ft.Colors.ERROR,
    "andere GEDCOM-Person": ft.Colors.ERROR,
    "nicht mehr zugeordnet": ft.Colors.ORANGE_800,
    "Status geändert": ft.Colors.BLUE_700,
    "Wert geändert": ft.Colors.BLUE_700,
    "behoben": ft.Colors.GREEN_700,
    "neu zugeordnet": ft.Colors.GREEN_700,
}


def status_chip(status: str) -> ft.Control:
    return ft.Container(
        ft.Text(status, size=12, color=STATUS_COLOR.get(status), weight=ft.FontWeight.W_500),
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        border_radius=ft.BorderRadius.all(12),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )


def section(title: str, *controls: ft.Control, subtitle: str = "") -> ft.Control:
    head = [ft.Text(title, size=16, weight=ft.FontWeight.BOLD)]
    if subtitle:
        head.append(ft.Text(subtitle, size=12, color=ft.Colors.ON_SURFACE_VARIANT))
    return ft.Card(ft.Container(ft.Column([*head, *controls], spacing=8), padding=14))


def stat(value, label: str) -> ft.Control:
    return ft.Container(
        ft.Column([ft.Text(str(value), size=18, weight=ft.FontWeight.BOLD),
                   ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT)], spacing=0, tight=True),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=ft.BorderRadius.all(10),
    )


def hint(text: str) -> ft.Text:
    return ft.Text(text, size=12, color=ft.Colors.ON_SURFACE_VARIANT)
